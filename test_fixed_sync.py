"""
Quick test of the fixed sync logic
"""
import logging
from auth import AuthClient, AuthConfig
from sync import sync_once

logging.basicConfig(level=logging.INFO)

print("Testing sync with fixed logic...\n")
auth = AuthClient(AuthConfig())
count, files = sync_once(auth)

print(f"\nSync result: {count} new files")
if files:
    print(f"   First 5 files: {[f.name for f in files[:5]]}")
