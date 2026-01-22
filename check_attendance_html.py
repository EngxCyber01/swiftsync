"""Check if attendance HTML contains student name"""
import requests
from bs4 import BeautifulSoup
from auth import AuthClient, AuthConfig

# Login
config = AuthConfig()
config.username = "B02052437"
config.password = "Arabicx2345@"
client = AuthClient(config)
client.login()

# Fetch attendance
response = requests.get(
    f"https://tempapp-su.awrosoft.com/University/ClassAttendance/GetAbsencesList?studentId=B02052437",
    cookies=dict(client.session.cookies),
    timeout=15
)

print(f"Status: {response.status_code}")
print(f"\n=== Full HTML (first 2000 chars) ===")
print(response.text[:2000])

# Save to file
with open('attendance_response.html', 'w', encoding='utf-8') as f:
    f.write(response.text)
print("\nSaved to attendance_response.html")

# Check if name is in there
soup = BeautifulSoup(response.text, 'html.parser')
text = soup.get_text()

# Search for common name patterns
import re
# Look for Arabic or English names
names = re.findall(r'\b[A-Z][a-z]+ [A-Z][a-z]+\b', text)
print(f"\n=== Potential names found ===")
for name in names[:10]:
    print(f"  - {name}")

# Check for specific student ID mentions
if 'B02052437' in text:
    idx = text.find('B02052437')
    print(f"\n=== Context around student ID ===")
    print(text[max(0, idx-100):idx+100])
