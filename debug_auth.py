"""
Debug tool to test authentication and API responses
"""
import json
import logging
from pathlib import Path

from dotenv import load_dotenv
from auth import AuthClient, AuthConfig, AuthError

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

def test_authentication():
    """Test if authentication works"""
    print("\n" + "="*60)
    print("🔐 Testing Authentication...")
    print("="*60 + "\n")
    
    try:
        config = AuthConfig()
        print(f"📧 Username: {config.username}")
        print(f"🔑 Password: {'*' * len(config.password)}")
        print(f"🔗 Login URL: {config.login_url}")
        print(f"🔗 Callback URL: {config.oidc_callback_url}\n")
        
        client = AuthClient(config)
        print("🔄 Attempting login...")
        session = client.login()
        
        print("✅ Authentication successful!")
        print(f"🍪 Cookies: {len(session.cookies)} cookies received")
        for cookie in session.cookies:
            print(f"   - {cookie.name}: {cookie.value[:20]}...")
        
        return session
        
    except AuthError as e:
        print(f"\n❌ Authentication failed: {e}")
        print("\n💡 Troubleshooting:")
        print("   1. Check your credentials in .env file")
        print("   2. Make sure you can login manually at:")
        print(f"      {config.login_url}")
        print("   3. Check if the portal is accessible")
        return None
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_timeline_api(session):
    """Test timeline API"""
    print("\n" + "="*60)
    print("📚 Testing Class Sessions API...")
    print("="*60 + "\n")
    
    if not session:
        print("⚠️  Skipping (no valid session)")
        return
    
    try:
        import os
        base_url = os.getenv("APP_BASE_URL", "https://tempapp-su.awrosoft.com")
        endpoint = f"{base_url}/University/ClassSession/GetStudentClassSessionsList"
        
        print(f"🔗 Endpoint: {endpoint}")
        print("📤 Sending GET request...")
        
        response = session.get(endpoint)
        
        print(f"📥 Response Status: {response.status_code}")
        
        if response.status_code == 200:
            try:
                data = response.json()
                print("\n✅ Sessions API returned JSON")
                print(f"📊 Response structure:")
                print(json.dumps(data, indent=2, ensure_ascii=False)[:2000])
                
                # Try to extract file IDs
                from sync import fetch_timeline
                ids = fetch_timeline(session)
                print(f"\n📝 Extracted {len(ids)} file IDs:")
                for i, file_id in enumerate(ids[:10], 1):
                    print(f"   {i}. ID: {file_id}")
                if len(ids) > 10:
                    print(f"   ... and {len(ids) - 10} more")
                
                if len(ids) == 0:
                    print("\n⚠️  NO FILE IDs FOUND!")
                    print("📋 This might mean:")
                    print("   - No lectures uploaded yet")
                    print("   - Different API structure than expected")
                    print("   - Need to check another endpoint")
                    
            except json.JSONDecodeError:
                print(f"❌ Response is not JSON: {response.text[:500]}")
        else:
            print(f"❌ API returned error {response.status_code}")
            print(f"Response: {response.text[:500]}")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


def main():
    print("\n🔍 LECTURE SYNC SYSTEM - DIAGNOSTIC TOOL")
    print("This tool will help diagnose why lectures aren't showing\n")
    
    # Test 1: Authentication
    session = test_authentication()
    
    # Test 2: Timeline API
    if session:
        test_timeline_api(session)
    
    print("\n" + "="*60)
    print("✅ Diagnostic complete!")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
