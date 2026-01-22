"""
Test script to see what the attendance HTML contains
"""
import sys
from auth import AuthClient, AuthConfig
import requests

# Login first
config = AuthConfig()
config.username = "B02052429"
config.password = "@12345"

try:
    client = AuthClient(config)
    session = client.login()
    
    print("✓ Login successful!")
    print(f"Cookies: {len(session.cookies)}")
    
    # Fetch attendance page
    attendance_url = "https://tempapp-su.awrosoft.com/University/ClassAttendance/GetAbsencesList"
    student_id = config.username
    
    response = session.get(f"{attendance_url}?studentId={student_id}")
    
    print(f"\nAttendance page status: {response.status_code}")
    
    # Save to file
    with open("attendance_html.html", "w", encoding="utf-8") as f:
        f.write(response.text)
    
    print("✓ HTML saved to attendance_html.html")
    
    # Try to fetch home page
    home_response = session.get("https://tempapp-su.awrosoft.com/Home/")
    print(f"\nHome page status: {home_response.status_code}")
    
    with open("home_page.html", "w", encoding="utf-8") as f:
        f.write(home_response.text)
    
    print("✓ Home page saved to home_page.html")
    
    # Try to extract student name patterns
    print("\n=== Searching for name patterns in attendance HTML ===")
    html_lower = response.text.lower()
    
    patterns = [
        'student name', 'student:', 'name:', 'full name',
        'الطالب:', 'اسم الطالب:', 'اسم',
        'b02052429'
    ]
    
    for pattern in patterns:
        if pattern in html_lower:
            # Find context around the pattern
            idx = html_lower.find(pattern)
            context = response.text[max(0, idx-100):min(len(response.text), idx+200)]
            print(f"\nFound '{pattern}':")
            print(f"Context: {context}")
    
    print("\n=== Checking home page for profile info ===")
    home_lower = home_response.text.lower()
    
    for pattern in patterns:
        if pattern in home_lower:
            idx = home_lower.find(pattern)
            context = home_response.text[max(0, idx-100):min(len(home_response.text), idx+200)]
            print(f"\nFound '{pattern}' in home:")
            print(f"Context: {context}")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
