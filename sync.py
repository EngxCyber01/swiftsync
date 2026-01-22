import json
import logging
import os
import re
import sqlite3
from datetime import datetime
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
                upload_date TEXT,
                subject TEXT,
                filename TEXT
            )
            """
        )
        conn.commit()


def _seen(item_id: str) -> bool:
    """
    Check if a lecture has already been downloaded.
    This prevents duplicate downloads and duplicate Telegram notifications
    when Render free tier wakes up from sleep.
    """
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute("SELECT 1 FROM synced_items WHERE id = ?", (item_id,))
        return cur.fetchone() is not None


def _mark_seen(item_id: str, subject: str = None, filename: str = None, upload_date: str = None) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO synced_items (id, subject, filename, upload_date) VALUES (?, ?, ?, ?)", 
            (item_id, subject, filename, upload_date)
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
    
    # Find 2025-2026 year section
    for year_section in soup.find_all('span', class_='float-left font-weight-bold'):
        year_text = year_section.get_text(strip=True)
        if '2025-2026' not in year_text:
            continue
            
        logger.info("Found academic year section: %s", year_text)
        card = year_section.find_parent('div', class_='card')
        if not card:
            continue
        
        # Use regex on the HTML string to extract subjects and their file IDs
        card_html = str(card)
        download_pattern = r'DownloadClassSessionFile\?id=([a-f0-9\-]+)'
        
        # Split by subject headers: <p class="m-0 float-left font-weight-bold">SUBJECT_NAME</p>
        # Pattern to find subject headers
        subject_pattern = r'<p class="m-0 float-left font-weight-bold">([^<]+)</p>'
        
        # Find all subject headers with their positions
        subject_matches = list(re.finditer(subject_pattern, card_html))
        
        if not subject_matches:
            logger.warning("No subject headers found, using fallback")
            all_file_ids = re.findall(download_pattern, card_html)
            subjects_data['All Lectures'] = list(set(all_file_ids))
            logger.info("Found %d files in fallback mode", len(subjects_data['All Lectures']))
        else:
            seen_file_ids = set()
            
            for i, match in enumerate(subject_matches):
                subject_name = match.group(1).strip()
                
                # Skip semester headers
                if subject_name in ['Fall Semester', 'Spring Semester', 'Summer Semester'] or len(subject_name) < 5:
                    continue
                
                # Get HTML between this subject and the next one
                start_pos = match.end()
                if i + 1 < len(subject_matches):
                    # Find the next valid subject (not a semester header)
                    next_pos = None
                    for j in range(i + 1, len(subject_matches)):
                        next_subject = subject_matches[j].group(1).strip()
                        if next_subject not in ['Fall Semester', 'Spring Semester', 'Summer Semester'] and len(next_subject) >= 5:
                            next_pos = subject_matches[j].start()
                            break
                    if next_pos:
                        end_pos = next_pos
                    else:
                        end_pos = len(card_html)
                else:
                    end_pos = len(card_html)
                
                # Extract file IDs from this subject's section
                subject_html = card_html[start_pos:end_pos]
                file_ids = re.findall(download_pattern, subject_html)
                
                # Remove duplicates
                unique_file_ids = [fid for fid in file_ids if fid not in seen_file_ids]
                
                if unique_file_ids:
                    subjects_data[subject_name] = unique_file_ids
                    seen_file_ids.update(unique_file_ids)
                    logger.info("Found %d unique files in subject: %s", len(unique_file_ids), subject_name)
            
            if not subjects_data:
                # Fallback if no valid subjects found
                logger.warning("No valid subjects found, using fallback")
                all_file_ids = re.findall(download_pattern, card_html)
                subjects_data['All Lectures'] = list(set(all_file_ids))
                logger.info("Found %d files in fallback mode", len(subjects_data['All Lectures']))
    
    total_files = sum(len(v) for v in subjects_data.values())
    logger.info("Total subjects: %d, Total files: %d", len(subjects_data), total_files)
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


def download_material(session: requests.Session, item_id: str) -> Tuple[Path, str]:
    params = {"id": item_id}
    response = session.get(DOWNLOAD_ENDPOINT, params=params, stream=True)
    
    # Handle authentication failures
    if response.status_code in (401, 403):
        raise AuthError(f"Download API returned {response.status_code}. Session expired or unauthorized.")
    
    if response.status_code != 200:
        raise RuntimeError(f"Download failed for id={item_id}: {response.status_code}")

    filename = _resolve_filename(response, item_id)
    target = DOWNLOAD_DIR / filename
    
    # Extract upload date from Last-Modified header
    upload_date = response.headers.get("Last-Modified", "")
    if not upload_date:
        # Fallback to current date if server doesn't provide Last-Modified
        upload_date = datetime.now().isoformat()
    else:
        # Convert from HTTP date format to ISO format for consistency
        from email.utils import parsedate_to_datetime
        try:
            dt = parsedate_to_datetime(upload_date)
            upload_date = dt.isoformat()
        except Exception:
            upload_date = datetime.now().isoformat()

    with open(target, "wb") as file:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                file.write(chunk)

    return target, upload_date


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
                    path, upload_date = download_material(session, item_id)
                    _mark_seen(item_id, subject, path.name, upload_date)
                    new_files.append(path)
                    logger.info("Successfully downloaded: %s (Upload date: %s)", path.name, upload_date)
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
                path, upload_date = download_material(session, item_id)
                _mark_seen(item_id, None, path.name, upload_date)
                new_files.append(path)
                logger.info("Successfully downloaded: %s (Upload date: %s)", path.name, upload_date)
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
