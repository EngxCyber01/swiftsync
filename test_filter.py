"""Test 2025-2026 filter"""
import logging
from auth import AuthClient, AuthConfig
from sync import fetch_timeline

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

try:
    print("🔐 Authenticating...")
    client = AuthClient(AuthConfig())
    session = client.login()
    print("✅ Authenticated\n")
    
    print("📚 Fetching 2025-2026 lectures...")
    file_ids = fetch_timeline(session)
    print(f"\n✅ Found {len(file_ids)} files from 2025-2026")
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
