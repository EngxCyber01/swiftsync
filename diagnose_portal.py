"""
Diagnostic script to check what the portal is actually returning
"""
import logging
from auth import AuthClient, AuthConfig
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

APP_BASE_URL = os.getenv("APP_BASE_URL", "https://tempapp-su.awrosoft.com")
SESSIONS_ENDPOINT = f"{APP_BASE_URL}/University/ClassSession/GetStudentClassSessionsList"

def diagnose():
    print("🔍 Diagnosing portal response...\n")
    
    # Authenticate
    print("1️⃣ Authenticating...")
    auth = AuthClient(AuthConfig())
    session = auth.get_authenticated_session()
    print("✅ Authentication successful!\n")
    
    # Fetch the page
    print("2️⃣ Fetching sessions page...")
    response = session.get(SESSIONS_ENDPOINT)
    print(f"   Status: {response.status_code}")
    print(f"   Content length: {len(response.text)} characters\n")
    
    # Save to file for inspection
    output_file = "portal_response.html"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(response.text)
    print(f"3️⃣ Saved response to: {output_file}")
    print("   Open this file to see what the portal returned\n")
    
    # Check for key patterns
    print("4️⃣ Checking for expected patterns:")
    checks = [
        ("Year 2025-2026", "2025-2026" in response.text),
        ("Download links", "DownloadClassSessionFile" in response.text),
        ("Class 'float-left'", "float-left" in response.text),
        ("Class 'text-primary'", "text-primary" in response.text),
        ("Card elements", "card" in response.text),
    ]
    
    for name, found in checks:
        status = "✅" if found else "❌"
        print(f"   {status} {name}")
    
    # Count potential download links
    import re
    download_pattern = r'DownloadClassSessionFile\?id=([a-f0-9\-]+)'
    matches = re.findall(download_pattern, response.text)
    print(f"\n5️⃣ Found {len(matches)} potential download links")
    if matches:
        print(f"   First 3 IDs: {matches[:3]}")
    
    print("\n" + "="*60)
    print("📋 DIAGNOSIS COMPLETE")
    print("="*60)
    if len(matches) == 0:
        print("⚠️  NO DOWNLOAD LINKS FOUND!")
        print("   This means either:")
        print("   1. The portal HTML structure changed")
        print("   2. You have no lectures in 2025-2026")
        print("   3. The account doesn't have access to lectures")
        print(f"\n   Check {output_file} to see the actual HTML")
    else:
        print(f"✅ Found {len(matches)} download links")
        print("   The issue might be with the year/subject filtering logic")

if __name__ == "__main__":
    try:
        diagnose()
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
