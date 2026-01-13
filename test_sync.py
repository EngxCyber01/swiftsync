"""Test complete sync cycle"""
import logging
from sync import sync_once
from auth import AuthClient, AuthConfig

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)

print("🔄 Starting sync cycle...\n")
auth_client = AuthClient(AuthConfig())
sync_once(auth_client)
print("\n✅ Sync complete! Check lectures_storage/ folder")
