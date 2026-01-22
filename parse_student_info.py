"""
Parse the student info from /University/Student/GetCurrentStudentInfo
"""
from auth import AuthClient, AuthConfig
from bs4 import BeautifulSoup

config = AuthConfig()
config.username = "B02052429"
config.password = "@12345"

client = AuthClient(config)
session = client.login()

url = "https://tempapp-su.awrosoft.com/University/Student/GetCurrentStudentInfo"
response = session.get(url)

print(f"Status: {response.status_code}\n")

# Save HTML
with open('student_info_page.html', 'w', encoding='utf-8') as f:
    f.write(response.text)
print("✓ Saved to student_info_page.html\n")

# Parse
soup = BeautifulSoup(response.text, 'html.parser')
print(soup.prettify()[:2000])

# Find table
table = soup.find('table')
if table:
    print("\n" + "="*60)
    print("STUDENT INFORMATION")
    print("="*60 + "\n")
    
    rows = table.find_all('tr')
    student_data = {}
    
    for row in rows:
        cells = row.find_all('td')
        if len(cells) >= 2:
            label = cells[0].get_text(strip=True)
            value = cells[1].get_text(strip=True)
            student_data[label] = value
            print(f"{label}: {value}")
    
    # Extract name components
    print("\n" + "="*60)
    print("EXTRACTED DATA")
    print("="*60)
    
    # Common field names
    name_fields = ['Name', 'Full Name', 'Student Name', 'الاسم', 'اسم الطالب']
    first_name_fields = ['First Name', 'الاسم الأول']
    middle_name_fields = ['Middle Name', 'الاسم الأوسط']
    last_name_fields = ['Last Name', 'الاسم الأخير']
    gender_fields = ['Gender', 'الجنس']
    
    for key in student_data:
        if any(field.lower() in key.lower() for field in name_fields):
            print(f"\n✓ Found Name Field: '{key}' = '{student_data[key]}'")
        if any(field.lower() in key.lower() for field in gender_fields):
            print(f"✓ Found Gender Field: '{key}' = '{student_data[key]}'")
