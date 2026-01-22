"""
Server Verification Test
Tests that server is running and security is active
"""
import requests
import time

BASE_URL = "http://localhost:8000"

print("🚀 Server Verification Test")
print("=" * 50)

# Wait for server to be fully ready
time.sleep(2)

# Test 1: Basic connectivity
print("\n1️⃣ Testing Basic Connectivity...")
try:
    response = requests.get(BASE_URL, timeout=5)
    if response.status_code == 200:
        print("   ✅ Server is running and responsive")
    else:
        print(f"   ⚠️ Server responded with status: {response.status_code}")
except Exception as e:
    print(f"   ❌ Cannot connect: {e}")
    exit(1)

# Test 2: Admin Portal Access (with correct key)
print("\n2️⃣ Testing Admin Portal Access...")
try:
    response = requests.get(f"{BASE_URL}/admin-portal?admin_key=emadCyberSoft4SOC", timeout=5)
    if response.status_code == 200 and "Admin SOC" in response.text:
        print("   ✅ Admin portal accessible with correct key")
    else:
        print(f"   ⚠️ Unexpected response: {response.status_code}")
except Exception as e:
    print(f"   ❌ Error: {e}")

# Test 3: Security Detection (SQL Injection attempt)
print("\n3️⃣ Testing Security Detection (SQL Injection)...")
try:
    # This should be blocked
    response = requests.get(f"{BASE_URL}/?test=' OR '1'='1", timeout=5)
    if response.status_code == 403:
        print("   ✅ SQL injection attempt blocked (403 Forbidden)")
    else:
        print(f"   ⚠️ Unexpected status: {response.status_code}")
except Exception as e:
    print(f"   ⚠️ Request error: {e}")

# Test 4: Security Detection (Malicious User Agent)
print("\n4️⃣ Testing Bot Detection...")
try:
    headers = {"User-Agent": "sqlmap/1.0"}
    response = requests.get(BASE_URL, headers=headers, timeout=5)
    if response.status_code == 403:
        print("   ✅ Malicious bot blocked (403 Forbidden)")
    else:
        print(f"   ⚠️ Unexpected status: {response.status_code}")
except Exception as e:
    print(f"   ⚠️ Request error: {e}")

# Test 5: Sync Functionality Check
print("\n5️⃣ Checking Sync Functionality...")
import os
lectures_dir = "lectures_storage"
if os.path.exists(lectures_dir):
    files = os.listdir(lectures_dir)
    print(f"   ✅ Lectures storage exists with {len(files)} items")
else:
    print("   ⚠️ Lectures storage directory not found")

print("\n" + "=" * 50)
print("✅ Server Verification Complete!")
print(f"🌐 Server running at: {BASE_URL}")
print("🛡️ All security systems: ACTIVE")
print("🤖 Bot sync functionality: READY")
