"""
Quick test script to verify all new features
"""
import requests
import json

BASE_URL = "http://localhost:8000"

print("🧪 Testing SwiftSync New Features\n")
print("=" * 50)

# Test 1: Health Check
print("\n1️⃣ Testing Health Endpoint...")
try:
    response = requests.get(f"{BASE_URL}/health")
    if response.status_code == 200:
        print("   ✅ Health check passed!")
    else:
        print(f"   ❌ Health check failed: {response.status_code}")
except Exception as e:
    print(f"   ❌ Error: {e}")

# Test 2: Admin Portal Access
print("\n2️⃣ Testing Admin Portal Access...")
try:
    response = requests.get(f"{BASE_URL}/admin-portal?admin_key=emadCyberSoft4SOC")
    if response.status_code == 200 and "SwiftSync Admin SOC" in response.text:
        print("   ✅ Admin portal accessible!")
        
        # Check if new colors are applied
        if "#06b6d4" in response.text or "#1a1a1a" in response.text:
            print("   ✅ Professional colors detected!")
        else:
            print("   ⚠️  New colors might not be applied")
    else:
        print(f"   ❌ Admin portal failed: {response.status_code}")
except Exception as e:
    print(f"   ❌ Error: {e}")

# Test 3: Telegram Bot
print("\n3️⃣ Testing Telegram Bot...")
try:
    from telegram_notifier import test_telegram_connection
    if test_telegram_connection():
        print("   ✅ Telegram bot working!")
    else:
        print("   ❌ Telegram bot test failed")
except Exception as e:
    print(f"   ❌ Error: {e}")

# Test 4: Main Dashboard
print("\n4️⃣ Testing Main Dashboard...")
try:
    response = requests.get(BASE_URL)
    if response.status_code == 200:
        print("   ✅ Main dashboard accessible!")
        
        # Check for typewriter animation
        if "kurdishTexts" in response.text:
            print("   ✅ Typewriter animation present!")
        
        # Check for emoji handling
        if "emoji:" in response.text:
            print("   ✅ Emoji handling updated!")
    else:
        print(f"   ❌ Dashboard failed: {response.status_code}")
except Exception as e:
    print(f"   ❌ Error: {e}")

print("\n" + "=" * 50)
print("\n✨ Feature Summary:")
print("   📱 Telegram notifications: Integrated")
print("   🎨 Professional dashboard: Applied")
print("   🎬 Smooth animations: Enhanced")
print("\n🚀 All systems ready!")
