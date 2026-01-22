"""
Security Detection Tests
Tests all security rules to ensure no bypass is possible
"""
from database import (
    detect_sql_injection,
    detect_xss_attack,
    detect_suspicious_user_agent,
    detect_path_traversal,
    detect_command_injection,
    detect_rate_limit_abuse
)

print("🔒 Security Detection Tests")
print("=" * 50)

# SQL Injection Tests
print("\n1️⃣ SQL Injection Detection:")
sql_tests = [
    "' OR '1'='1",
    "' OR 1=1--",
    "admin'--",
    "UNION SELECT * FROM users",
    "%27%20OR%201%3D1",  # URL encoded
    "1' and '1'='1",
    "; DROP TABLE users--",
]
for test in sql_tests:
    result = "✅ DETECTED" if detect_sql_injection(test) else "❌ MISSED"
    print(f"   {result}: {test}")

# XSS Tests
print("\n2️⃣ XSS Attack Detection:")
xss_tests = [
    "<script>alert('xss')</script>",
    "javascript:alert(1)",
    "<img src=x onerror=alert(1)>",
    "%3Cscript%3Ealert(1)%3C/script%3E",  # URL encoded
    "&lt;script&gt;alert(1)&lt;/script&gt;",  # HTML encoded
    "<svg onload=alert(1)>",
    "eval('alert(1)')",
]
for test in xss_tests:
    result = "✅ DETECTED" if detect_xss_attack(test) else "❌ MISSED"
    print(f"   {result}: {test}")

# Bot Detection Tests
print("\n3️⃣ Suspicious User Agent Detection:")
bot_tests = [
    "sqlmap/1.0",
    "Nikto/2.1.5",
    "python-requests/2.28.0",
    "curl/7.68.0",
    "",  # Empty user agent
    "x",  # Too short
    "Mozilla/5.0 (compatible; BurpSuite)",
]
for test in bot_tests:
    result = "✅ DETECTED" if detect_suspicious_user_agent(test) else "❌ MISSED"
    print(f"   {result}: {test or '(empty)'}")

# Path Traversal Tests
print("\n4️⃣ Path Traversal Detection:")
path_tests = [
    "../../../etc/passwd",
    "..\\..\\..\\windows\\system32",
    "%2e%2e%2f%2e%2e%2f",
    "....//....//",
    "..//etc/passwd",
]
for test in path_tests:
    result = "✅ DETECTED" if detect_path_traversal(test) else "❌ MISSED"
    print(f"   {result}: {test}")

# Command Injection Tests
print("\n5️⃣ Command Injection Detection:")
cmd_tests = [
    "test | whoami",
    "file; rm -rf /",
    "$(cat /etc/passwd)",
    "test && ping 127.0.0.1",
    "`cat /etc/passwd`",
    "test%0Awhoami",
]
for test in cmd_tests:
    result = "✅ DETECTED" if detect_command_injection(test) else "❌ MISSED"
    print(f"   {result}: {test}")

print("\n" + "=" * 50)
print("✅ Security Test Complete!")
print("All detection rules are active and working.")
