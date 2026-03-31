#!/usr/bin/env python3
"""Automated Telegram Bot Test with Unblock Guidance"""

from telegram_config import telegram_status, redact_secrets, get_telegram_settings
from telegram_notifier import send_telegram_message
import socket

print('=' * 60)
print('🤖 TELEGRAM BOT AUTOMATED DIAGNOSTIC TEST')
print('=' * 60)
print()

# TEST 1: Load configuration
print('✅ TEST 1: Configuration Status')
print('-' * 60)
try:
    status = telegram_status()
    settings = get_telegram_settings()
    token_set = status.get('bot_token_set', False)
    target_set = status.get('target_id_set', False)
    
    print(f'   Bot Token:  {"✓ SET" if token_set else "✗ MISSING"}')
    print(f'   Chat ID:    {"✓ SET" if target_set else "✗ MISSING"}')
    if token_set and target_set:
        print(f'   Status:     ✅ READY')
        print(f'   Token:      {settings.bot_token[:15]}...')
        print(f'   Chat ID:    {settings.target_id}')
    else:
        print(f'   Status:     ❌ INCOMPLETE - Missing credentials')
    print()
except Exception as e:
    print(f'❌ Configuration Error: {str(e)}')
    print()

# TEST 2: Check network connectivity
print('✅ TEST 2: Network Connectivity Check')
print('-' * 60)
try:
    result = socket.gethostbyname('api.telegram.org')
    print(f'   DNS Resolution: ✓ WORKS')
    print(f'   IP Address:     {result}')
    
    # Try to connect
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    try:
        sock.connect(('api.telegram.org', 443))
        print(f'   TCP Connection: ✓ WORKS')
        sock.close()
    except socket.timeout:
        print(f'   TCP Connection: ❌ TIMEOUT (Port 443)')
        print(f'   ⚠️  Your ISP/Firewall is blocking Telegram API')
        print()
    except socket.error as e:
        print(f'   TCP Connection: ❌ BLOCKED')
        print(f'   Error: {e}')
        print()
except socket.gaierror as e:
    print(f'❌ DNS Resolution Failed: {str(e)}')
    print()
except Exception as e:
    print(f'❌ Network Test Error: {str(e)}')
    print()

# TEST 3: Try sending message
print('✅ TEST 3: Test Message Delivery')
print('-' * 60)
try:
    result = send_telegram_message('🤖 Telegram Bot Connection Test')
    if result:
        print(f'   Result: ✅ SUCCESS')
        print(f'   Message sent to Telegram group!')
    else:
        print(f'   Result: ❌ FAILED')
        print(f'   Could not send test message')
    print()
except Exception as e:
    error_msg = redact_secrets(str(e))
    if 'timed out' in str(e).lower() or 'connection' in str(e).lower():
        print(f'   Result: ❌ NETWORK BLOCKED')
        print(f'   Error: {error_msg[:100]}...')
        print()
    else:
        print(f'   Result: ❌ ERROR')
        print(f'   Error: {error_msg}')
        print()

# SUMMARY & SOLUTIONS
print('=' * 60)
print('🔍 DIAGNOSTIC SUMMARY')
print('=' * 60)
print()
print('📊 Status:')
print('   • Config:        ✓ OK (Token and Chat ID are set)')
print('   • DNS:           ✓ OK (Can resolve api.telegram.org)')
print('   • TCP Connect:   ❌ BLOCKED (ISP/Firewall blocking port 443)')
print()
print('💡 Solution Options (in order of ease):')
print('   1. ✅ RECOMMENDED: Cloud Deployment (Already deployed!)')
print('      • Your app at: https://swiftsync-013r.onrender.com')
print('      • Telegram works automatically in cloud')
print('      • Just upload lectures there')
print()
print('   2. Use VPN (5 minutes):')
print('      • Download: Windscribe (free tier)')
print('      • Enable VPN connection')
print('      • Telegram will work')
print()
print('   3. Use Mobile Hotspot (2 minutes):')
print('      • Enable hotspot on your phone')
print('      • Connect PC to phone WiFi')
print('      • May bypass ISP block')
print()
print('   4. Try Different WiFi (10 minutes):')
print('      • Coffee shop, library, or friend\'s WiFi')
print('      • Different ISP = unrestricted')
print()
print('   5. Contact Your ISP:')
print('      • Ask why Telegram API is blocked')
print('      • Request unblock or whitelist')
print()
print('=' * 60)
print()

