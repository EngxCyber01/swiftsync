"""
Quick verification test for SwiftSync Kurdish SOC System
Tests all critical endpoints before deployment
"""
import requests
import sys

BASE_URL = "http://localhost:8000"
ADMIN_KEY = "emadCyberSoft4SOC"

def test_endpoint(name, url, expected_status=200):
    """Test a single endpoint"""
    try:
        response = requests.get(url, timeout=5)
        status = "✅" if response.status_code == expected_status else "❌"
        print(f"{status} {name}: {response.status_code}")
        return response.status_code == expected_status
    except Exception as e:
        print(f"❌ {name}: ERROR - {e}")
        return False

print("🔍 Testing SwiftSync Kurdish SOC System...\n")

tests = [
    ("Public Portal", f"{BASE_URL}/"),
    ("Files API", f"{BASE_URL}/api/files"),
    ("Service Worker", f"{BASE_URL}/service-worker.js"),
    ("PWA Manifest", f"{BASE_URL}/manifest.json"),
    ("Admin SOC Portal", f"{BASE_URL}/admin-portal?admin_key={ADMIN_KEY}"),
]

print("📋 Running Tests:\n")
results = []
for name, url in tests:
    results.append(test_endpoint(name, url))

print("\n" + "="*50)
passed = sum(results)
total = len(results)
print(f"\n✅ Passed: {passed}/{total}")

if passed == total:
    print("\n🎉 ALL TESTS PASSED! System is ready for deployment!")
    print("\n🌐 Local URLs:")
    print(f"   Public: {BASE_URL}/")
    print(f"   Admin:  {BASE_URL}/admin-portal?admin_key={ADMIN_KEY}")
    print("\n🚀 Next Step: Deploy to Render.com (see DEPLOY_NOW.md)")
    sys.exit(0)
else:
    print(f"\n❌ {total - passed} test(s) failed. Check the errors above.")
    sys.exit(1)
