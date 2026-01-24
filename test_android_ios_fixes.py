"""
Quick Test Script for Android & iOS Fixes
Run this to verify cookie settings and PDF headers

Usage: python test_android_ios_fixes.py
"""

import requests
import json
from typing import Dict, Any

# ⚠️ UPDATE THIS URL TO YOUR DEPLOYMENT
BASE_URL = "https://swiftsync-013r.onrender.com"  # Change to your actual URL
# BASE_URL = "http://localhost:8000"  # For local testing

def print_section(title: str):
    """Print formatted section header"""
    print("\n" + "="*60)
    print(f"  {title}")
    print("="*60)

def test_login_cookie_set():
    """Test 1: Verify login sets HTTP cookie"""
    print_section("TEST 1: Android Login Cookie")
    
    # Note: You need real credentials for this test
    print("⚠️  This test requires valid credentials")
    print("📝 Enter test credentials (or skip by pressing Enter):\n")
    
    username = input("Username: ").strip()
    if not username:
        print("⏭️  Skipped (no credentials provided)")
        return None
    
    password = input("Password: ").strip()
    
    try:
        print(f"\n🔄 Logging in as: {username}")
        response = requests.post(
            f"{BASE_URL}/api/attendance/login",
            params={"username": username, "password": password},
            allow_redirects=False
        )
        
        print(f"\n📊 Response Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Login successful!")
            print(f"   Student ID: {data.get('student_id', 'N/A')}")
            print(f"   Username: {data.get('username', 'N/A')}")
            
            # Check for Set-Cookie header
            if 'set-cookie' in response.headers:
                print(f"\n🍪 COOKIE SET (ANDROID FIX WORKING):")
                cookie_header = response.headers['set-cookie']
                print(f"   {cookie_header}")
                
                # Parse cookie attributes
                if 'SameSite=Lax' in cookie_header or 'SameSite=lax' in cookie_header:
                    print("   ✅ SameSite=Lax (Android-safe)")
                else:
                    print("   ⚠️  SameSite NOT set to Lax")
                
                if 'Max-Age' in cookie_header or 'max-age' in cookie_header:
                    print("   ✅ Max-Age set (cookie persists)")
                else:
                    print("   ⚠️  Max-Age not set")
                
                if 'HttpOnly' not in cookie_header:
                    print("   ✅ HttpOnly=False (JS can access)")
                else:
                    print("   ℹ️  HttpOnly=True (backend-only)")
                    
                return data.get('session_token')
            else:
                print("❌ NO COOKIE SET - Android fix NOT working!")
                print("   Response headers:")
                for key, value in response.headers.items():
                    print(f"   {key}: {value}")
                return None
        else:
            print(f"❌ Login failed: {response.status_code}")
            print(f"   Response: {response.text}")
            return None
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

def test_cookie_fallback(session_token: str = None):
    """Test 2: Verify cookie fallback works"""
    print_section("TEST 2: Android Cookie Fallback")
    
    if not session_token:
        print("⏭️  Skipped (no session token from previous test)")
        return
    
    try:
        print("🔄 Testing cookie-based authentication...")
        
        # Create a session with cookie
        session = requests.Session()
        session.cookies.set('session_token', session_token, domain=BASE_URL.replace('https://', '').replace('http://', ''))
        
        # Try to access attendance WITHOUT query parameter
        response = session.get(f"{BASE_URL}/api/attendance/data")
        
        print(f"\n📊 Response Status: {response.status_code}")
        
        if response.status_code == 200:
            print("✅ Cookie fallback working! Android users can use cookies")
        elif response.status_code == 401:
            data = response.json()
            print(f"❌ Cookie fallback NOT working: {data.get('error', 'Unknown error')}")
        else:
            print(f"⚠️  Unexpected status: {response.text}")
            
    except Exception as e:
        print(f"❌ Error: {e}")

def test_ios_pdf_headers():
    """Test 3: Verify iOS Safari PDF headers"""
    print_section("TEST 3: iOS Safari PDF Download")
    
    try:
        # List available files
        print("🔄 Fetching available files...")
        files_response = requests.get(f"{BASE_URL}/api/files")
        
        if files_response.status_code != 200:
            print(f"❌ Cannot fetch files: {files_response.status_code}")
            return
        
        files_data = files_response.json()
        
        # Find first PDF
        test_file = None
        for subject, files in files_data.items():
            if files:
                test_file = files[0]['name']
                break
        
        if not test_file:
            print("⚠️  No PDF files found in lectures_storage")
            print("   Please add a test PDF to test iOS download fix")
            return
        
        print(f"📄 Testing with file: {test_file}")
        
        # Test with iOS Safari User-Agent
        ios_headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1'
        }
        
        print(f"\n🔄 Requesting with iOS Safari User-Agent...")
        response = requests.head(
            f"{BASE_URL}/api/download/{test_file}",
            headers=ios_headers,
            allow_redirects=False
        )
        
        print(f"\n📊 Response Headers:")
        print(f"   Status: {response.status_code}")
        
        # Check critical headers
        content_type = response.headers.get('content-type', '')
        content_disposition = response.headers.get('content-disposition', '')
        x_content_type = response.headers.get('x-content-type-options', '')
        
        print(f"   Content-Type: {content_type}")
        print(f"   Content-Disposition: {content_disposition}")
        print(f"   X-Content-Type-Options: {x_content_type}")
        
        # Validate iOS fix
        if test_file.lower().endswith('.pdf'):
            if 'application/octet-stream' in content_type:
                print("\n✅ iOS PDF FIX WORKING!")
                print("   Content-Type changed to octet-stream for iOS")
            elif 'application/pdf' in content_type:
                print("\n❌ iOS fix NOT working!")
                print("   Still sending application/pdf (iOS will preview)")
            else:
                print(f"\n⚠️  Unexpected Content-Type: {content_type}")
        
        if 'attachment' in content_disposition:
            print("✅ Content-Disposition set to attachment")
        else:
            print("⚠️  Content-Disposition missing or not set to attachment")
        
        if 'nosniff' in x_content_type:
            print("✅ X-Content-Type-Options: nosniff (prevents MIME detection)")
        else:
            print("⚠️  X-Content-Type-Options not set")
        
        # Test with regular desktop browser
        print(f"\n🔄 Testing with Desktop Chrome User-Agent...")
        desktop_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        
        response2 = requests.head(
            f"{BASE_URL}/api/download/{test_file}",
            headers=desktop_headers,
            allow_redirects=False
        )
        
        content_type2 = response2.headers.get('content-type', '')
        print(f"   Content-Type: {content_type2}")
        
        if 'application/pdf' in content_type2:
            print("✅ Desktop browsers still get application/pdf (normal behavior)")
        else:
            print("⚠️  Desktop browsers getting octet-stream (not ideal but works)")
            
    except Exception as e:
        print(f"❌ Error: {e}")

def main():
    """Run all tests"""
    print("\n" + "🔧 ANDROID & iOS FIXES - TEST SUITE")
    print("="*60)
    print(f"Testing URL: {BASE_URL}")
    print("="*60)
    
    # Test 1: Login cookie
    session_token = test_login_cookie_set()
    
    # Test 2: Cookie fallback
    if session_token:
        test_cookie_fallback(session_token)
    
    # Test 3: iOS PDF headers
    test_ios_pdf_headers()
    
    # Summary
    print_section("TEST SUMMARY")
    print("✅ = Working correctly")
    print("⚠️  = Needs attention")
    print("❌ = Not working")
    print("\nIf you see ❌ errors, check:")
    print("1. Server is running and accessible")
    print("2. BASE_URL is correct")
    print("3. Code changes were deployed")
    print("4. Server was restarted after changes")
    print("\n")

if __name__ == "__main__":
    main()
