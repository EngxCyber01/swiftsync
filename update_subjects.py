"""Script to update database with subject information for existing files"""
import logging
import re
import sqlite3
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from auth import AuthClient, AuthConfig
from sync import DB_PATH, SESSIONS_ENDPOINT

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def fetch_filename_to_subject_map(session: requests.Session) -> dict:
    """Fetch all files with their subjects from portal"""
    logger.info("Fetching class sessions from portal...")
    
    response = session.get(SESSIONS_ENDPOINT)
    if response.status_code != 200:
        raise RuntimeError(f"Failed to fetch sessions: {response.status_code}")
    
    soup = BeautifulSoup(response.text, 'html.parser')
    filename_to_subject = {}
    
    # Find 2025-2026 year section
    for year_section in soup.find_all('span', class_='float-left font-weight-bold'):
        year_text = year_section.get_text(strip=True)
        if '2025-2026' in year_text:
            logger.info("Found 2025-2026 section")
            card = year_section.find_parent('div', class_='card')
            if card:
                # Find all collapse divs within this card
                all_collapses = card.find_all('div', id=re.compile(r'classCollapse_'))
                logger.info(f"Found {len(all_collapses)} class collapse divs")
                
                for collapse in all_collapses:
                    collapse_id = collapse.get('id')
                    # Find the button that controls this collapse
                    button = card.find('button', attrs={'data-target': f'#{collapse_id}'})
                    if button:
                        # Get subject name from button
                        subject_name = button.get_text(strip=True)
                        
                        # Skip semester headers
                        if 'Semester' in subject_name:
                            logger.info(f"Skipping semester: {subject_name}")
                            continue
                        
                        logger.info(f"Processing subject: {subject_name}")
                        
                        # Find all download links within this collapse div
                        for link in collapse.find_all('a', href=re.compile(r'DownloadClassSessionFile\?id=')):
                            file_id = link['href'].split('id=')[1]
                            # Get the display name from the adjacent p.name element
                            name_elem = link.find_previous('p', class_='name')
                            display_name = name_elem.get_text(strip=True) if name_elem else 'Unknown'
                            
                            filename_to_subject[file_id] = {
                                'subject': subject_name,
                                'display_name': display_name
                            }
                            logger.info("  Mapped %s -> %s", display_name, subject_name)
    
    return filename_to_subject


def update_database_subjects():
    """Update existing database entries with subject information"""
    # Authenticate
    auth_client = AuthClient(AuthConfig())
    auth_client.login()
    session = auth_client.get_authenticated_session()
    
    # Fetch file-to-subject mapping
    file_map = fetch_filename_to_subject_map(session)
    logger.info("Found %d files with subject mappings", len(file_map))
    
    # Update database
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get all existing entries
    cursor.execute("SELECT id FROM synced_items")
    rows = cursor.fetchall()
    
    updated = 0
    for (file_id,) in rows:
        if file_id in file_map:
            subject = file_map[file_id]['subject']
            display_name = file_map[file_id]['display_name']
            cursor.execute(
                "UPDATE synced_items SET subject = ?, filename = ? WHERE id = ?",
                (subject, display_name, file_id)
            )
            updated += 1
            logger.info("Updated %s -> %s", display_name, subject)
    
    conn.commit()
    conn.close()
    
    logger.info("Updated %d entries with subject information", updated)


if __name__ == "__main__":
    update_database_subjects()
