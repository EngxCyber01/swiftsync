"""Test auth on Render with detailed logging"""
import os
import sys
from auth import AuthClient, AuthConfig

def test_auth():
    print("=" * 60)
    print("  Testing Authentication")
    print("=" * 60)
    
    # Check env vars
    username = os.getenv("PORTAL_USERNAME", "")
    password = os.getenv("PORTAL_PASSWORD", "")
    
    print(f"\n📋 Configuration:")
    print(f"   Username: {'✅ SET' if username else '❌ NOT SET'}")
    print(f"   Password: {'✅ SET' if password else '❌ NOT SET'}")
    
    if not username or not password:
        print("\n❌ Missing credentials in environment variables!")
        print("   Add PORTAL_USERNAME and PORTAL_PASSWORD to Render environment.")
        sys.exit(1)
    
    print(f"\n🔐 Attempting login...")
    print(f"   Username: {username[:3]}***")
    
    try:
        config = AuthConfig()
        client = AuthClient(config)
        client.login()
        
        print("✅ Login successful!")
        print(f"   Session active: {client.session is not None}")
        return True
        
    except Exception as e:
        print(f"❌ Login failed: {e}")
        print(f"\n📝 Error details:")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_auth()
    sys.exit(0 if success else 1)
