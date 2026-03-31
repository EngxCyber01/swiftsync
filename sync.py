import json
import logging
import os
import re
import sqlite3
import pytz
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
SESSIONS_ENDPOINTS = [
    SESSIONS_ENDPOINT,
    f"{APP_BASE_URL}/University/ClassSession/GetStudentClassSessionList",
    f"{APP_BASE_URL}/University/ClassSessions/GetStudentClassSessionsList",
]
DOWNLOAD_ENDPOINT = f"{APP_BASE_URL}/University/ClassSessionFile/DownloadClassSessionFile"

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DOWNLOAD_DIR = ROOT / "lectures_storage"
DB_PATH = DATA_DIR / "lecture_sync.db"

SYNC_INTERVAL_SECONDS = int(os.getenv("SYNC_INTERVAL_SECONDS", "1800"))

GENERIC_SUBJECTS = {
    "",
    "other",
    "all lectures",
    "general lectures",
    "unknown",
    "unknown subject",
    "بابەتی جیاواز",
}


def _ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _get_semester_from_subject(subject: str) -> str:
    """Determine semester based on subject name"""
    fall_subjects = [
        'Combinatorics and Graph Theory',
        'Database Principles',
        'Data Structures and Algorithms',
        'Mathematics III',
        'Software Engineering Principles',
        'Introduction to OOP'
    ]
    
    spring_subjects = [
        'Numerical Analysis and Probability',
        'Data Communication',
        'Object Oriented Programming',
        'Software Design and Modelling with UML'
    ]
    
    if subject in fall_subjects:
        return 'Fall Semester'
    elif subject in spring_subjects:
        return 'Spring Semester'
    else:
        return 'Spring Semester'  # Default to Spring (current semester)


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
                filename TEXT,
                last_notified TEXT,
                semester TEXT
            )
            """
        )
        # Add last_notified column if it doesn't exist (migration)
        try:
            conn.execute("ALTER TABLE synced_items ADD COLUMN last_notified TEXT")
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        # Add semester column if it doesn't exist (migration)
        try:
            conn.execute("ALTER TABLE synced_items ADD COLUMN semester TEXT")
        except sqlite3.OperationalError:
            pass  # Column already exists
        
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
    semester = _get_semester_from_subject(subject) if subject else 'Spring Semester'
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO synced_items (id, subject, filename, upload_date, semester) VALUES (?, ?, ?, ?, ?)", 
            (item_id, subject, filename, upload_date, semester)
        )
        conn.commit()


def _is_generic_subject(subject: str) -> bool:
    value = (subject or "").strip().lower()
    return value in GENERIC_SUBJECTS


def _backfill_subject_for_seen_item(item_id: str, subject: str) -> None:
    """Update subject metadata for previously-seen items that were saved as generic/empty."""
    clean_subject = (subject or "").strip()
    if not clean_subject or _is_generic_subject(clean_subject):
        return

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute("SELECT subject FROM synced_items WHERE id = ?", (item_id,))
        row = cur.fetchone()
        if not row:
            return

        existing_subject = (row[0] or "").strip()
        if existing_subject and not _is_generic_subject(existing_subject):
            return

        semester = _get_semester_from_subject(clean_subject)
        conn.execute(
            "UPDATE synced_items SET subject = ?, semester = ? WHERE id = ?",
            (clean_subject, semester, item_id),
        )
        conn.commit()
        logger.info("Backfilled subject for ID %s -> %s", item_id, clean_subject)


def _was_notified(item_id: str) -> bool:
    """
    Check if Telegram notification was already sent for this lecture.
    Prevents duplicate notifications when Render wakes from sleep.
    """
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute("SELECT last_notified FROM synced_items WHERE id = ?", (item_id,))
        result = cur.fetchone()
        was_notified = result is not None and result[0] is not None
        if was_notified:
            logger.debug(f"✓ ID {item_id} already notified at {result[0]}")
        else:
            logger.debug(f"⚠ ID {item_id} not yet notified")
        return was_notified


def _mark_notified(item_id: str) -> None:
    """
    Mark that a Telegram notification was sent for this lecture.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE synced_items SET last_notified = datetime('now') WHERE id = ?",
            (item_id,)
        )
        conn.commit()
        logger.info(f"✅ Marked ID {item_id} as notified")


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


def _fetch_sessions_html(session: requests.Session) -> str:
    """Fetch sessions HTML, trying known endpoint variants to survive portal route changes."""
    auth_status = None
    status_details = []

    for endpoint in SESSIONS_ENDPOINTS:
        logger.info("Fetching class sessions from %s", endpoint)
        response = session.get(endpoint)
        status_details.append(f"{endpoint} -> {response.status_code}")

        if response.status_code == 200:
            logger.info("Using sessions endpoint: %s", endpoint)
            return response.text

        if response.status_code in (401, 403):
            auth_status = response.status_code

    if auth_status is not None:
        raise AuthError(f"Sessions API returned {auth_status}. Session expired or unauthorized.")

    raise RuntimeError(
        "Sessions API returned non-200 statuses across known endpoints: " + "; ".join(status_details)
    )


def fetch_timeline(session: requests.Session) -> List[str]:
    """Fetch list of file IDs from the sessions HTML page (2025-2026 only)"""
    html = _fetch_sessions_html(session)

    # The endpoint returns HTML with download links
    # Filter to only include 2025-2026 academic year
    soup = BeautifulSoup(html, 'html.parser')
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
    html = _fetch_sessions_html(session)
    soup = BeautifulSoup(html, 'html.parser')
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
        
        # Preferred path: each subject appears in a button with data-semester="true" and
        # a corresponding collapse section that contains download links.
        subject_buttons = card.find_all('button', attrs={'data-semester': 'true'})
        seen_file_ids = set()

        for button in subject_buttons:
            subject_tag = button.find('p', class_='float-left font-weight-bold')
            subject_name = subject_tag.get_text(strip=True) if subject_tag else button.get_text(" ", strip=True)
            if not subject_name:
                continue

            if subject_name in ['Fall Semester', 'Spring Semester', 'Summer Semester']:
                continue

            collapse_id = (button.get('data-target') or '').strip().lstrip('#')
            if not collapse_id:
                continue

            collapse_div = card.find('div', id=collapse_id) or soup.find('div', id=collapse_id)
            if not collapse_div:
                continue

            file_ids = []
            for link in collapse_div.find_all('a', href=True):
                href = link.get('href', '')
                match = re.search(r'DownloadClassSessionFile\?id=([a-f0-9\-]+)', href, flags=re.IGNORECASE)
                if match:
                    file_ids.append(match.group(1))

            unique_file_ids = [fid for fid in file_ids if fid not in seen_file_ids]
            if unique_file_ids:
                subjects_data[subject_name] = unique_file_ids
                seen_file_ids.update(unique_file_ids)
                logger.info("Found %d unique files in subject: %s", len(unique_file_ids), subject_name)

        # Safety fallback: if button/collapse parsing fails, scan links in the year card.
        if not subjects_data:
            logger.warning("Structured subject parsing found no data, using safe fallback")
            all_ids = set()
            for link in card.find_all('a', href=True):
                href = link.get('href', '')
                match = re.search(r'DownloadClassSessionFile\?id=([a-f0-9\-]+)', href, flags=re.IGNORECASE)
                if match:
                    all_ids.add(match.group(1))

            if all_ids:
                subjects_data['General Lectures'] = sorted(all_ids)
                logger.info("Found %d files in fallback mode", len(all_ids))
    
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
            upload_date = datetime.now(pytz.timezone('Asia/Baghdad')).isoformat()

    with open(target, "wb") as file:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                file.write(chunk)

    return target, upload_date


def sync_once(auth_client: AuthClient, send_notifications: bool = True) -> Tuple[int, List[Path], List[str], dict]:
    """
    Sync lectures once.
    
    Args:
        auth_client: Authentication client
        send_notifications: Whether to track items for notifications (False for silent sync)
    
    Returns:
        Tuple of (new_files_count, new_file_paths, new_item_ids_for_notification, subject_map)
        subject_map: Dictionary mapping item_id to subject name for notifications
    """
    _init_db()
    session = auth_client.get_authenticated_session()
    new_files: List[Path] = []
    new_item_ids: List[str] = []  # Track IDs for notification
    subject_map: dict = {}  # Map item_id to subject name

    logger.info("Starting sync cycle...")
    
    # Try to fetch with subjects first
    try:
        subjects_data = fetch_timeline_with_subjects(session)
        # Flatten into list with subject info
        for subject, ids in subjects_data.items():
            for item_id in ids:
                if _seen(item_id):
                    _backfill_subject_for_seen_item(item_id, subject)
                    logger.debug("Skipping already downloaded ID: %s", item_id)
                    continue
                try:
                    logger.info("Downloading material with ID: %s (Subject: %s)", item_id, subject)
                    path, upload_date = download_material(session, item_id)
                    _mark_seen(item_id, subject, path.name, upload_date)
                    new_files.append(path)
                    # Track for notification only if not already notified
                    if send_notifications and not _was_notified(item_id):
                        new_item_ids.append(item_id)
                        subject_map[item_id] = subject  # Store subject for this ID
                    logger.info("Successfully downloaded: %s (Upload date: %s)", path.name, upload_date)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Failed to download id=%s: %s", item_id, exc)
    except Exception as e:
        # Fallback to old method without subjects
        logger.warning("Failed to fetch with subjects, using fallback: %s", e)
        ids = fetch_timeline(session)
        
        if not ids:
            logger.warning("No lecture IDs found in timeline response.")
            return 0, new_files, [], {}

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
                # Track for notification only if not already notified
                if send_notifications and not _was_notified(item_id):
                    new_item_ids.append(item_id)
                    subject_map[item_id] = "بابەتی جیاواز"  # Generic subject in Kurdish
                logger.info("Successfully downloaded: %s (Upload date: %s)", path.name, upload_date)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Failed to download id=%s: %s", item_id, exc)

    logger.info("Sync cycle completed: %d new files downloaded, %d need notification", len(new_files), len(new_item_ids))
    return len(new_files), new_files, new_item_ids, subject_map


def sync_forever(auth_client: AuthClient) -> None:
    import time

    while True:
        try:
            count, files, new_ids, subject_map = sync_once(auth_client)
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
