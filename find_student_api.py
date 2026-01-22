"""
Fetch the home page and search for GetCurrentStudentInfo to find the real API endpoint
"""
from auth import AuthClient, AuthConfig
from bs4 import BeautifulSoup
import re

config = AuthConfig()
config.username = "B02052429"  
config.password = "@12345"

client = AuthClient(config)
session = client.login()

# Fetch home page
response = session.get("https://tempapp-su.awrosoft.com/Home/", timeout=15)
print(f"Home page status: {response.status_code}\n")

soup = BeautifulSoup(response.text, 'html.parser')

# Save full HTML
with open('home_page.html', 'w', encoding='utf-8') as f:
    f.write(response.text)
print("✓ Saved to home_page.html\n")

# Look for GetCurrentStudentInfo in scripts
print("="*60)
print("Searching for GetCurrentStudentInfo in JavaScript...")
print("="*60)

scripts = soup.find_all('script')
found = False

for script in scripts:
    if script.string:
        if 'GetCurrentStudentInfo' in script.string or 'getCurrentStudentInfo' in script.string.lower():
            print("\n✓ FOUND in script!")
            # Find the relevant lines
            lines = script.string.split('\n')
            for i, line in enumerate(lines):
                if 'getcurrentstudentinfo' in line.lower():
                    # Print context
                    start = max(0, i-3)
                    end = min(len(lines), i+4)
                    print(f"\nLines {start}-{end}:")
                    for j in range(start, end):
                        marker = ">>> " if j == i else "    "
                        print(f"{marker}{lines[j]}")
            found = True

# Look for API endpoints in general
print("\n" + "="*60)
print("Searching for API endpoints...")
print("="*60)

for script in scripts:
    if script.string:
        # Find URLs that look like API endpoints
        urls = re.findall(r'["\']/(api|Api|API)/[^"\']+["\']', script.string)
        if urls:
            print("\nFound API URLs:")
            for url in set(urls):
                print(f"  {url}")

# Look for student name in the HTML itself
print("\n" + "="*60)
print("Searching for student name in HTML...")
print("="*60)

# Check for divs/spans with class containing 'student', 'user', 'profile', 'name'
for elem in soup.find_all(['div', 'span', 'li', 'a']):
    classes = ' '.join(elem.get('class', []))
    if any(keyword in classes.lower() for keyword in ['student', 'user', 'profile', 'name']):
        text = elem.get_text(strip=True)
        if text and len(text) > 2 and len(text) < 100:
            print(f"Class '{classes}': {text}")

# Look for data attributes
print("\n" + "="*60)
print("Searching for data attributes...")
print("="*60)

for elem in soup.find_all(attrs={'data-student': True}):
    print(f"Found data-student: {elem.get('data-student')}")
    
for elem in soup.find_all(attrs={'data-name': True}):
    print(f"Found data-name: {elem.get('data-name')}")

print("\nDone!")
