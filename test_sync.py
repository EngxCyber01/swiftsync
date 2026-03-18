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
count, files, new_ids, subject_map = sync_once(auth_client)
print(f"\n✅ Sync complete! Downloaded {count} files")
print(f"New notifications needed: {len(new_ids)}")
if subject_map:
    print(f"Subjects: {list(set(subject_map.values()))}")
print("Check lectures_storage/ folder")
