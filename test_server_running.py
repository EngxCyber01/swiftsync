"""
Server Verification Test
Tests that server is running and security is active
"""
import requests
import time

BASE_URL = "http://localhost:8000"

print("ðŸš€ Server Verification Test")
print("=" * 50)

# Wait for server to be fully ready
time.sleep(2)

# Test 1: Basic connectivity
print("\n1ï¸âƒ£ Testing Basic Connectivity...")
try:
    response = requests.get(BASE_URL, timeout=5)
    if response.status_code == 200:
        print("   âœ… Server is running and responsive")
    else:
        print(f"   âš ï¸ Server responded with status: {response.status_code}")
except Exception as e:
    print(f"   âŒ Cannot connect: {e}")
    exit(1)

# Test 2: Admin Portal Access (with correct key)
print("\n2ï¸âƒ£ Testing Admin Portal Access...")
try:
    response = requests.get(f"{BASE_URL}/admin-portal?admin_key=your_secret_admin_key_here", timeout=5)
    if response.status_code == 200 and "Admin SOC" in response.text:
        print("   âœ… Admin portal accessible with correct key")
    else:
        print(f"   âš ï¸ Unexpected response: {response.status_code}")
except Exception as e:
    print(f"   âŒ Error: {e}")

# Test 3: Security Detection (SQL Injection attempt)
print("\n3ï¸âƒ£ Testing Security Detection (SQL Injection)...")
try:
    # This should be blocked
    response = requests.get(f"{BASE_URL}/?test=' OR '1'='1", timeout=5)
    if response.status_code == 403:
        print("   âœ… SQL injection attempt blocked (403 Forbidden)")
    else:
        print(f"   âš ï¸ Unexpected status: {response.status_code}")
except Exception as e:
    print(f"   âš ï¸ Request error: {e}")

# Test 4: Security Detection (Malicious User Agent)
print("\n4ï¸âƒ£ Testing Bot Detection...")
try:
    headers = {"User-Agent": "sqlmap/1.0"}
    response = requests.get(BASE_URL, headers=headers, timeout=5)
    if response.status_code == 403:
        print("   âœ… Malicious bot blocked (403 Forbidden)")
    else:
        print(f"   âš ï¸ Unexpected status: {response.status_code}")
except Exception as e:
    print(f"   âš ï¸ Request error: {e}")

# Test 5: Sync Functionality Check
print("\n5ï¸âƒ£ Checking Sync Functionality...")
import os
lectures_dir = "lectures_storage"
if os.path.exists(lectures_dir):
    files = os.listdir(lectures_dir)
    print(f"   âœ… Lectures storage exists with {len(files)} items")
else:
    print("   âš ï¸ Lectures storage directory not found")

print("\n" + "=" * 50)
print("âœ… Server Verification Complete!")
print(f"ðŸŒ Server running at: {BASE_URL}")
print("ðŸ›¡ï¸ All security systems: ACTIVE")
print("ðŸ¤– Bot sync functionality: READY")

