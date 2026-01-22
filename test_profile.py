"""Test extracting name from attendance page"""
import requests
from bs4 import BeautifulSoup
from auth import AuthClient, AuthConfig
import re

# Login
config = AuthConfig()
config.username = "B02052324"
config.password = "emadXoshnaw1$"
client = AuthClient(config)
client.login()

# Fetch attendance page (the one that works)
response = requests.get(
    f"https://tempapp-su.awrosoft.com/University/ClassAttendance/GetAbsencesList?studentId=B02052324",
    cookies=dict(client.session.cookies),
    timeout=10
)

print(f"Status: {response.status_code}")

# Save to file
with open('attendance_page.html', 'w', encoding='utf-8') as f:
    f.write(response.text)
print("Saved to attendance_page.html")

# Parse and look for student name/info
soup = BeautifulSoup(response.text, 'html.parser')
text = soup.get_text()

print(f"\nPage text length: {len(text)}")
print(f"\nFirst 1000 chars:")
print(text[:1000])

# Check if there's a name somewhere
if 'Emad' in text:
    print("\n*** Found 'Emad' in page! ***")
    idx = text.find('Emad')
    print(f"Context: ...{text[max(0,idx-100):idx+200]}...")

# Check for any h1, h2, title elements
print("\n=== Headers/Titles ===")
for tag in ['h1', 'h2', 'h3', 'title']:
    for elem in soup.find_all(tag):
        print(f"{tag}: {elem.get_text(strip=True)}")
