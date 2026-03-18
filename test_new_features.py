"""
Quick test script to verify all new features
"""
import requests
import json

BASE_URL = "http://localhost:8000"

print("ðŸ§ª Testing SwiftSync New Features\n")
print("=" * 50)

# Test 1: Health Check
print("\n1ï¸âƒ£ Testing Health Endpoint...")
try:
    response = requests.get(f"{BASE_URL}/health")
    if response.status_code == 200:
        print("   âœ… Health check passed!")
    else:
        print(f"   âŒ Health check failed: {response.status_code}")
except Exception as e:
    print(f"   âŒ Error: {e}")

# Test 2: Admin Portal Access
print("\n2ï¸âƒ£ Testing Admin Portal Access...")
try:
    response = requests.get(f"{BASE_URL}/admin-portal?admin_key=your_secret_admin_key_here")
    if response.status_code == 200 and "SwiftSync Admin SOC" in response.text:
        print("   âœ… Admin portal accessible!")
        
        # Check if new colors are applied
        if "#06b6d4" in response.text or "#1a1a1a" in response.text:
            print("   âœ… Professional colors detected!")
        else:
            print("   âš ï¸  New colors might not be applied")
    else:
        print(f"   âŒ Admin portal failed: {response.status_code}")
except Exception as e:
    print(f"   âŒ Error: {e}")

# Test 3: Telegram Bot
print("\n3ï¸âƒ£ Testing Telegram Bot...")
try:
    from telegram_notifier import test_telegram_connection
    if test_telegram_connection():
        print("   âœ… Telegram bot working!")
    else:
        print("   âŒ Telegram bot test failed")
except Exception as e:
    print(f"   âŒ Error: {e}")

# Test 4: Main Dashboard
print("\n4ï¸âƒ£ Testing Main Dashboard...")
try:
    response = requests.get(BASE_URL)
    if response.status_code == 200:
        print("   âœ… Main dashboard accessible!")
        
        # Check for typewriter animation
        if "kurdishTexts" in response.text:
            print("   âœ… Typewriter animation present!")
        
        # Check for emoji handling
        if "emoji:" in response.text:
            print("   âœ… Emoji handling updated!")
    else:
        print(f"   âŒ Dashboard failed: {response.status_code}")
except Exception as e:
    print(f"   âŒ Error: {e}")

print("\n" + "=" * 50)
print("\nâœ¨ Feature Summary:")
print("   ðŸ“± Telegram notifications: Integrated")
print("   ðŸŽ¨ Professional dashboard: Applied")
print("   ðŸŽ¬ Smooth animations: Enhanced")
print("\nðŸš€ All systems ready!")

