"""
Test all possible variations of the student info endpoint
"""
from auth import AuthClient, AuthConfig
import json

config = AuthConfig()
config.username = "B02052429"
config.password = "@12345"

client = AuthClient(config)
session = client.login()

print("✓ Logged in\n")

# Try every possible pattern
patterns = [
    "/University/GetCurrentStudentInfo",
    "/University/Portal/GetCurrentStudentInfo",
    "/University/Student/GetCurrentStudentInfo",
    "/University/Student/GetInfo",
    "/University/Student/Info",
    "/Student/GetCurrentInfo",
    "/Student/Info",
    "/Student/Profile",
    "/University/GetStudentInfo",
    "/University/StudentInfo",
]

base_url = "https://tempapp-su.awrosoft.com"

for pattern in patterns:
    url = base_url + pattern
    print(f"Trying: {pattern}")
    
    try:
        response = session.get(url, timeout=5)
        if response.status_code == 200:
            print(f"  ✓ SUCCESS! Status: {response.status_code}")
            try:
                data = response.json()
                print(f"  Data: {json.dumps(data, indent=2, ensure_ascii=False)[:300]}")
                
                with open('student_info_SUCCESS.json', 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                print("\n  ✓✓✓ SAVED TO student_info_SUCCESS.json ✓✓✓\n")
                break
            except:
                print(f"  Response (not JSON): {response.text[:200]}")
        elif response.status_code != 404:
            print(f"  Status: {response.status_code}")
    except Exception as e:
        print(f"  Error: {str(e)[:50]}")

print("\nDone")
