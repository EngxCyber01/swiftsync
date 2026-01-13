import json
import logging
import os
import re
import sqlite3
from pathlib import Path
from typing import Iterable, List, Tuple

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from auth import AuthClient, AuthConfig, AuthError

load_dotenv()
logger = logging.getLogger(__name__)

APP_BASE_URL = os.getenv("APP_BASE_URL", "https://tempapp-su.awrosoft.com")
SESSIONS_ENDPOINT = f"{APP_BASE_URL}/University/ClassSession/GetStudentClassSessionsList"
DOWNLOAD_ENDPOINT = f"{APP_BASE_URL}/University/ClassSessionFile/DownloadClassSessionFile"

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DOWNLOAD_DIR = ROOT / "lectures_storage"
DB_PATH = DATA_DIR / "lecture_sync.db"

SYNC_INTERVAL_SECONDS = int(os.getenv("SYNC_INTERVAL_SECONDS", "3600"))


def _ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _init_db() -> None:
    _ensure_dirs()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS synced_items (
                id TEXT PRIMARY KEY,
                downloaded_at TEXT DEFAULT (datetime('now')),
                subject TEXT,
                filename TEXT
            )
            """
        )
        conn.commit()


def _seen(item_id: str) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute("SELECT 1 FROM synced_items WHERE id = ?", (item_id,))
        return cur.fetchone() is not None


def _mark_seen(item_id: str, subject: str = None, filename: str = None) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO synced_items (id, subject, filename) VALUES (?, ?, ?)", 
            (item_id, subject, filename)
        )
        conn.commit()


def _extract_ids(timeline: Iterable) -> List[str]:
    ids: List[str] = []
    for entry in timeline:
        if isinstance(entry, dict):
            # Log each entry to see structure
            logger.debug("Processing timeline entry: %s", str(entry)[:200])
            for key in ("id", "Id", "materialId", "MaterialId", "fileId", "FileId", "documentId", "DocumentId"):
                if key in entry:
                    ids.append(str(entry[key]))
                    logger.debug("Found ID '%s' in key '%s'", entry[key], key)
        if isinstance(entry, (list, tuple)):
            ids.extend(_extract_ids(entry))
    return ids


def fetch_timeline(session: requests.Session) -> List[str]:
    """Fetch list of file IDs from the sessions HTML page (2025-2026 only)"""
    logger.info("Fetching class sessions from %s", SESSIONS_ENDPOINT)
    
    response = session.get(SESSIONS_ENDPOINT)
    
    # Handle authentication failures
    if response.status_code in (401, 403):
        raise AuthError(f"Sessions API returned {response.status_code}. Session expired or unauthorized.")
    
    if response.status_code != 200:
        raise RuntimeError(f"Sessions API returned {response.status_code}: {response.text[:200]}")

    # The endpoint returns HTML with download links
    # Filter to only include 2025-2026 academic year
    soup = BeautifulSoup(response.text, 'html.parser')
    file_ids = []
    
    # Find all year sections
    for year_section in soup.find_all('span', class_='float-left font-weight-bold'):
        year_text = year_section.get_text(strip=True)
        if '2025-2026' in year_text:
            # Find the parent card that contains this year
            card = year_section.find_parent('div', class_='card')
            if card:
                # Extract all download links within this card
                download_pattern = r'DownloadClassSessionFile\?id=([a-f0-9\-]+)'
                matches = re.findall(download_pattern, str(card))
                file_ids.extend(matches)
                logger.info("Found %d files in %s section", len(matches), year_text)
    
    logger.info("Total file IDs from 2025-2026: %d", len(file_ids))
    return file_ids


def fetch_timeline_with_subjects(session: requests.Session) -> dict:
    """Fetch file IDs with their subject information (2025-2026 only)"""
    logger.info("Fetching class sessions with subjects from %s", SESSIONS_ENDPOINT)
    
    response = session.get(SESSIONS_ENDPOINT)
    
    if response.status_code in (401, 403):
        raise AuthError(f"Sessions API returned {response.status_code}. Session expired or unauthorized.")
    
    if response.status_code != 200:
        raise RuntimeError(f"Sessions API returned {response.status_code}: {response.text[:200]}")

    soup = BeautifulSoup(response.text, 'html.parser')
    subjects_data = {}
    seen_file_ids = set()  # Track globally to avoid duplicates across subjects
    
    # Find 2025-2026 year section
    for year_section in soup.find_all('span', class_='float-left font-weight-bold'):
        year_text = year_section.get_text(strip=True)
        # ONLY process 2025-2026 academic year
        if '2025-2026' in year_text:
            logger.info("Found academic year section: %s", year_text)
            card = year_section.find_parent('div', class_='card')
            if card:
                # Find all subject headers: <p class="m-0 float-left font-weight-bold">
                # Beautiful Soup stores classes as a list
                all_p_tags = card.find_all('p')
                
                for p_tag in all_p_tags:
                    classes = p_tag.get('class', [])
                    # Check if it has the required classes
                    if 'm-0' in classes and 'float-left' in classes and 'font-weight-bold' in classes:
                        subject_name = p_tag.get_text(strip=True)
                        
                        # Skip semester headers and empty names
                        if not subject_name or len(subject_name) < 5:
                            continue
                        if subject_name in ['Fall Semester', 'Spring Semester', 'Summer Semester']:
                            logger.debug("Skipping semester header: %s", subject_name)
                            continue
                        
                        # Find the parent container
                        container = p_tag.find_parent('div', class_='card-body')
                        if not container:
                            container = p_tag.find_parent('div')
                        
                        if container:
                            # Extract file IDs - search in siblings after this p tag
                            download_pattern = r'DownloadClassSessionFile\?id=([a-f0-9\-]+)'
                            
                            # Get all siblings after this subject header until the next one
                            sibling_html = ""
                            current_elem = p_tag.find_next_sibling()
                            while current_elem:
                                # Stop if we hit another subject header
                                if current_elem.name == 'p':
                                    elem_classes = current_elem.get('class', [])
                                    if 'm-0' in elem_classes and 'float-left' in elem_classes and 'font-weight-bold' in elem_classes:
                                        break
                                sibling_html += str(current_elem)
                                current_elem = current_elem.find_next_sibling()
                            
                            if not sibling_html:
                                # If no siblings, use the whole container
                                sibling_html = str(container)
                            
                            matches = re.findall(download_pattern, sibling_html)
                        
                        # Filter out already seen IDs to avoid duplicates
                        new_matches = [m for m in matches if m not in seen_file_ids]
                        
                        if new_matches:
                            subjects_data[subject_name] = new_matches
                            seen_file_ids.update(new_matches)
                            logger.info("Found %d unique files in subject: %s", len(new_matches), subject_name)
    
    if not subjects_data:
        logger.warning("No subjects found, extracting all files from 2025-2026")
        # Fallback: extract all files under one category
        for year_section in soup.find_all('span', class_='float-left font-weight-bold'):
            year_text = year_section.get_text(strip=True)
            if '2025-2026' in year_text:
                card = year_section.find_parent('div', class_='card')
                if card:
                    download_pattern = r'DownloadClassSessionFile\?id=([a-f0-9\-]+)'
                    matches = re.findall(download_pattern, str(card))
                    subjects_data['All Lectures'] = list(set(matches))
                    logger.info("Found %d files in fallback mode", len(subjects_data['All Lectures']))
    
    logger.info("Total subjects: %d, Total files: %d", len(subjects_data), len(seen_file_ids))
    return subjects_data


def _resolve_filename(response: requests.Response, item_id: str) -> str:
    """Parse filename from Content-Disposition header"""
    disposition = response.headers.get("Content-Disposition", "")
    if "filename=" in disposition:
        # Handle both formats: 
        # filename="name.ext" 
        # filename=name.ext; filename*=UTF-8''encoded-name.ext
        parts = disposition.split(";")
        for part in parts:
            part = part.strip()
            if part.startswith("filename=") and not part.startswith("filename*="):
                name = part[9:].strip().strip("\"'")
                return name or f"material-{item_id}"
    return f"material-{item_id}"


def download_material(session: requests.Session, item_id: str) -> Path:
    params = {"id": item_id}
    response = session.get(DOWNLOAD_ENDPOINT, params=params, stream=True)
    
    # Handle authentication failures
    if response.status_code in (401, 403):
        raise AuthError(f"Download API returned {response.status_code}. Session expired or unauthorized.")
    
    if response.status_code != 200:
        raise RuntimeError(f"Download failed for id={item_id}: {response.status_code}")

    filename = _resolve_filename(response, item_id)
    target = DOWNLOAD_DIR / filename

    with open(target, "wb") as file:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                file.write(chunk)

    return target


def sync_once(auth_client: AuthClient) -> Tuple[int, List[Path]]:
    _init_db()
    session = auth_client.get_authenticated_session()
    new_files: List[Path] = []

    logger.info("Starting sync cycle...")
    
    # Try to fetch with subjects first
    try:
        subjects_data = fetch_timeline_with_subjects(session)
        # Flatten into list with subject info
        for subject, ids in subjects_data.items():
            for item_id in ids:
                if _seen(item_id):
                    logger.debug("Skipping already downloaded ID: %s", item_id)
                    continue
                try:
                    logger.info("Downloading material with ID: %s (Subject: %s)", item_id, subject)
                    path = download_material(session, item_id)
                    _mark_seen(item_id, subject, path.name)
                    new_files.append(path)
                    logger.info("Successfully downloaded: %s", path.name)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Failed to download id=%s: %s", item_id, exc)
    except Exception as e:
        # Fallback to old method without subjects
        logger.warning("Failed to fetch with subjects, using fallback: %s", e)
        ids = fetch_timeline(session)
        
        if not ids:
            logger.warning("No lecture IDs found in timeline response.")
            return 0, new_files

        logger.info("Found %d total IDs in timeline", len(ids))
        
        for item_id in ids:
            if _seen(item_id):
                logger.debug("Skipping already downloaded ID: %s", item_id)
                continue
            try:
                logger.info("Downloading material with ID: %s", item_id)
                path = download_material(session, item_id)
                _mark_seen(item_id, None, path.name)
                new_files.append(path)
                logger.info("Successfully downloaded: %s", path.name)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Failed to download id=%s: %s", item_id, exc)

    logger.info("Sync cycle completed: %d new files downloaded", len(new_files))
    return len(new_files), new_files


def sync_forever(auth_client: AuthClient) -> None:
    import time

    while True:
        try:
            count, files = sync_once(auth_client)
            logger.info("Sync completed: %d new files downloaded", count)
        except AuthError as exc:
            logger.warning("Authentication failed: %s. Re-authenticating...", exc)
            try:
                auth_client.login()
            except Exception as login_exc:  # noqa: BLE001
                logger.exception("Failed to re-authenticate: %s", login_exc)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected error in sync loop: %s", exc)
        time.sleep(SYNC_INTERVAL_SECONDS)
