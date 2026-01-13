"""Test the actual API response structure"""
import json
from auth import AuthClient, AuthConfig

# Login
config = AuthConfig()
client = AuthClient(config)
session = client.login()

print("✅ Authenticated successfully!\n")

# Test the sessions endpoint
endpoint = "https://tempapp-su.awrosoft.com/University/ClassSession/GetStudentClassSessionsList"
print(f"Testing: {endpoint}\n")

response = session.get(endpoint)
print(f"Status: {response.status_code}")
print(f"Content-Type: {response.headers.get('Content-Type')}")
print(f"\nResponse preview (first 2000 chars):")
print("="*60)
print(response.text[:2000])
print("="*60)

# Check if it's HTML with downloadable links
if 'href=' in response.text and 'DownloadClassSessionFile' in response.text:
    print("\n✅ Found download links in HTML!")
    import re
    # Extract all download links
    download_pattern = r'href="([^"]*DownloadClassSessionFile[^"]*)"'
    links = re.findall(download_pattern, response.text)
    print(f"\nFound {len(links)} download links:")
    for i, link in enumerate(links[:5], 1):
        print(f"  {i}. {link}")
    if len(links) > 5:
        print(f"  ... and {len(links) - 5} more")
