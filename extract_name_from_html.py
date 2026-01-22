"""
Extract student name from the actual attendance HTML
Run this for B02052429 to see what we get
"""
from auth import AuthClient, AuthConfig
from bs4 import BeautifulSoup

# Test with B02052429
config = AuthConfig()
config.username = "B02052429"
config.password = "@12345"

client = AuthClient(config)
session = client.login()

# Fetch attendance
url = "https://tempapp-su.awrosoft.com/University/ClassAttendance/GetAbsencesList"
response = session.get(f"{url}?studentId={config.username}")

print(f"Status: {response.status_code}\n")

soup = BeautifulSoup(response.text, 'html.parser')

# Save full HTML for inspection
with open('attendance_full.html', 'w', encoding='utf-8') as f:
    f.write(soup.prettify())

print("✓ Saved full HTML to attendance_full.html\n")

# Look for ALL text that might be a name
print("=== Looking for student name patterns ===\n")

# 1. Check page title
title = soup.find('title')
if title:
    print(f"Title: {title.get_text()}")

# 2. Check all h1, h2, h3 headers
for header in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5']):
    text = header.get_text(strip=True)
    if text and 'B02052429' not in text:
        print(f"Header: {text}")

# 3. Check for any span/div with class containing 'name', 'student', 'user'
for elem in soup.find_all(['span', 'div', 'label', 'p']):
    classes = elem.get('class', [])
    if any(c for c in classes if 'name' in str(c).lower() or 'student' in str(c).lower() or 'user' in str(c).lower()):
        print(f"Found element with class {classes}: {elem.get_text(strip=True)[:100]}")

# 4. Look for JavaScript variables
scripts = soup.find_all('script')
for script in scripts:
    if script.string:
        if 'var student' in script.string.lower() or 'studentName' in script.string or 'userName' in script.string:
            lines = script.string.split('\n')
            for line in lines:
                if 'name' in line.lower() and '=' in line:
                    print(f"JS Variable: {line.strip()[:150]}")

# 5. Check the actual table for student info
table = soup.find('table')
if table:
    print("\n=== Table found ===")
    # Get all text before the table
    for elem in table.find_all_previous(['h1', 'h2', 'h3', 'p', 'div', 'span']):
        text = elem.get_text(strip=True)
        if text and len(text) > 3 and len(text) < 200:
            print(f"Before table: {text}")
            
# 6. Look for Arabic text (might be the name)
import re
arabic_pattern = re.compile(r'[\u0600-\u06FF]+')
all_text = soup.get_text()
arabic_matches = arabic_pattern.findall(all_text)
if arabic_matches:
    print("\n=== Arabic text found (might be name) ===")
    for match in set(arabic_matches[:10]):
        if len(match) > 2:
            print(match)

# 7. Print first 50 visible text elements
print("\n=== First 20 text elements ===")
all_elements = soup.find_all(text=True)
visible_texts = [text.strip() for text in all_elements if text.strip() and text.parent.name not in ['script', 'style']]
for i, text in enumerate(visible_texts[:20]):
    if len(text) > 2 and text != '\n':
        print(f"{i+1}. {text[:100]}")
