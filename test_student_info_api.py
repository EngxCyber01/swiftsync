"""
Test GetCurrentStudentInfo endpoint with proper authentication
"""
from auth import AuthClient, AuthConfig
import json

# Test with B02052429
config = AuthConfig()
config.username = "B02052429"
config.password = "@12345"

client = AuthClient(config)
session = client.login()

print("✓ Logged in successfully\n")

# Try different endpoint URLs
endpoints = [
    "https://tempapp-su.awrosoft.com/Portal/GetCurrentStudentInfo",
    "https://tempapp-su.awrosoft.com/Api/Portal/GetCurrentStudentInfo",
    "https://tempapp-su.awrosoft.com/api/Portal/GetCurrentStudentInfo",
    "https://tempapp-su.awrosoft.com/GetCurrentStudentInfo",
    "https://tempapp-su.awrosoft.com/Portal/GetCurrentStudentTimeLine",
    "https://tempapp-su.awrosoft.com/Home/GetCurrentStudentInfo",
]

for endpoint in endpoints:
    print(f"\n{'='*60}")
    print(f"Testing: {endpoint}")
    print('='*60)
    
    try:
        response = session.get(endpoint, timeout=10)
        print(f"Status: {response.status_code}")
        print(f"Content-Type: {response.headers.get('Content-Type', 'N/A')}")
        
        if response.status_code == 200:
            print(f"\n✓ SUCCESS! Response:")
            try:
                data = response.json()
                print(json.dumps(data, indent=2, ensure_ascii=False))
                
                # Save to file
                with open(f'student_info_response.json', 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                print(f"\n✓ Saved to student_info_response.json")
            except:
                print(response.text[:500])
        else:
            print(f"Error: {response.status_code}")
            if response.text:
                print(f"Response: {response.text[:200]}")
    
    except Exception as e:
        print(f"Exception: {e}")

print("\n" + "="*60)
print("TESTING COMPLETE")
print("="*60)
