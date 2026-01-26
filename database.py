"""
Database module for SwiftSync Admin SOC
Handles visitor logging and IP blacklist management
"""
import sqlite3
import os
from datetime import datetime
import pytz
from pathlib import Path
from typing import List, Dict, Optional

# Database path
DB_PATH = Path("data") / "lecture_sync.db"


def init_security_tables():
    """Initialize security tables for visitor logs and IP blacklist"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        # Create visitor_logs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS visitor_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip_address TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                action_performed TEXT NOT NULL,
                user_agent TEXT,
                path TEXT,
                username TEXT
            )
        """)
        
        # Create blacklist table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS blacklist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip_address TEXT UNIQUE NOT NULL,
                reason TEXT,
                blocked_at TEXT NOT NULL
            )
        """)
        
        # Create threat_logs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS threat_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip_address TEXT NOT NULL,
                threat_type TEXT NOT NULL,
                details TEXT,
                detected_at TEXT NOT NULL,
                action_taken TEXT
            )
        """)
        
        # Create index for faster IP lookups
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_blacklist_ip 
            ON blacklist(ip_address)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_visitor_logs_ip 
            ON visitor_logs(ip_address)
        """)
        
        conn.commit()


def log_visitor(ip_address: str, action: str, user_agent: str = None, path: str = None, username: str = None):
    """Log a visitor action with optional username/student info"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO visitor_logs (ip_address, timestamp, action_performed, user_agent, path, username)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (ip_address, datetime.now(pytz.timezone('Asia/Baghdad')).isoformat(), action, user_agent, path, username))
            conn.commit()
    except Exception as e:
        print(f"Error logging visitor: {e}")


def is_ip_blocked(ip_address: str) -> bool:
    """Check if an IP is in the blacklist (optimized for speed)"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 1 FROM blacklist WHERE ip_address = ? LIMIT 1
            """, (ip_address,))
            return cursor.fetchone() is not None
    except Exception as e:
        print(f"Error checking IP blacklist: {e}")
        return False


def block_ip(ip_address: str, reason: str = "Manual block"):
    """Add an IP to the blacklist"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO blacklist (ip_address, reason, blocked_at)
            VALUES (?, ?, ?)
        """, (ip_address, reason, datetime.now(pytz.timezone('Asia/Baghdad')).isoformat()))
        conn.commit()


def unblock_ip(ip_address: str):
    """Remove an IP from the blacklist"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM blacklist WHERE ip_address = ?", (ip_address,))
        conn.commit()


def get_recent_visitors(limit: int = 100) -> List[Dict]:
    """Get recent visitor logs with username/student info"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, ip_address, timestamp, action_performed, user_agent, path, username
            FROM visitor_logs
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,))
        
        rows = cursor.fetchall()
        return [
            {
                "id": row[0],
                "ip_address": row[1],
                "timestamp": row[2],
                "action": row[3],
                "user_agent": row[4],
                "path": row[5],
                "username": row[6] if row[6] else "N/A"
            }
            for row in rows
        ]


def get_blocked_ips() -> List[Dict]:
    """Get all blocked IPs"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, ip_address, reason, blocked_at
            FROM blacklist
            ORDER BY blocked_at DESC
        """)
        
        rows = cursor.fetchall()
        return [
            {
                "id": row[0],
                "ip_address": row[1],
                "reason": row[2],
                "blocked_at": row[3]
            }
            for row in rows
        ]


def get_visitor_stats() -> Dict:
    """Get visitor statistics"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        # Total visitors
        cursor.execute("SELECT COUNT(DISTINCT ip_address) FROM visitor_logs")
        total_unique_visitors = cursor.fetchone()[0]
        
        # Total requests
        cursor.execute("SELECT COUNT(*) FROM visitor_logs")
        total_requests = cursor.fetchone()[0]
        
        # Total blocked IPs
        cursor.execute("SELECT COUNT(*) FROM blacklist")
        total_blocked = cursor.fetchone()[0]
        
        # Recent activity (last 24 hours)
        cursor.execute("""
            SELECT COUNT(*) FROM visitor_logs 
            WHERE datetime(timestamp) > datetime('now', '-1 day')
        """)
        recent_activity = cursor.fetchone()[0]
        
        return {
            "total_unique_visitors": total_unique_visitors,
            "total_requests": total_requests,
            "total_blocked": total_blocked,
            "recent_activity_24h": recent_activity
        }


def detect_rate_limit_abuse(ip_address: str, time_window_minutes: int = 1, max_requests: int = 100) -> bool:
    """
    Detect if an IP is making too many requests (DDoS detection)
    Returns True if abuse detected
    """
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM visitor_logs 
            WHERE ip_address = ? 
            AND datetime(timestamp) > datetime('now', '-' || ? || ' minutes')
        """, (ip_address, time_window_minutes))
        count = cursor.fetchone()[0]
        return count > max_requests


def detect_sql_injection(query_string: str) -> bool:
    """
    Detect potential SQL injection attempts with bypass prevention
    Returns True if suspicious patterns found
    """
    import urllib.parse
    
    # Decode URL encoding to prevent bypass
    try:
        decoded = urllib.parse.unquote(query_string)
        # Double decode to catch double encoding
        decoded = urllib.parse.unquote(decoded)
    except:
        decoded = query_string
    
    # Remove spaces, tabs, newlines to prevent obfuscation
    normalized = decoded.replace(' ', '').replace('\t', '').replace('\n', '').replace('\r', '')
    
    sql_patterns = [
        "'or'1'='1",
        "'or1=1",
        "\"or\"1\"=\"1",
        "or1=1",
        "and1=1",
        "and'1'='1",
        "unionselect",
        "droptable",
        "';drop",
        "insertinto",
        "deletefrom",
        "updateset",
        "--",
        "/*",
        "*/",
        "xp_cmdshell",
        "exec(",
        "execute(",
        "sp_executesql",
        "information_schema",
        "sysobjects",
        "syscolumns",
        "benchmark(",
        "sleep(",
        "waitfor",
        "pg_sleep",
        "and1=1",
        "admin'--",
        "'=''",
        "having1=1",
        "groupby",
    ]
    query_lower = query_string.lower()
    normalized_lower = normalized.lower()
    return any(pattern.lower() in query_lower or pattern.lower() in normalized_lower for pattern in sql_patterns)


def detect_xss_attack(input_string: str) -> bool:
    """
    Detect potential XSS (Cross-Site Scripting) attempts with encoding bypass prevention
    Returns True if suspicious patterns found
    """
    import html
    import urllib.parse
    
    # Decode HTML entities and URL encoding
    try:
        decoded = html.unescape(input_string)
        decoded = urllib.parse.unquote(decoded)
        decoded = urllib.parse.unquote(decoded)  # Double decode
    except:
        decoded = input_string
    
    # Remove common obfuscation characters
    normalized = decoded.replace(' ', '').replace('\t', '').replace('\n', '').replace('\r', '').replace('\x00', '')
    
    xss_patterns = [
        "<script",
        "</script",
        "javascript:",
        "onerror=",
        "onload=",
        "onclick=",
        "onmouseover=",
        "onfocus=",
        "<iframe",
        "<embed",
        "<object",
        "eval(",
        "alert(",
        "confirm(",
        "prompt(",
        "document.cookie",
        "window.location",
        "fromcharcode",
        "string.fromcharcode",
        "<svg",
        "<img",
        "src=",
        "href=",
        "javascript",
        "vbscript:",
        "data:text/html",
        "expression(",
        "<base",
        "<meta",
    ]
    input_lower = input_string.lower()
    decoded_lower = decoded.lower()
    normalized_lower = normalized.lower()
    return any(pattern.lower() in input_lower or pattern.lower() in decoded_lower or pattern.lower() in normalized_lower for pattern in xss_patterns)


def detect_suspicious_user_agent(user_agent: str) -> bool:
    """
    Detect known malicious or suspicious user agents (comprehensive bot detection)
    Returns True if suspicious
    """
    if not user_agent or len(user_agent) < 10:
        return True  # No or very short user agent is suspicious
    
    suspicious_agents = [
        "sqlmap",
        "nikto",
        "masscan",
        "nmap",
        "acunetix",
        "metasploit",
        "dirbuster",
        "havij",
        "w3af",
        "webscarab",
        "arachni",
        "burpsuite",
        "burp suite",
        "zap",
        "owasp",
        "scanner",
        "python-requests",
        "curl",
        "wget",
        "scrapy",
        "bot",
        "crawler",
        "spider",
        "scraper",
        "http.rb",
        "mechanize",
        "attack",
        "hack",
        "exploit",
        "injection",
        "probe",
        "test",
        "scan",
    ]
    user_agent_lower = user_agent.lower()
    return any(agent in user_agent_lower for agent in suspicious_agents)


def log_threat_detection(ip_address: str, threat_type: str, details: str):
    """Log a detected threat for monitoring"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        # Create threats table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS threat_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip_address TEXT NOT NULL,
                threat_type TEXT NOT NULL,
                details TEXT,
                detected_at TEXT NOT NULL,
                action_taken TEXT
            )
        """)
        
        cursor.execute("""
            INSERT INTO threat_logs (ip_address, threat_type, details, detected_at, action_taken)
            VALUES (?, ?, ?, ?, ?)
        """, (ip_address, threat_type, details, datetime.now(pytz.timezone('Asia/Baghdad')).isoformat(), "AUTO_BLOCKED"))
        conn.commit()


def get_threat_logs(limit: int = 50) -> List[Dict]:
    """Get recent threat detection logs"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        # Check if table exists
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='threat_logs'
        """)
        if not cursor.fetchone():
            return []
        
        cursor.execute("""
            SELECT ip_address, threat_type, details, detected_at, action_taken
            FROM threat_logs
            ORDER BY detected_at DESC
            LIMIT ?
        """, (limit,))
        
        rows = cursor.fetchall()
        return [
            {
                "ip_address": row[0],
                "threat_type": row[1],
                "details": row[2],
                "detected_at": row[3],
                "action_taken": row[4]
            }
            for row in rows
        ]


def has_threat_log(ip_address: str) -> bool:
    """Check if an IP address has any threat logs"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # Check if table exists
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='threat_logs'
            """)
            if not cursor.fetchone():
                return False
            
            cursor.execute("""
                SELECT 1 FROM threat_logs 
                WHERE ip_address = ? 
                LIMIT 1
            """, (ip_address,))
            
            return cursor.fetchone() is not None
    except Exception as e:
        print(f"Error checking threat log: {e}")
        return False


# Initialize tables on import
try:
    init_security_tables()
    print("✓ Security tables initialized successfully")
except Exception as e:
    print(f"Error initializing security tables: {e}")


def detect_path_traversal(path: str) -> bool:
    """
    Detect path traversal attacks
    Returns True if suspicious patterns found
    """
    import urllib.parse
    
    try:
        decoded = urllib.parse.unquote(path)
        decoded = urllib.parse.unquote(decoded)
    except:
        decoded = path
    
    traversal_patterns = [
        "../",
        "..\\",
        "....//",
        "....\\\\",
        "%2e%2e/",
        "%2e%2e\\",
        "..%2f",
        "..%5c",
        "%252e%252e",
        "..;",
        "..//",
    ]
    
    path_lower = path.lower()
    decoded_lower = decoded.lower()
    
    return any(pattern in path_lower or pattern in decoded_lower for pattern in traversal_patterns)


def detect_command_injection(input_string: str) -> bool:
    """
    Detect command injection attempts
    Returns True if suspicious patterns found
    """
    import urllib.parse
    
    try:
        decoded = urllib.parse.unquote(input_string)
    except:
        decoded = input_string
    
    cmd_patterns = [
        "|",
        "&",
        ";",
        "`",
        "$(",
        "%0a",  # newline URL encoded
        "%0d",  # carriage return
        "&&",
        "||",
        "<(",
        ">(",
        "${{",
    ]
    
    # Check for shell commands
    shell_commands = [
        "bash",
        "sh",
        "cmd",
        "powershell",
        "nc ",
        "netcat",
        "wget ",
        "curl ",
        "rm ",
        "del ",
        "cat ",
        "type ",
        "ping ",
        "whoami",
        "chmod",
        "chown",
    ]
    
    input_lower = input_string.lower()
    decoded_lower = decoded.lower()
    
    has_cmd_pattern = any(pattern in input_string or pattern in decoded for pattern in cmd_patterns)
    has_shell_cmd = any(cmd in input_lower or cmd in decoded_lower for cmd in shell_commands)
    
    return has_cmd_pattern or has_shell_cmd


def is_ip_whitelisted(ip_address: str) -> bool:
    """
    Check if IP is whitelisted (for admin or trusted IPs)
    Returns True if IP should bypass all checks
    """
    # Add your trusted IPs here
    whitelist = [
        "127.0.0.1",
        "localhost",
        "::1",
    ]
    return ip_address in whitelist


def detect_device_type(user_agent: str) -> Dict[str, str]:
    """
    Detect device type, OS, and browser from user agent string
    Returns: {device: str, os: str, browser: str, icon: str}
    """
    if not user_agent:
        return {"device": "Unknown", "os": "Unknown", "browser": "Unknown", "icon": "fa-question"}
    
    ua_lower = user_agent.lower()
    
    # Detect Device Type
    if 'mobile' in ua_lower or 'android' in ua_lower or 'iphone' in ua_lower:
        device = "Mobile"
        icon = "fa-mobile-alt"
    elif 'tablet' in ua_lower or 'ipad' in ua_lower:
        device = "Tablet"
        icon = "fa-tablet-alt"
    else:
        device = "Desktop"
        icon = "fa-desktop"
    
    # Detect Operating System
    if 'windows nt 10' in ua_lower or 'windows nt 11' in ua_lower:
        os_name = "Windows 11"
    elif 'windows nt 6.3' in ua_lower:
        os_name = "Windows 8.1"
    elif 'windows nt 6.2' in ua_lower:
        os_name = "Windows 8"
    elif 'windows nt 6.1' in ua_lower:
        os_name = "Windows 7"
    elif 'windows' in ua_lower:
        os_name = "Windows"
    elif 'android' in ua_lower:
        # Extract Android version
        import re
        match = re.search(r'android\s+([\d.]+)', ua_lower)
        version = match.group(1) if match else ''
        os_name = f"Android {version}" if version else "Android"
        icon = "fa-mobile-alt"
    elif 'iphone' in ua_lower or 'ipad' in ua_lower:
        # Extract iOS version
        import re
        match = re.search(r'os\s+([\d_]+)', ua_lower)
        version = match.group(1).replace('_', '.') if match else ''
        os_name = f"iOS {version}" if version else "iOS"
        icon = "fa-apple"
    elif 'mac os x' in ua_lower or 'macos' in ua_lower or 'macintosh' in ua_lower:
        os_name = "macOS"
        icon = "fa-apple"
    elif 'linux' in ua_lower:
        os_name = "Linux"
    elif 'cros' in ua_lower:
        os_name = "Chrome OS"
    else:
        os_name = "Unknown OS"
    
    # Detect Browser
    if 'edg/' in ua_lower or 'edge' in ua_lower:
        browser = "Edge"
    elif 'chrome' in ua_lower and 'safari' in ua_lower:
        browser = "Chrome"
    elif 'firefox' in ua_lower:
        browser = "Firefox"
    elif 'safari' in ua_lower and 'chrome' not in ua_lower:
        browser = "Safari"
    elif 'opera' in ua_lower or 'opr/' in ua_lower:
        browser = "Opera"
    elif 'msie' in ua_lower or 'trident' in ua_lower:
        browser = "Internet Explorer"
    else:
        browser = "Unknown Browser"
    
    return {
        "device": device,
        "os": os_name,
        "browser": browser,
        "icon": icon
    }

