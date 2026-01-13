"""Debug script to see HTML structure"""
import logging
from auth import AuthClient, AuthConfig
from sync import SESSIONS_ENDPOINT
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

auth_client = AuthClient(AuthConfig())
auth_client.login()
session = auth_client.get_authenticated_session()

response = session.get(SESSIONS_ENDPOINT)
soup = BeautifulSoup(response.text, 'html.parser')

# Look for 2025-2026 section
for year_section in soup.find_all('span', class_='float-left font-weight-bold'):
    year_text = year_section.get_text(strip=True)
    print(f"\n=== Found year section: {year_text} ===")
    if '2025-2026' in year_text:
        card = year_section.find_parent('div', class_='card')
        if card:
            # Find all buttons with data-semester
            buttons = card.find_all('button', attrs={'data-semester': 'true'})
            print(f"Found {len(buttons)} buttons with data-semester='true'")
            
            for i, button in enumerate(buttons[:5]):  # Show first 5
                p_tag = button.find('p', class_='float-left font-weight-bold')
                if p_tag:
                    subject_name = p_tag.get_text(strip=True)
                    collapse_id = button.get('data-target', '').lstrip('#')
                    print(f"  Button {i+1}: {subject_name} -> collapse_id: {collapse_id}")
                    
                    if collapse_id:
                        collapse_div = soup.find('div', id=collapse_id)
                        if collapse_div:
                            links = collapse_div.find_all('a', href=True)
                            download_links = [l for l in links if 'DownloadClassSessionFile' in l['href']]
                            print(f"    Found {len(download_links)} download links")
                        else:
                            print(f"    Collapse div not found!")
