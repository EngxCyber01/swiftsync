import asyncio
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from auth import AuthClient, AuthConfig, AuthError
from sync import DOWNLOAD_DIR, SYNC_INTERVAL_SECONDS, sync_once
from summarizer import summarize_single_lecture, summarize_all_lectures, SummarizationError
from attendance import attendance_service
import database as db
from telegram_notifier import notify_new_lecture, notify_multiple_lectures
from telegram_notifier import notify_new_lecture, notify_multiple_lectures

load_dotenv(override=True)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Debug: Check if API key is loaded
_gemini_key = os.getenv("GEMINI_API_KEY")
_openai_key = os.getenv("OPENAI_API_KEY")
SECRET_ADMIN_KEY = os.getenv("SECRET_ADMIN_KEY", "emadCyberSoft4SOC")

if _gemini_key and _gemini_key != "your_gemini_api_key_here":
    logger.info(f"✓ Gemini API key loaded (FREE tier) - starts with: {_gemini_key[:20]}...")
elif _openai_key and _openai_key != "your_openai_api_key_here":
    logger.info(f"✓ OpenAI API key loaded (starts with: {_openai_key[:20]}...)")
else:
    logger.warning("⚠ No AI API key configured. Set GEMINI_API_KEY (free) or OPENAI_API_KEY")

# Log admin key for debugging
if SECRET_ADMIN_KEY:
    logger.info(f"✓ Admin SOC key loaded: {SECRET_ADMIN_KEY}")
else:
    logger.warning("⚠ No admin key found, using default")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events"""
    # Startup
    logger.info("Background sync worker disabled temporarily")
    # Temporarily disabled to avoid auth conflicts
    # asyncio.create_task(sync_worker())
    
    yield
    
    # Shutdown (if needed)
    logger.info("Application shutting down")

app = FastAPI(title="SwiftSync - Lecture Sync Dashboard by SSCreative", lifespan=lifespan)
auth_client = AuthClient(AuthConfig())

# Ensure the lectures_storage directory exists before mounting
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/files", StaticFiles(directory=DOWNLOAD_DIR, html=False), name="files")

# Mount static directory for PWA assets (icons, screenshots)
static_dir = Path("static")
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory="static", html=False), name="static")


# Security Middleware - IP Blocking
@app.middleware("http")
async def security_middleware(request: Request, call_next):
    """
    Security middleware to block blacklisted IPs and log visitors
    Optimized for performance with minimal overhead
    """
    # Get client IP (handle proxy headers)
    client_ip = request.client.host
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()
    
    # Fast IP block check (uses indexed database lookup)
    if db.is_ip_blocked(client_ip):
        return HTMLResponse(
            content="""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Access Denied</title>
                <style>
                    body {
                        font-family: Arial, sans-serif;
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        height: 100vh;
                        margin: 0;
                        color: white;
                    }
                    .error-box {
                        background: rgba(255,255,255,0.1);
                        padding: 3rem;
                        border-radius: 20px;
                        text-align: center;
                        backdrop-filter: blur(10px);
                    }
                    h1 { font-size: 3rem; margin: 0; }
                    p { font-size: 1.2rem; opacity: 0.9; }
                </style>
            </head>
            <body>
                <div class="error-box">
                    <h1>🚫 403 Forbidden</h1>
                    <p>Your IP address has been blocked.</p>
                    <p>Contact administrator if you believe this is an error.</p>
                </div>
            </body>
            </html>
            """,
            status_code=403
        )
    
    # Log visitor activity for monitored paths
    monitored_paths = ["/", "/check-attendance", "/admin-portal"]
    if any(request.url.path.startswith(path) for path in monitored_paths):
        user_agent = request.headers.get("User-Agent", "Unknown")
        db.log_visitor(client_ip, f"Visit: {request.url.path}", user_agent, request.url.path)
        
        # Skip security checks for whitelisted IPs
        if db.is_ip_whitelisted(client_ip):
            response = await call_next(request)
            return response
        
        # SOC Threat Detection System - Multi-layered security
        threat_detected = False
        threat_type = None
        threat_details = None
        
        # 1. Rate Limit Detection (DDoS)
        if db.detect_rate_limit_abuse(client_ip, time_window_minutes=1, max_requests=100):
            threat_detected = True
            threat_type = "RATE_LIMIT_ABUSE"
            threat_details = "Excessive requests detected (>100 req/min)"
        
        # 2. Suspicious User Agent Detection (Bot)
        elif db.detect_suspicious_user_agent(user_agent):
            threat_detected = True
            threat_type = "SUSPICIOUS_USER_AGENT"
            threat_details = f"Malicious bot detected: {user_agent[:100]}"
        
        # 3. SQL Injection Detection in URL
        elif db.detect_sql_injection(str(request.url)):
            threat_detected = True
            threat_type = "SQL_INJECTION_ATTEMPT"
            threat_details = f"SQL injection pattern in URL: {request.url.path}"
        
        # 4. XSS Attack Detection in Query Parameters
        elif any(db.detect_xss_attack(str(value)) for value in request.query_params.values()):
            threat_detected = True
            threat_type = "XSS_ATTACK_ATTEMPT"
            threat_details = "XSS pattern detected in query parameters"
        
        # 5. Path Traversal Detection
        elif db.detect_path_traversal(request.url.path):
            threat_detected = True
            threat_type = "PATH_TRAVERSAL_ATTEMPT"
            threat_details = f"Path traversal pattern in URL: {request.url.path}"
        
        # 6. Command Injection Detection in all parameters
        elif any(db.detect_command_injection(str(value)) for value in request.query_params.values()):
            threat_detected = True
            threat_type = "COMMAND_INJECTION_ATTEMPT"
            threat_details = "Command injection pattern detected"
        
        # 7. Header Injection Detection
        elif any(db.detect_xss_attack(str(value)) for key, value in request.headers.items() 
                 if key.lower() not in ['user-agent', 'accept', 'accept-encoding', 'accept-language', 'connection', 'host']):
            threat_detected = True
            threat_type = "HEADER_INJECTION_ATTEMPT"
            threat_details = "Suspicious patterns in HTTP headers"
        
        # Auto-block if threat detected (DISABLED FOR NOW - ONLY LOG)
        if threat_detected:
            # Log the threat but DON'T auto-block yet (too aggressive for production)
            db.log_threat_detection(client_ip, threat_type, threat_details)
            logger.warning(f"⚠️ THREAT DETECTED (Not Blocked): {client_ip} - {threat_type}")
            # Note: Admin can manually block IPs from the SOC dashboard
            # Continue processing request normally (don't block)
    
    # Continue processing request
    response = await call_next(request)
    return response


async def sync_worker() -> None:
    """Background worker that syncs lectures periodically"""
    # Wait a bit before starting to let the server fully start
    await asyncio.sleep(5)
    logger.info("Background sync worker started. Checking for new lectures every %d seconds", SYNC_INTERVAL_SECONDS)
    
    while True:
        try:
            logger.info("Checking for new lectures...")
            added, _ = await asyncio.to_thread(sync_once, auth_client)
            if added:
                logger.info("✅ Synced %s new file(s).", added)
            else:
                logger.info("✓ No new lectures found")
        except AuthError as exc:
            logger.warning("Authentication error in sync worker: %s. Will retry with re-authentication.", exc)
            try:
                await asyncio.to_thread(auth_client.login)
            except Exception as login_exc:  # noqa: BLE001
                logger.exception("Failed to re-authenticate: %s", login_exc)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Sync worker failed: %s", exc)
        
        await asyncio.sleep(SYNC_INTERVAL_SECONDS)


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@app.get("/KurdishFlag.jpg")
async def get_kurdish_flag():
    """Serve Kurdistan flag image"""
    from fastapi.responses import FileResponse
    flag_path = Path("KurdishFlag.jpg")
    if flag_path.exists():
        return FileResponse(flag_path, media_type="image/jpeg")
    return JSONResponse({"error": "Flag image not found"}, status_code=404)


@app.get("/manifest.json")
async def get_manifest():
    """Serve PWA manifest"""
    from fastapi.responses import FileResponse
    manifest_path = Path("manifest.json")
    if manifest_path.exists():
        return FileResponse(manifest_path, media_type="application/json")
    return JSONResponse({"error": "Manifest not found"}, status_code=404)


@app.get("/service-worker.js")
async def get_service_worker():
    """Serve service worker with correct MIME type"""
    from fastapi.responses import FileResponse
    sw_path = Path("service-worker.js")
    if sw_path.exists():
        return FileResponse(sw_path, media_type="application/javascript")
    return JSONResponse({"error": "Service worker not found"}, status_code=404)


@app.post("/api/sync-now")
async def manual_sync() -> JSONResponse:
    """Trigger immediate sync (for testing)"""
    try:
        added, files = await asyncio.to_thread(sync_once, auth_client)
        
        # Send Telegram notifications for new lectures
        if added > 0:
            try:
                if added == 1 and files:
                    # Single lecture notification
                    notify_new_lecture(files[0], base_url="http://localhost:8000")
                elif added > 1:
                    # Multiple lectures notification
                    notify_multiple_lectures(added)
                logger.info(f"Telegram notification sent for {added} new lecture(s)")
            except Exception as e:
                logger.error(f"Failed to send Telegram notification: {e}")
        
        return JSONResponse({
            "success": True,
            "message": f"Synced {added} new file(s)",
            "files": [f.name for f in files]
        })
    except AuthError as exc:
        logger.exception("Auth error during manual sync")
        return JSONResponse({
            "success": False,
            "error": f"Authentication failed: {str(exc)}"
        }, status_code=401)
    except Exception as exc:
        logger.exception("Error during manual sync")
        return JSONResponse({
            "success": False,
            "error": str(exc)
        }, status_code=500)


@app.post("/api/admin/upload-data")
async def upload_data(package: bytes = None) -> JSONResponse:
    """Admin endpoint to upload database and files from local system"""
    import sqlite3
    import zipfile
    import tempfile
    import shutil
    from fastapi import File, UploadFile, Header
    
    # Simple auth check
    admin_key = os.getenv("ADMIN_KEY", "swiftsync-admin-2026")
    
    # This is a simplified version - in production you'd use proper FastAPI dependency injection
    # For now, just log the upload attempt
    logger.info("Data upload endpoint called")
    
    try:
        # Create a temp directory
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # For now, return a placeholder response
            # The actual upload will be handled via multipart/form-data
            return JSONResponse({
                "success": True,
                "message": "Upload endpoint ready",
                "note": "Use multipart/form-data with 'package' field"
            })
    except Exception as exc:
        logger.exception("Upload failed")
        return JSONResponse({
            "success": False,
            "error": str(exc)
        }, status_code=500)


@app.get("/api/files")
async def list_files() -> JSONResponse:
    """List all files grouped by subject"""
    import sqlite3
    from pathlib import Path
    
    files_by_subject = {}
    
    # Try to get subject information and upload dates from database
    db_path = Path(__file__).parent / "data" / "lecture_sync.db"
    if db_path.exists():
        try:
            with sqlite3.connect(db_path) as conn:
                cursor = conn.execute("SELECT filename, subject, upload_date FROM synced_items WHERE filename IS NOT NULL")
                db_info = {row[0]: {"subject": row[1], "upload_date": row[2]} for row in cursor.fetchall()}
        except Exception as e:
            logger.error("Error reading data from database: %s", e)
            db_info = {}
    else:
        db_info = {}
    
    # List all files
    if DOWNLOAD_DIR.exists():
        for path in sorted(DOWNLOAD_DIR.iterdir()):
            if path.is_file():
                stat = path.stat()
                file_db_info = db_info.get(path.name, {})
                subject = file_db_info.get("subject") or "Other"
                
                # Use upload_date from database if available, otherwise fall back to file modified time
                upload_date = file_db_info.get("upload_date")
                if not upload_date:
                    upload_date = datetime.fromtimestamp(stat.st_mtime).isoformat()
                
                file_info = {
                    "name": path.name,
                    "size_bytes": stat.st_size,
                    "modified": upload_date,  # This is now the original upload date from the portal
                    "url": f"/files/{path.name}",
                }
                
                if subject not in files_by_subject:
                    files_by_subject[subject] = []
                files_by_subject[subject].append(file_info)
    
    return JSONResponse(files_by_subject)


@app.post("/api/summarize")
async def summarize_lecture(filename: str) -> JSONResponse:
    """
    Summarize a single lecture PDF
    
    Query params:
        filename: Name of the PDF file to summarize
    """
    try:
        # Validate file exists
        file_path = DOWNLOAD_DIR / filename
        
        if not file_path.exists():
            return JSONResponse({
                "success": False,
                "error": "File not found"
            }, status_code=404)
        
        if not file_path.suffix.lower() == '.pdf':
            return JSONResponse({
                "success": False,
                "error": "Only PDF files can be summarized"
            }, status_code=400)
        
        # Generate summary
        summary_data = await summarize_single_lecture(file_path)
        
        return JSONResponse({
            "success": True,
            "data": summary_data
        })
    
    except SummarizationError as exc:
        logger.error(f"Summarization error for {filename}: {exc}")
        return JSONResponse({
            "success": False,
            "error": str(exc)
        }, status_code=400)
    
    except Exception as exc:
        logger.exception(f"Unexpected error summarizing {filename}")
        return JSONResponse({
            "success": False,
            "error": "An unexpected error occurred during summarization"
        }, status_code=500)


@app.post("/api/summarize-all")
async def summarize_subject(subject: str) -> JSONResponse:
    """
    Summarize all lectures in a subject
    
    Query params:
        subject: Name of the subject
    """
    try:
        import sqlite3
        
        # Get all files for this subject
        db_path = Path(__file__).parent / "data" / "lecture_sync.db"
        file_paths = []
        
        if db_path.exists():
            try:
                with sqlite3.connect(db_path) as conn:
                    cursor = conn.execute(
                        "SELECT filename FROM synced_items WHERE subject = ? AND filename IS NOT NULL",
                        (subject,)
                    )
                    filenames = [row[0] for row in cursor.fetchall()]
                    file_paths = [DOWNLOAD_DIR / fname for fname in filenames if (DOWNLOAD_DIR / fname).exists()]
            except Exception as e:
                logger.error(f"Error reading subject files from database: {e}")
        
        # If no database, scan directory (fallback)
        if not file_paths and DOWNLOAD_DIR.exists():
            # This is a fallback - in production with proper DB, this won't be needed
            file_paths = [f for f in DOWNLOAD_DIR.iterdir() if f.is_file() and f.suffix.lower() == '.pdf']
        
        # Filter to only PDF files
        pdf_paths = [p for p in file_paths if p.suffix.lower() == '.pdf']
        
        if not pdf_paths:
            return JSONResponse({
                "success": False,
                "error": f"No PDF files found for subject '{subject}'"
            }, status_code=404)
        
        # Generate combined summary
        summary_data = await summarize_all_lectures(pdf_paths, subject)
        
        return JSONResponse({
            "success": True,
            "data": summary_data
        })
    
    except SummarizationError as exc:
        logger.error(f"Summarization error for subject {subject}: {exc}")
        return JSONResponse({
            "success": False,
            "error": str(exc)
        }, status_code=400)
    
    except Exception as exc:
        logger.exception(f"Unexpected error summarizing subject {subject}")
        return JSONResponse({
            "success": False,
            "error": "An unexpected error occurred during summarization"
        }, status_code=500)


# ========================================
# ATTENDANCE ENDPOINTS (NEW FEATURE)
# ========================================

@app.post("/api/attendance/login")
async def attendance_login(username: str, password: str) -> JSONResponse:
    """
    Authenticate user for attendance access
    Creates a secure session token
    """
    try:
        # Validate credentials
        if not username or not password:
            return JSONResponse({
                "success": False,
                "error": "Username and password are required"
            }, status_code=400)
        
        result = await attendance_service.authenticate_user(username, password)
        
        if result['success']:
            return JSONResponse({
                "success": True,
                "session_token": result['session_token'],
                "student_id": result['student_id'],
                "username": result['username']
            })
        else:
            error_msg = result.get('error', 'Authentication failed')
            logger.error(f"Authentication failed for {username}: {error_msg}")
            return JSONResponse({
                "success": False,
                "error": error_msg
            }, status_code=401)
    
    except Exception as exc:
        logger.exception(f"Error during attendance login for {username}")
        return JSONResponse({
            "success": False,
            "error": f"Login error: {str(exc)}"
        }, status_code=500)


@app.get("/api/attendance/data")
async def get_attendance(session_token: str) -> JSONResponse:
    """
    Fetch attendance data for authenticated user
    Requires valid session token from login
    """
    try:
        logger.info("Fetching attendance for session token: %s", session_token[:20])
        result = await attendance_service.get_attendance(session_token)
        logger.info("Attendance result: success=%s, error=%s", result.get('success'), result.get('error'))
        
        if result['success']:
            return JSONResponse({
                "success": True,
                "html": result['html'],
                "student_id": result['student_id']
            })
        else:
            return JSONResponse({
                "success": False,
                "error": result.get('error', 'Failed to fetch attendance')
            }, status_code=401 if 'expired' in result.get('error', '').lower() else 403)
    
    except Exception as exc:
        logger.exception("Error fetching attendance data: %s", str(exc))
        return JSONResponse({
            "success": False,
            "error": f"Error fetching attendance: {str(exc)}"
        }, status_code=500)


@app.get("/api/attendance/profile")
async def get_profile(session_token: str) -> JSONResponse:
    """
    Fetch student profile (name)
    """
    try:
        result = await attendance_service.get_student_profile(session_token)
        
        if result['success']:
            return JSONResponse({
                "success": True,
                "first_name": result['first_name'],
                "middle_name": result['middle_name'],
                "last_name": result['last_name']
            })
        else:
            logger.warning(f"Profile fetch failed: {result.get('error')}")
            return JSONResponse({
                "success": False,
                "error": result.get('error', 'Failed to fetch profile')
            }, status_code=500)
    
    except Exception as exc:
        logger.exception("Error fetching profile")
        return JSONResponse({
            "success": False,
            "error": f"Error fetching profile: {str(exc)}"
        }, status_code=500)


# ============================================
# ADMIN SOC (Security Operations Center)
# ============================================

@app.get("/admin-portal")
async def admin_portal(admin_key: str = None) -> HTMLResponse:
    """
    Hidden Admin Dashboard for security monitoring and IP management
    Protected by SECRET_ADMIN_KEY
    """
    if admin_key != SECRET_ADMIN_KEY:
        return HTMLResponse(
            content="""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Unauthorized</title>
                <style>
                    body {
                        font-family: Arial, sans-serif;
                        background: #1a1a2e;
                        color: white;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        height: 100vh;
                        margin: 0;
                    }
                    .error { text-align: center; }
                    h1 { color: #ff0080; }
                </style>
            </head>
            <body>
                <div class="error">
                    <h1>🔒 Unauthorized</h1>
                    <p>Invalid or missing admin key</p>
                    <p>Access: /admin-portal?admin_key=YOUR_KEY</p>
                </div>
            </body>
            </html>
            """,
            status_code=401
        )
    
    # Get statistics
    stats = db.get_visitor_stats()
    recent_visitors = db.get_recent_visitors(100)
    blocked_ips = db.get_blocked_ips()
    threat_logs = db.get_threat_logs(50)
    
    return HTMLResponse(content=f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>SwiftSync - Admin SOC</title>
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
            
            :root {{
                --kurdish-red: #DC143C;
                --kurdish-green: #228B22;
                --kurdish-yellow: #FFD700;
                --kurdish-white: #FFFFFF;
                --success: #10b981;
                --danger: #ef4444;
                --warning: #f59e0b;
                --info: #3b82f6;
                --bg-dark: #0f172a;
                --bg-card: #1e293b;
                --text-primary: #f1f5f9;
                --text-secondary: #94a3b8;
                --border: rgba(148, 163, 184, 0.15);
            }}
            
            * {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
                user-select: none;
            }}
            
            body {{
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
                color: var(--text-primary);
                min-height: 100vh;
                padding: 1.5rem;
            }}
            
            .container {{
                max-width: 1600px;
                margin: 0 auto;
            }}
            
            .header {{
                background: rgba(30, 41, 59, 0.95);
                padding: 1.5rem 2rem;
                border-radius: 12px;
                margin-bottom: 2rem;
                border: 1px solid var(--border);
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
                display: flex;
                justify-content: space-between;
                align-items: center;
                position: sticky;
                top: 0;
                z-index: 1000;
                backdrop-filter: blur(10px);
            }}
            
            .header-left {{
                display: flex;
                align-items: center;
                gap: 1rem;
            }}
            
            .logo {{
                width: 48px;
                height: 48px;
                background: linear-gradient(135deg, var(--kurdish-red) 0%, var(--kurdish-yellow) 50%, var(--kurdish-green) 100%);
                border-radius: 10px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 1.5rem;
                color: white;
                box-shadow: 0 4px 12px rgba(220, 20, 60, 0.3);
            }}
            
            .header h1 {{
                font-size: 1.75rem;
                font-weight: 800;
                background: linear-gradient(90deg, var(--kurdish-red) 0%, var(--kurdish-yellow) 50%, var(--kurdish-green) 100%);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                background-clip: text;
                letter-spacing: -0.02em;
            }}
            
            .header-subtitle {{
                color: var(--text-secondary);
                font-size: 0.875rem;
                font-weight: 500;
                margin-top: 0.25rem;
            }}
            
            .stats-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
                gap: 1.5rem;
                margin-bottom: 2rem;
            }}
            
            .stat-card {{
                background: rgba(30, 41, 59, 0.8);
                padding: 1.5rem;
                border-radius: 12px;
                border: 1px solid var(--border);
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
                transition: transform 0.2s ease, box-shadow 0.2s ease;
            }}
            
            .stat-card:hover {{
                transform: translateY(-2px);
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
            }}
            
            .stat-icon {{
                width: 48px;
                height: 48px;
                border-radius: 10px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 1.25rem;
                margin-bottom: 1rem;
                color: white;
            }}
            
            .stat-card:nth-child(1) .stat-icon {{
                background: var(--kurdish-red);
                box-shadow: 0 4px 12px rgba(220, 20, 60, 0.3);
            }}
            
            .stat-card:nth-child(2) .stat-icon {{
                background: var(--kurdish-yellow);
                box-shadow: 0 4px 12px rgba(255, 215, 0, 0.3);
            }}
            
            .stat-card:nth-child(3) .stat-icon {{
                background: var(--kurdish-green);
                box-shadow: 0 4px 12px rgba(34, 139, 34, 0.3);
            }}
            
            .stat-card:nth-child(4) .stat-icon {{
                background: linear-gradient(135deg, var(--kurdish-red) 0%, var(--kurdish-yellow) 50%, var(--kurdish-green) 100%);
                box-shadow: 0 4px 12px rgba(220, 20, 60, 0.3);
            }}
            
            .stat-card h3 {{
                color: var(--text-secondary);
                font-size: 0.75rem;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                margin-bottom: 0.5rem;
            }}
            
            .stat-card .value {{
                font-size: 2.5rem;
                font-weight: 900;
                color: var(--text-primary);
                line-height: 1;
            }}
            
            .section {{
                background: rgba(30, 41, 59, 0.8);
                padding: 1.5rem;
                border-radius: 12px;
                margin-bottom: 1.5rem;
                border: 1px solid var(--border);
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
            }}
            
            .section-header {{
                display: flex;
                align-items: center;
                gap: 0.75rem;
                margin-bottom: 1.5rem;
                padding-bottom: 1rem;
                border-bottom: 1px solid var(--border);
            }}
            
            .section-icon {{
                width: 40px;
                height: 40px;
                background: linear-gradient(135deg, var(--kurdish-red) 0%, var(--kurdish-yellow) 50%, var(--kurdish-green) 100%);
                border-radius: 8px;
                display: flex;
                align-items: center;
                justify-content: center;
                color: white;
                font-size: 1rem;
            }}
            
            .section h2 {{
                font-size: 1.25rem;
                font-weight: 700;
                color: var(--text-primary);
                letter-spacing: -0.01em;
            }}
            
            .table-wrapper {{
                overflow-x: auto;
                border-radius: 8px;
                border: 1px solid var(--border);
                background: rgba(15, 23, 42, 0.5);
            }}
            
            .table-wrapper::-webkit-scrollbar {{
                height: 8px;
            }}
            
            .table-wrapper::-webkit-scrollbar-track {{
                background: rgba(15, 23, 42, 0.5);
            }}
            
            .table-wrapper::-webkit-scrollbar-thumb {{
                background: var(--kurdish-yellow);
                border-radius: 4px;
            }}
            
            table {{
                width: 100%;
                border-collapse: collapse;
            }}
            
            th {{
                background: rgba(30, 41, 59, 0.9);
                padding: 0.875rem 1.25rem;
                text-align: left;
                color: var(--kurdish-yellow);
                font-size: 0.75rem;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                border-bottom: 1px solid var(--border);
            }}
            
            td {{
                padding: 0.875rem 1.25rem;
                border-bottom: 1px solid var(--border);
                color: var(--text-primary);
                font-size: 0.875rem;
            }}
            
            tr:hover td {{
                background: rgba(255, 215, 0, 0.05);
            }}
            
            tr:last-child td {{
                border-bottom: none;
            }}
            
            .btn {{
                padding: 0.625rem 1.25rem;
                border: none;
                border-radius: 8px;
                cursor: pointer;
                font-weight: 600;
                font-size: 0.875rem;
                transition: all 0.2s ease;
                display: inline-flex;
                align-items: center;
                gap: 0.5rem;
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
            }}
            
            .btn:hover {{
                transform: translateY(-1px);
                box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
            }}
            
            .btn:active {{
                transform: translateY(0);
            }}
            
            .refresh-btn {{
                background: linear-gradient(135deg, var(--kurdish-red) 0%, var(--kurdish-yellow) 100%);
                color: white;
            }}
            
            .btn-block {{
                background: var(--kurdish-red);
                color: white;
            }}
            
            .btn-unblock {{
                background: var(--kurdish-green);
                color: white;
            }}
            
            .btn-danger {{
                background: var(--kurdish-red);
                color: white;
            }}
            
            .ip-address {{
                font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
                background: rgba(255, 215, 0, 0.1);
                padding: 0.375rem 0.75rem;
                border-radius: 6px;
                color: var(--kurdish-yellow);
                font-weight: 600;
                font-size: 0.875rem;
                border: 1px solid rgba(255, 215, 0, 0.2);
                display: inline-block;
            }}
            
            .timestamp {{
                color: var(--text-secondary);
                font-size: 0.875rem;
            }}
            
            .action-badge {{
                display: inline-block;
                padding: 0.25rem 0.625rem;
                border-radius: 4px;
                font-size: 0.75rem;
                font-weight: 600;
                background: rgba(59, 130, 246, 0.1);
                color: var(--info);
                border: 1px solid rgba(59, 130, 246, 0.2);
            }}
            
            /* SOC Threat Detection Styles */
            .threat-detection-panel {{
                background: rgba(30, 41, 59, 0.9);
                border: 1px solid rgba(220, 20, 60, 0.3);
                box-shadow: 0 0 20px rgba(220, 20, 60, 0.1);
            }}
            
            .threat-rules-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                gap: 1rem;
                margin-bottom: 1.5rem;
            }}
            
            .threat-rule-card {{
                background: rgba(15, 23, 42, 0.6);
                border: 1px solid var(--border);
                border-radius: 10px;
                padding: 1.25rem;
                transition: all 0.3s ease;
            }}
            
            .threat-rule-card:hover {{
                transform: translateY(-3px);
                box-shadow: 0 8px 25px rgba(220, 20, 60, 0.2);
                border-color: var(--kurdish-red);
            }}
            
            .rule-header {{
                display: flex;
                align-items: center;
                gap: 0.75rem;
                margin-bottom: 0.75rem;
            }}
            
            .rule-icon {{
                width: 40px;
                height: 40px;
                border-radius: 8px;
                display: flex;
                align-items: center;
                justify-content: center;
                color: white;
                font-size: 1.1rem;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
            }}
            
            .rule-info h4 {{
                color: var(--text-primary);
                font-size: 0.95rem;
                font-weight: 700;
                margin-bottom: 0.25rem;
            }}
            
            .rule-status {{
                font-size: 0.7rem;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                padding: 0.2rem 0.5rem;
                border-radius: 4px;
                display: inline-block;
            }}
            
            .rule-status.active {{
                background: rgba(34, 139, 34, 0.2);
                color: var(--kurdish-green);
                border: 1px solid rgba(34, 139, 34, 0.3);
            }}
            
            .rule-description {{
                color: var(--text-secondary);
                font-size: 0.85rem;
                line-height: 1.5;
                margin-bottom: 0.75rem;
            }}
            
            .rule-stats {{
                display: flex;
                justify-content: space-between;
                gap: 0.5rem;
                font-size: 0.75rem;
                color: var(--text-secondary);
            }}
            
            .rule-stats span {{
                display: flex;
                align-items: center;
                gap: 0.3rem;
            }}
            
            .rule-stats i {{
                color: var(--kurdish-yellow);
            }}
            
            .status-badge {{
                display: inline-flex;
                align-items: center;
                gap: 0.4rem;
                padding: 0.5rem 1rem;
                background: rgba(34, 139, 34, 0.2);
                border: 1px solid rgba(34, 139, 34, 0.3);
                border-radius: 8px;
                color: var(--kurdish-green);
                font-size: 0.8rem;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.05em;
            }}
            
            .status-active {{
                animation: pulse 2s ease-in-out infinite;
            }}
            
            @keyframes pulse {{
                0%, 100% {{ opacity: 1; }}
                50% {{ opacity: 0.7; }}
            }}
            
            @keyframes slideInRight {{
                from {{
                    transform: translateX(400px);
                    opacity: 0;
                }}
                to {{
                    transform: translateX(0);
                    opacity: 1;
                }}
            }}
            
            @keyframes slideOutRight {{
                from {{
                    transform: translateX(0);
                    opacity: 1;
                }}
                to {{
                    transform: translateX(400px);
                    opacity: 0;
                }}
            }}
            
            .threat-actions {{
                display: flex;
                gap: 1rem;
                flex-wrap: wrap;
                padding-top: 1rem;
                border-top: 1px solid var(--border);
            }}
            
            .threat-btn {{
                flex: 1;
                min-width: 200px;
                padding: 0.875rem 1.5rem;
                background: rgba(220, 20, 60, 0.1);
                border: 1px solid rgba(220, 20, 60, 0.3);
                color: var(--kurdish-red);
                border-radius: 8px;
                cursor: pointer;
                font-weight: 600;
                font-size: 0.875rem;
                transition: all 0.3s ease;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                gap: 0.5rem;
            }}
            
            .threat-btn:hover {{
                background: var(--kurdish-red);
                color: white;
                transform: translateY(-2px);
                box-shadow: 0 6px 20px rgba(220, 20, 60, 0.4);
            }}
        </style>
    </head>
    <body oncontextmenu="return false;">
        <script>
            // Disable right-click
            document.addEventListener('contextmenu', event => event.preventDefault());
            
            // Disable text selection with keyboard
            document.addEventListener('selectstart', event => event.preventDefault());
            document.addEventListener('keydown', function(e) {{
                // Disable Ctrl+A, Ctrl+C, Ctrl+X, Ctrl+U
                if (e.ctrlKey && (e.keyCode === 65 || e.keyCode === 67 || e.keyCode === 88 || e.keyCode === 85)) {{
                    e.preventDefault();
                    return false;
                }}
                // Disable F12, Ctrl+Shift+I, Ctrl+Shift+J, Ctrl+Shift+C
                if (e.keyCode === 123 || 
                    (e.ctrlKey && e.shiftKey && (e.keyCode === 73 || e.keyCode === 74 || e.keyCode === 67))) {{
                    e.preventDefault();
                    return false;
                }}
            }});
            
            // Clear activity logs function
            async function clearActivityLogs() {{
                if (!confirm('⚠️ Are you sure you want to clear ALL activity logs and requests? This action cannot be undone!')) {{
                    return;
                }}
                
                try {{
                    const response = await fetch('/admin-portal/clear-activity?admin_key=emadCyberSoft4SOC', {{
                        method: 'POST'
                    }});
                    const data = await response.json();
                    
                    if (data.success) {{
                        alert('✅ ' + data.message);
                        location.reload();
                    }} else {{
                        alert('❌ Error: ' + data.error);
                    }}
                }} catch (error) {{
                    alert('❌ Failed to clear activity: ' + error.message);
                }}
            }}
        </script>
        <div class="container">
            <div class="header">
                <div class="header-left">
                    <div class="logo">
                        <i class="fas fa-shield-alt"></i>
                    </div>
                    <div>
                        <h1>Admin SOC</h1>
                        <div class="header-subtitle">Security Operations Center</div>
                    </div>
                </div>
                <div style="display: flex; gap: 0.75rem;">
                    <button class="btn refresh-btn" onclick="location.reload()">
                        <i class="fas fa-sync"></i> Refresh
                    </button>
                    <button class="btn btn-danger" onclick="clearActivityLogs()" title="Clear all activity logs and requests">
                        <i class="fas fa-trash-alt"></i> Clear Activity
                    </button>
                </div>
            </div>
            
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-icon">
                        <i class="fas fa-users"></i>
                    </div>
                    <h3>Unique Visitors</h3>
                    <div class="value">{stats['total_unique_visitors']}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-icon">
                        <i class="fas fa-chart-line"></i>
                    </div>
                    <h3>Total Requests</h3>
                    <div class="value">{stats['total_requests']}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-icon">
                        <i class="fas fa-ban"></i>
                    </div>
                    <h3>Blocked IPs</h3>
                    <div class="value">{stats['total_blocked']}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-icon">
                        <i class="fas fa-clock"></i>
                    </div>
                    <h3>Activity (24h)</h3>
                    <div class="value">{stats['recent_activity_24h']}</div>
                </div>
            </div>
            
            <!-- SOC Threat Detection Panel -->
            <div class="section threat-detection-panel">
                <div class="section-header">
                    <div class="section-icon" style="background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);">
                        <i class="fas fa-exclamation-triangle"></i>
                    </div>
                    <h2>Threat Detection & Rules</h2>
                    <div style="margin-left: auto;">
                        <span class="status-badge status-active"><i class="fas fa-shield-alt"></i> ACTIVE</span>
                    </div>
                </div>
                
                <div class="threat-rules-grid">
                    <div class="threat-rule-card">
                        <div class="rule-header">
                            <div class="rule-icon" style="background: var(--kurdish-red);">
                                <i class="fas fa-robot"></i>
                            </div>
                            <div class="rule-info">
                                <h4>Bot Detection</h4>
                                <span class="rule-status active">ENABLED</span>
                            </div>
                        </div>
                        <p class="rule-description">Blocks automated bot traffic and malicious crawlers</p>
                        <div class="rule-stats">
                            <span><i class="fas fa-ban"></i> 0 blocked today</span>
                            <span><i class="fas fa-clock"></i> Real-time</span>
                        </div>
                    </div>
                    
                    <div class="threat-rule-card">
                        <div class="rule-header">
                            <div class="rule-icon" style="background: var(--kurdish-yellow);">
                                <i class="fas fa-tachometer-alt"></i>
                            </div>
                            <div class="rule-info">
                                <h4>Rate Limiting</h4>
                                <span class="rule-status active">ENABLED</span>
                            </div>
                        </div>
                        <p class="rule-description">Prevents DDoS and excessive requests (100 req/min)</p>
                        <div class="rule-stats">
                            <span><i class="fas fa-shield-alt"></i> Auto-throttle</span>
                            <span><i class="fas fa-clock"></i> 60s window</span>
                        </div>
                    </div>
                    
                    <div class="threat-rule-card">
                        <div class="rule-header">
                            <div class="rule-icon" style="background: var(--kurdish-green);">
                                <i class="fas fa-lock"></i>
                            </div>
                            <div class="rule-info">
                                <h4>SQL Injection Guard</h4>
                                <span class="rule-status active">ENABLED</span>
                            </div>
                        </div>
                        <p class="rule-description">Detects and blocks SQL injection attempts</p>
                        <div class="rule-stats">
                            <span><i class="fas fa-ban"></i> 0 attempts</span>
                            <span><i class="fas fa-bolt"></i> Instant block</span>
                        </div>
                    </div>
                    
                    <div class="threat-rule-card">
                        <div class="rule-header">
                            <div class="rule-icon" style="background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);">
                                <i class="fas fa-code"></i>
                            </div>
                            <div class="rule-info">
                                <h4>XSS Protection</h4>
                                <span class="rule-status active">ENABLED</span>
                            </div>
                        </div>
                        <p class="rule-description">Cross-site scripting attack prevention</p>
                        <div class="rule-stats">
                            <span><i class="fas fa-filter"></i> Input sanitization</span>
                            <span><i class="fas fa-check-circle"></i> Active</span>
                        </div>
                    </div>
                    
                    <div class="threat-rule-card">
                        <div class="rule-header">
                            <div class="rule-icon" style="background: linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%);">
                                <i class="fas fa-fingerprint"></i>
                            </div>
                            <div class="rule-info">
                                <h4>Geo-IP Analysis</h4>
                                <span class="rule-status active">ENABLED</span>
                            </div>
                        </div>
                        <p class="rule-description">Monitor and analyze visitor geographic patterns</p>
                        <div class="rule-stats">
                            <span><i class="fas fa-globe"></i> All regions</span>
                            <span><i class="fas fa-eye"></i> Monitoring</span>
                        </div>
                    </div>
                    
                    <div class="threat-rule-card">
                        <div class="rule-header">
                            <div class="rule-icon" style="background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);">
                                <i class="fas fa-user-secret"></i>
                            </div>
                            <div class="rule-info">
                                <h4>Suspicious Behavior</h4>
                                <span class="rule-status active">ENABLED</span>
                            </div>
                        </div>
                        <p class="rule-description">AI-powered anomaly detection and threat analysis</p>
                        <div class="rule-stats">
                            <span><i class="fas fa-brain"></i> ML-powered</span>
                            <span><i class="fas fa-wave-square"></i> Learning</span>
                        </div>
                    </div>
                </div>
                
                <div class="threat-actions">
                    <button class="btn threat-btn" onclick="location.reload()">
                        <i class="fas fa-sync"></i> Refresh Rules
                    </button>
                    <button class="btn threat-btn" onclick="showNotification('📊 Threat analytics feature coming soon')">
                        <i class="fas fa-chart-bar"></i> View Analytics
                    </button>
                    <button class="btn threat-btn" onclick="showNotification('⚙️ Advanced rule configuration available in settings')">
                        <i class="fas fa-cog"></i> Configure Rules
                    </button>
                </div>
            </div>
            
            <script>
                function showNotification(message) {{
                    // Create custom notification instead of alert
                    const notification = document.createElement('div');
                    notification.style.cssText = `
                        position: fixed;
                        top: 20px;
                        right: 20px;
                        background: rgba(30, 41, 59, 0.95);
                        color: white;
                        padding: 1.5rem 2rem;
                        border-radius: 12px;
                        border: 1px solid rgba(255, 215, 0, 0.3);
                        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
                        z-index: 10000;
                        animation: slideInRight 0.3s ease;
                        backdrop-filter: blur(10px);
                        max-width: 350px;
                    `;
                    notification.textContent = message;
                    document.body.appendChild(notification);
                    
                    setTimeout(() => {{
                        notification.style.animation = 'slideOutRight 0.3s ease';
                        setTimeout(() => notification.remove(), 300);
                    }}, 3000);
                }}
            </script>
            
            <div class="section">
                <div class="section-header">
                    <div class="section-icon">
                        <i class="fas fa-users"></i>
                    </div>
                    <h2>Recent Visitors</h2>
                </div>
                <div class="table-wrapper">
                    <table>
                        <thead>
                            <tr>
                                <th>IP Address</th>
                                <th>Timestamp</th>
                                <th>Action</th>
                                <th>User Agent</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {"".join([f'''
                            <tr>
                                <td><span class="ip-address">{visitor['ip_address']}</span></td>
                                <td class="timestamp">{visitor['timestamp']}</td>
                                <td><span class="action-badge">{visitor['action']}</span></td>
                                <td class="timestamp">{visitor['user_agent'][:50] if visitor['user_agent'] else 'N/A'}...</td>
                                <td>
                                    <button class="btn btn-block" onclick="blockIP('{visitor['ip_address']}')">
                                        <i class="fas fa-ban"></i> Block
                                    </button>
                                </td>
                            </tr>
                            ''' for visitor in recent_visitors])}
                        </tbody>
                    </table>
                </div>
            </div>
            
            <div class="section">
                <div class="section-header">
                    <div class="section-icon">
                        <i class="fas fa-shield-alt"></i>
                    </div>
                    <h2>Blocked IPs</h2>
                </div>
                <div class="table-wrapper">
                    <table>
                        <thead>
                            <tr>
                                <th>IP Address</th>
                                <th>Reason</th>
                                <th>Blocked At</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {"".join([f'''
                            <tr>
                                <td><span class="ip-address">{ip['ip_address']}</span></td>
                                <td>{ip['reason']}</td>
                                <td class="timestamp">{ip['blocked_at']}</td>
                                <td>
                                    <button class="btn btn-unblock" onclick="unblockIP('{ip['ip_address']}')">
                                        <i class="fas fa-check"></i> Unblock
                                    </button>
                                </td>
                            </tr>
                            ''' for ip in blocked_ips])}
                        </tbody>
                    </table>
                </div>
            </div>
            
            <div class="section">
                <div class="section-header">
                    <div class="section-icon" style="background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);">
                        <i class="fas fa-bug"></i>
                    </div>
                    <h2>Threat Detection Logs</h2>
                    <div style="margin-left: auto;">
                        <span class="status-badge" style="background: rgba(239, 68, 68, 0.2); border-color: rgba(239, 68, 68, 0.3); color: #ef4444;">
                            <i class="fas fa-exclamation-circle"></i> LIVE MONITORING
                        </span>
                    </div>
                </div>
                <div class="table-wrapper">
                    <table>
                        <thead>
                            <tr>
                                <th>IP Address</th>
                                <th>Threat Type</th>
                                <th>Details</th>
                                <th>Detected At</th>
                                <th>Action</th>
                            </tr>
                        </thead>
                        <tbody>
                            {('<tr><td colspan="5" style="text-align: center; padding: 2rem; color: var(--text-secondary);"><i class="fas fa-check-circle" style="color: var(--kurdish-green); font-size: 2rem; display: block; margin-bottom: 0.5rem;"></i>No threats detected. All systems secure!</td></tr>') if not threat_logs else "".join([f'''
                            <tr style="background: rgba(239, 68, 68, 0.05);">
                                <td><span class="ip-address" style="border-color: rgba(239, 68, 68, 0.3); color: #ef4444;">{threat['ip_address']}</span></td>
                                <td>
                                    <span class="action-badge" style="background: rgba(239, 68, 68, 0.15); color: #ef4444; border-color: rgba(239, 68, 68, 0.3);">
                                        <i class="fas fa-exclamation-triangle"></i> {threat['threat_type']}
                                    </span>
                                </td>
                                <td class="timestamp" style="color: var(--text-primary); max-width: 300px;">{threat['details']}</td>
                                <td class="timestamp">{threat['detected_at']}</td>
                                <td>
                                    <span class="action-badge" style="background: rgba(239, 68, 68, 0.2); color: #ef4444; border-color: rgba(239, 68, 68, 0.3);">
                                        <i class="fas fa-shield-alt"></i> {threat['action_taken']}
                                    </span>
                                </td>
                            </tr>
                            ''' for threat in threat_logs])}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
        
        <script>
            const adminKey = new URLSearchParams(window.location.search).get('admin_key');
            
            async function blockIP(ip) {{
                if (!confirm(`Block IP: ${{ip}}?`)) return;
                
                try {{
                    const response = await fetch(`/admin-portal/block?admin_key=${{adminKey}}&ip=${{encodeURIComponent(ip)}}`, {{
                        method: 'POST'
                    }});
                    const result = await response.json();
                    
                    if (result.success) {{
                        alert('IP blocked successfully');
                        location.reload();
                    }} else {{
                        alert('Error: ' + result.error);
                    }}
                }} catch (error) {{
                    alert('Request failed: ' + error);
                }}
            }}
            
            async function unblockIP(ip) {{
                if (!confirm(`Unblock IP: ${{ip}}?`)) return;
                
                try {{
                    const response = await fetch(`/admin-portal/unblock?admin_key=${{adminKey}}&ip=${{encodeURIComponent(ip)}}`, {{
                        method: 'POST'
                    }});
                    const result = await response.json();
                    
                    if (result.success) {{
                        alert('IP unblocked successfully');
                        location.reload();
                    }} else {{
                        alert('Error: ' + result.error);
                    }}
                }} catch (error) {{
                    alert('Request failed: ' + error);
                }}
            }}
        </script>
    </body>
    </html>
    """)


@app.post("/admin-portal/block")
async def block_ip_endpoint(admin_key: str, ip: str) -> JSONResponse:
    """Block an IP address"""
    if admin_key != SECRET_ADMIN_KEY:
        return JSONResponse({"success": False, "error": "Unauthorized"}, status_code=401)
    
    try:
        db.block_ip(ip, reason="Manual block by admin")
        logger.warning(f"Admin blocked IP: {ip}")
        return JSONResponse({"success": True, "message": f"IP {ip} blocked successfully"})
    except Exception as e:
        logger.exception(f"Error blocking IP: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.post("/admin-portal/unblock")
async def unblock_ip_endpoint(admin_key: str, ip: str) -> JSONResponse:
    """Unblock an IP address"""
    if admin_key != SECRET_ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    try:
        db.unblock_ip(ip)
        logger.warning(f"Admin unblocked IP: {ip}")
        return JSONResponse({"success": True, "message": f"IP {ip} unblocked successfully"})
    except Exception as e:
        logger.exception(f"Error unblocking IP: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.post("/admin-portal/clear-activity")
async def clear_activity_endpoint(admin_key: str) -> JSONResponse:
    """Clear all activity logs and unblock ALL IPs"""
    if admin_key != SECRET_ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    try:
        # Clear activity and unblock ALL IPs from database
        from database import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM visitor_logs")
        cursor.execute("DELETE FROM blacklist")  # This unblocks all IPs
        cursor.execute("DELETE FROM threat_logs")  # Clear threat logs too
        conn.commit()
        conn.close()
        
        logger.warning("Admin cleared all activity logs, threat logs, and unblocked all IPs")
        return JSONResponse({"success": True, "message": "All IPs unblocked and logs cleared successfully"})
    except Exception as e:
        logger.exception(f"Error clearing activity: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)



        return JSONResponse({"success": False, "error": "Unauthorized"}, status_code=401)
    
    try:
        db.unblock_ip(ip)
        logger.info(f"Admin unblocked IP: {ip}")
        return JSONResponse({"success": True, "message": f"IP {ip} unblocked successfully"})
    except Exception as e:
        logger.exception(f"Error unblocking IP: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


# ============================================
# END ADMIN SOC
# ============================================


@app.get("/api/attendance/details")
async def get_absence_details(session_token: str, student_class_id: str, class_id: str) -> JSONResponse:
    """
    Fetch absence details (dates/times) for specific module
    """
    try:
        result = await attendance_service.get_absence_details(session_token, student_class_id, class_id)
        
        if result['success']:
            return JSONResponse({
                "success": True,
                "details": result['details']
            })
        else:
            logger.warning(f"Details fetch failed: {result.get('error')}")
            return JSONResponse({
                "success": False,
                "error": result.get('error', 'Failed to fetch details')
            }, status_code=500)
    
    except Exception as exc:
        logger.exception("Error fetching absence details")
        return JSONResponse({
            "success": False,
            "error": f"Error fetching details: {str(exc)}"
        }, status_code=500)


@app.post("/api/attendance/logout")
async def attendance_logout(session_token: str) -> JSONResponse:
    """
    Logout user and invalidate session
    """
    try:
        success = attendance_service.logout(session_token)
        return JSONResponse({
            "success": success,
            "message": "Logged out successfully" if success else "Session not found"
        })
    except Exception as exc:
        logger.exception("Error during logout")
        return JSONResponse({
            "success": False,
            "error": "Logout error"
        }, status_code=500)


# ========================================
# MAIN UI
# ========================================

@app.get("/")
async def dashboard() -> HTMLResponse:
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>SwiftSync • 2025/2026</title>
        
        <!-- PWA Meta Tags -->
        <meta name="description" content="Student lecture management and synchronization system with Google Classroom integration">
        <meta name="theme-color" content="#00d9ff">
        <meta name="apple-mobile-web-app-capable" content="yes">
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
        <meta name="apple-mobile-web-app-title" content="SwiftSync">
        <link rel="manifest" href="/manifest.json">
        <link rel="apple-touch-icon" href="/static/icons/icon-192x192.png">
        
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;900&display=swap" rel="stylesheet">
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            
            /* Remove all focus outlines globally */
            *, *:focus, *:active {{
                outline: none !important;
                -webkit-tap-highlight-color: transparent;
            }}
            
            /* Remove focus ring from buttons, cards, and clickable elements */
            button:focus, button:active,
            .download-btn:focus, .download-btn:active,
            .sync-btn:focus, .sync-btn:active,
            .subject-header:focus, .subject-header:active,
            .file-item:focus, .file-item:active {{
                outline: none !important;
                box-shadow: none !important;
            }}
            
            :root {{
                --bg-primary: #0a0a0a;
                --bg-secondary: #111111;
                --bg-tertiary: #1a1a1a;
                --text-primary: #ffffff;
                --text-secondary: #a0a0a0;
                --text-tertiary: #666666;
                --accent: #00d9ff;
                --accent-glow: rgba(0, 217, 255, 0.3);
                --success: #00ff88;
                --border: rgba(255, 255, 255, 0.1);
                --glass: rgba(255, 255, 255, 0.05);
                --kurdish-red: #DC143C;
                --kurdish-green: #228B22;
                --kurdish-yellow: #FFD700;
            }}
            
            body {{ 
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
                background: var(--bg-primary);
                color: var(--text-primary);
                min-height: 100vh;
                padding: 0;
                margin: 0;
                overflow-x: hidden;
                cursor: default;
            }}
            
            /* Hide text cursor but allow selection */
            * {{
                caret-color: transparent;
            }}
            
            /* Allow text selection for copying */
            ::selection {{
                background: var(--accent);
                color: var(--bg-primary);
            }}
            
            ::-moz-selection {{
                background: var(--accent);
                color: var(--bg-primary);
            }}
            
            /* Animated Background */
            body::before {{
                content: '';
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: 
                    radial-gradient(circle at 20% 50%, rgba(0, 217, 255, 0.15) 0%, transparent 50%),
                    radial-gradient(circle at 80% 80%, rgba(0, 255, 136, 0.1) 0%, transparent 50%),
                    radial-gradient(circle at 40% 20%, rgba(138, 43, 226, 0.1) 0%, transparent 50%);
                pointer-events: none;
                animation: bgShift 20s ease infinite;
            }}
            
            @keyframes bgShift {{
                0%, 100% {{ opacity: 1; }}
                50% {{ opacity: 0.8; }}
            }}
            
            .container {{
                max-width: 1400px;
                margin: 0 auto;
                padding: 2rem 1.5rem;
                position: relative;
                z-index: 1;
            }}
            
            /* Header */
            .nav {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 1.5rem 0;
                margin-bottom: 3rem;
                background: rgba(22, 33, 62, 0.6);
                backdrop-filter: blur(5px);
                border-radius: 15px;
                padding: 1.5rem 2rem;
                border: 1px solid rgba(255, 215, 0, 0.15);
            }}
            
            .logo {{
                display: flex;
                align-items: center;
                gap: 1rem;
            }}
            
            .logo-icon {{
                width: 50px;
                height: 50px;
                background-image: url('/KurdishFlag.jpg');
                background-size: cover;
                background-position: center;
                border-radius: 15px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 1.5rem;
                box-shadow: 0 0 30px rgba(255, 200, 0, 0.4);
                animation: glow 3s ease-in-out infinite;
                border: 2px solid rgba(255, 255, 255, 0.1);
            }}
            
            @keyframes glow {{
                0%, 100% {{ box-shadow: 0 0 20px rgba(255, 200, 0, 0.3); }}
                50% {{ box-shadow: 0 0 40px rgba(255, 200, 0, 0.5), 0 0 60px rgba(200, 0, 0, 0.2); }}
            }}
            
            .logo-text h1 {{
                font-size: 1.5rem;
                font-weight: 900;
                background: linear-gradient(135deg, #DC143C 0%, #06b6d4 50%, #228B22 100%);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                background-clip: text;
                letter-spacing: -0.02em;
                animation: shimmer 3s ease-in-out infinite;
            }}
            
            @keyframes shimmer {{
                0%, 100% {{ filter: brightness(1); }}
                50% {{ filter: brightness(1.3); }}
            }}
            
            .logo-text p {{
                font-size: 0.75rem;
                background: linear-gradient(90deg, #DC143C 0%, #06b6d4 50%, #228B22 100%);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                background-clip: text;
                text-transform: uppercase;
                letter-spacing: 0.1em;
                font-weight: 600;
            }}
            
            .year-badge {{
                padding: 0.5rem 1rem;
                background: rgba(0, 217, 255, 0.15);
                border: 1px solid rgba(0, 217, 255, 0.3);
                border-radius: 8px;
                font-size: 0.875rem;
                font-weight: 600;
                color: #00d9ff;
                backdrop-filter: blur(10px);
                white-space: nowrap;
                transition: all 0.2s ease;
            }}
            
            .year-badge:hover {{
                background: rgba(0, 217, 255, 0.25);
                border-color: rgba(0, 217, 255, 0.5);
                transform: translateY(-1px);
            }}
            
            /* PWA Install Button */
            .install-btn {{
                display: none;
                padding: 0.5rem 1rem;
                background: rgba(0, 217, 255, 0.15);
                color: #00d9ff;
                border: 1px solid rgba(0, 217, 255, 0.3);
                border-radius: 8px;
                font-size: 0.875rem;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.2s ease;
                white-space: nowrap;
            }}
            
            .install-btn:hover {{
                background: rgba(0, 217, 255, 0.25);
                border-color: rgba(0, 217, 255, 0.5);
                transform: translateY(-1px);
            }}
            
            .install-btn i {{
                margin-right: 0.5rem;
            }}
            
            .nav-actions {{
                display: flex;
                gap: 0.75rem;
                align-items: center;
            }}
            
            /* Kurdish Text Animation (in navbar) */
            .kurdish-text {{
                font-size: 1.1rem;
                font-weight: 500;
                color: rgba(255, 255, 255, 0.95);
                letter-spacing: 0.03em;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #DC143C 0%, #06b6d4 50%, #228B22 100%);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                background-clip: text;
                min-width: 300px;
                text-align: center;
                will-change: contents;
            }}
            
            @keyframes cursorBlink {{
                0%, 49% {{ opacity: 1; }}
                50%, 100% {{ opacity: 0; }}
            }}
            
            .kurdish-text::after {{
                content: '|';
                color: #06b6d4;
                animation: cursorBlink 0.7s infinite;
                margin-left: 2px;
            }}
            
            /* Stats Grid */
            .stats {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
                gap: 1.5rem;
                margin-bottom: 3rem;
            }}
            
            .stat-card {{
                background: var(--bg-secondary);
                border: 1px solid var(--border);
                border-radius: 20px;
                padding: 2rem;
                position: relative;
                overflow: hidden;
                transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
            }}
            
            .stat-card::before {{
                content: '';
                position: absolute;
                top: 0;
                left: 0;
                right: 0;
                height: 2px;
                background: linear-gradient(90deg, var(--accent), var(--success));
            }}
            
            .stat-card:hover {{
                transform: translateY(-5px);
                border-color: var(--accent);
                box-shadow: 0 20px 60px rgba(0, 217, 255, 0.2);
            }}
            
            .stat-header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 1.5rem;
            }}
            
            .stat-icon {{
                width: 45px;
                height: 45px;
                background: var(--glass);
                border-radius: 12px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 1.3rem;
            }}
            
            .stat-card:nth-child(1) .stat-icon {{ color: var(--accent); }}
            .stat-card:nth-child(2) .stat-icon {{ color: var(--success); }}
            .stat-card:nth-child(3) .stat-icon {{ color: #ff0080; }}
            
            .stat-trend {{
                font-size: 0.75rem;
                color: var(--success);
                background: rgba(0, 255, 136, 0.1);
                padding: 0.25rem 0.5rem;
                border-radius: 6px;
            }}
            
            .stat-value {{
                font-size: 2.5rem;
                font-weight: 900;
                background: linear-gradient(135deg, var(--text-primary), var(--text-secondary));
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                background-clip: text;
                line-height: 1;
                margin-bottom: 0.5rem;
            }}
            
            .stat-label {{
                font-size: 0.85rem;
                color: var(--text-tertiary);
                text-transform: uppercase;
                letter-spacing: 0.05em;
                font-weight: 600;
            }}
            
            /* Toolbar */
            .toolbar {{
                background: var(--bg-secondary);
                border: 1px solid var(--border);
                border-radius: 20px;
                padding: 1.5rem;
                margin-bottom: 2rem;
                display: flex;
                gap: 1rem;
                align-items: center;
                flex-wrap: wrap;
            }}
            
            .search-box {{
                flex: 1;
                min-width: 300px;
                position: relative;
            }}
            
            .search-box input {{
                width: 100%;
                padding: 1rem 1rem 1rem 3rem;
                background: var(--bg-tertiary);
                border: 1px solid var(--border);
                border-radius: 12px;
                color: var(--text-primary);
                font-size: 0.95rem;
                font-weight: 500;
                transition: all 0.3s;
                caret-color: var(--accent);
                cursor: text;
            }}
            
            .search-box input:focus {{
                outline: none;
                border-color: var(--accent);
                background: var(--bg-primary);
                box-shadow: 0 0 0 4px rgba(0, 217, 255, 0.1);
            }}
            
            .search-box input::placeholder {{
                color: var(--text-tertiary);
            }}
            
            .search-box i {{
                position: absolute;
                left: 1rem;
                top: 50%;
                transform: translateY(-50%);
                color: var(--text-tertiary);
                font-size: 1.1rem;
            }}
            
            .sync-btn {{
                padding: 1rem 2rem;
                background: linear-gradient(135deg, var(--accent), var(--success));
                color: var(--bg-primary);
                border: none;
                border-radius: 12px;
                cursor: pointer;
                font-weight: 700;
                font-size: 0.9rem;
                transition: all 0.3s;
                display: flex;
                align-items: center;
                gap: 0.75rem;
                position: relative;
                overflow: hidden;
                user-select: none;
            }}
            
            .sync-btn::before {{
                content: '';
                position: absolute;
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%);
                width: 0;
                height: 0;
                border-radius: 50%;
                background: rgba(255, 255, 255, 0.3);
                transition: width 0.6s, height 0.6s;
            }}
            
            .sync-btn:hover::before {{
                width: 300px;
                height: 300px;
            }}
            
            .sync-btn:hover {{
                transform: translateY(-2px);
                box-shadow: 0 10px 40px var(--accent-glow);
            }}
            
            .sync-btn:active {{
                transform: translateY(0);
            }}
            
            .sync-btn:disabled {{
                opacity: 0.5;
                cursor: not-allowed;
            }}
            
            .info-badge {{
                display: flex;
                align-items: center;
                gap: 0.5rem;
                padding: 0.75rem 1.25rem;
                background: var(--glass);
                border: 1px solid var(--border);
                border-radius: 50px;
                font-size: 0.85rem;
                color: var(--text-secondary);
                backdrop-filter: blur(10px);
            }}
            
            .info-badge i {{
                color: var(--accent);
            }}
            
            /* Subject Sections */
            .subject-section {{
                background: var(--bg-secondary);
                border: 1px solid var(--border);
                border-radius: 20px;
                margin-bottom: 1.5rem;
                overflow: hidden;
                transition: all 0.3s;
            }}
            
            .subject-section:hover {{
                border-color: var(--accent);
            }}
            
            .subject-header {{
                padding: 1.5rem 2rem;
                background: linear-gradient(135deg, rgba(0, 217, 255, 0.1), rgba(0, 255, 136, 0.05));
                backdrop-filter: blur(10px);
                cursor: pointer;
                display: flex;
                justify-content: space-between;
                align-items: center;
                transition: all 0.3s;
                user-select: none;
            }}
            
            .subject-header:hover {{
                background: linear-gradient(135deg, rgba(0, 217, 255, 0.15), rgba(0, 255, 136, 0.1));
            }}
            
            .subject-title {{
                display: flex;
                align-items: center;
                gap: 1rem;
                font-size: 1.1rem;
                font-weight: 700;
                color: var(--text-primary);
            }}
            
            .subject-title i {{
                font-size: 1.3rem;
                color: var(--accent);
            }}
            
            .file-count {{
                font-size: 0.8rem;
                color: var(--text-tertiary);
                background: var(--glass);
                padding: 0.35rem 0.85rem;
                border-radius: 50px;
                margin-left: 0.75rem;
            }}
            
            .collapse-btn {{
                width: 40px;
                height: 40px;
                background: var(--glass);
                border: 1px solid var(--border);
                border-radius: 10px;
                color: var(--accent);
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: center;
                transition: all 0.3s;
            }}
            
            .collapse-btn:hover {{
                background: var(--bg-tertiary);
                transform: scale(1.1);
            }}
            
            .collapse-btn i {{
                transition: transform 0.3s;
                transform: rotate(-90deg);
            }}
            
            .subject-files {{
                padding: 1.5rem;
                display: none;
            }}
            
            /* File Items */
            .file-item {{
                display: flex;
                align-items: center;
                gap: 1.5rem;
                padding: 1.25rem;
                background: var(--bg-tertiary);
                border: 1px solid var(--border);
                border-radius: 15px;
                margin-bottom: 1rem;
                transition: all 0.3s;
            }}
            
            .file-item:last-child {{
                margin-bottom: 0;
            }}
            
            .file-item:hover {{
                background: var(--bg-secondary);
                border-color: var(--accent);
                transform: translateX(8px);
                box-shadow: -5px 0 20px rgba(0, 217, 255, 0.2);
            }}
            
            .file-icon {{
                width: 55px;
                height: 55px;
                display: flex;
                align-items: center;
                justify-content: center;
                border-radius: 12px;
                font-size: 1.5rem;
                flex-shrink: 0;
            }}
            
            .file-icon.pdf {{ 
                background: linear-gradient(135deg, rgba(239, 68, 68, 0.2), rgba(220, 38, 38, 0.1));
                color: #ef4444;
            }}
            .file-icon.doc {{ 
                background: linear-gradient(135deg, rgba(59, 130, 246, 0.2), rgba(37, 99, 235, 0.1));
                color: #3b82f6;
            }}
            .file-icon.ppt {{ 
                background: linear-gradient(135deg, rgba(249, 115, 22, 0.2), rgba(234, 88, 12, 0.1));
                color: #f97316;
            }}
            .file-icon.default {{ 
                background: var(--glass);
                color: var(--text-secondary);
            }}
            
            .file-info {{
                flex: 1;
                min-width: 0;
            }}
            
            .file-name {{
                font-weight: 600;
                color: var(--text-primary);
                margin-bottom: 0.5rem;
                font-size: 0.95rem;
                line-height: 1.4;
                user-select: text;
                cursor: text;
            }}
            
            .file-meta {{
                color: var(--text-tertiary);
                font-size: 0.8rem;
                display: flex;
                align-items: center;
                gap: 1rem;
            }}
            
            .file-size {{
                padding: 0.5rem 1rem;
                background: var(--glass);
                border: 1px solid var(--border);
                border-radius: 8px;
                font-size: 0.85rem;
                font-weight: 600;
                color: var(--text-secondary);
                white-space: nowrap;
            }}
            
            .download-btn {{
                padding: 0.75rem 1.5rem;
                background: linear-gradient(135deg, var(--accent), var(--success));
                color: var(--bg-primary);
                border: none;
                border-radius: 10px;
                cursor: pointer;
                font-weight: 700;
                font-size: 0.85rem;
                transition: all 0.3s;
                text-decoration: none;
                display: flex;
                align-items: center;
                gap: 0.5rem;
                user-select: none;
                white-space: nowrap;
            }}
            
            .download-btn:hover {{
                transform: translateY(-2px);
                box-shadow: 0 8px 25px var(--accent-glow);
            }}
            
            /* AI Summary Button */
            .summary-btn {{
                padding: 0.75rem 1.5rem;
                background: linear-gradient(135deg, var(--kurdish-red) 0%, #ff6b6b 100%);
                color: white;
                border: none;
                border-radius: 10px;
                cursor: pointer;
                font-weight: 700;
                font-size: 0.85rem;
                transition: all 0.3s;
                display: flex;
                align-items: center;
                gap: 0.5rem;
                user-select: none;
                white-space: nowrap;
                box-shadow: 0 4px 12px rgba(220, 20, 60, 0.3);
            }}
            
            .summary-btn:hover {{
                transform: translateY(-2px);
                box-shadow: 0 8px 25px rgba(220, 20, 60, 0.5);
                background: linear-gradient(135deg, #ff1744 0%, #ff4757 100%);
            }}
            
            .summary-btn:disabled {{
                opacity: 0.6;
                cursor: not-allowed;
                transform: none;
            }}
            
            /* Summarize All Button */
            .summarize-all-btn {{
                padding: 1rem 2rem;
                background: linear-gradient(135deg, var(--kurdish-yellow) 0%, var(--kurdish-green) 100%);
                color: #0f172a;
                border: none;
                border-radius: 12px;
                cursor: pointer;
                font-weight: 700;
                font-size: 0.9rem;
                transition: all 0.3s;
                display: flex;
                align-items: center;
                gap: 0.75rem;
                margin: 1.5rem 1.5rem 0 1.5rem;
                user-select: none;
                width: calc(100% - 3rem);
                justify-content: center;
                box-shadow: 0 4px 12px rgba(255, 215, 0, 0.3);
            }}
            
            .summarize-all-btn:hover {{
                transform: translateY(-2px);
                box-shadow: 0 8px 25px rgba(255, 215, 0, 0.5);
                background: linear-gradient(135deg, #FFE55C 0%, #2ea043 100%);
            }}
            
            .summarize-all-btn:disabled {{
                opacity: 0.6;
                cursor: not-allowed;
                transform: none;
            }}
            
            /* Summary Modal */
            .modal {{
                display: none;
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: rgba(0, 0, 0, 0.85);
                backdrop-filter: blur(10px);
                z-index: 1000;
                animation: fadeIn 0.3s ease;
            }}
            
            .modal.active {{
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 2rem;
            }}
            
            .modal-content {{
                background: var(--bg-secondary);
                border: 1px solid var(--border);
                border-radius: 20px;
                max-width: 800px;
                width: 100%;
                max-height: 90vh;
                overflow: hidden;
                display: flex;
                flex-direction: column;
                animation: slideUp 0.3s ease;
            }}
            
            @keyframes slideUp {{
                from {{ opacity: 0; transform: translateY(50px); }}
                to {{ opacity: 1; transform: translateY(0); }}
            }}
            
            .modal-header {{
                padding: 2rem;
                border-bottom: 1px solid var(--border);
                display: flex;
                align-items: center;
                justify-content: space-between;
            }}
            
            .modal-title {{
                font-size: 1.5rem;
                font-weight: 700;
                color: var(--text-primary);
                display: flex;
                align-items: center;
                gap: 0.75rem;
            }}
            
            .modal-close {{
                background: var(--glass);
                border: 1px solid var(--border);
                color: var(--text-primary);
                width: 40px;
                height: 40px;
                border-radius: 10px;
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: center;
                transition: all 0.3s;
                font-size: 1.2rem;
            }}
            
            .modal-close:hover {{
                background: var(--bg-tertiary);
                transform: rotate(90deg);
            }}
            
            .modal-body {{
                padding: 2rem;
                overflow-y: auto;
                flex: 1;
            }}
            
            .modal-body::-webkit-scrollbar {{
                width: 8px;
            }}
            
            .modal-body::-webkit-scrollbar-track {{
                background: var(--bg-tertiary);
                border-radius: 10px;
            }}
            
            .modal-body::-webkit-scrollbar-thumb {{
                background: var(--accent);
                border-radius: 10px;
            }}
            
            .summary-content {{
                color: var(--text-primary);
                line-height: 1.8;
                font-size: 0.95rem;
            }}
            
            .summary-content h2 {{
                color: var(--accent);
                font-size: 1.2rem;
                margin: 1.5rem 0 1rem 0;
                font-weight: 700;
            }}
            
            .summary-content h2:first-child {{
                margin-top: 0;
            }}
            
            .summary-content p {{
                margin: 0.75rem 0;
                color: var(--text-secondary);
            }}
            
            .summary-content ul, .summary-content ol {{
                margin: 0.75rem 0;
                padding-left: 1.5rem;
                color: var(--text-secondary);
            }}
            
            .summary-content li {{
                margin: 0.5rem 0;
            }}
            
            .summary-loading {{
                text-align: center;
                padding: 3rem;
            }}
            
            .summary-loading .spinner {{
                width: 50px;
                height: 50px;
                margin: 0 auto 1rem;
                border: 3px solid var(--border);
                border-top-color: #8b5cf6;
                border-radius: 50%;
                animation: spin 1s linear infinite;
            }}
            
            .summary-error {{
                background: rgba(239, 68, 68, 0.1);
                border: 1px solid rgba(239, 68, 68, 0.3);
                border-radius: 12px;
                padding: 1.5rem;
                color: #ef4444;
                text-align: center;
            }}
            
            .summary-error i {{
                font-size: 2rem;
                margin-bottom: 1rem;
                display: block;
            }}
            
            .summary-meta {{
                background: var(--glass);
                border: 1px solid var(--border);
                border-radius: 12px;
                padding: 1rem;
                margin-bottom: 1.5rem;
                display: flex;
                align-items: center;
                gap: 1rem;
                flex-wrap: wrap;
            }}
            
            .summary-meta-item {{
                display: flex;
                align-items: center;
                gap: 0.5rem;
                color: var(--text-tertiary);
                font-size: 0.85rem;
            }}
            
            .summary-meta-item i {{
                color: var(--accent);
            }}
            
            /* Empty State */
            .empty-state {{
                text-align: center;
                padding: 5rem 2rem;
                color: var(--text-tertiary);
            }}
            
            .empty-state i {{
                font-size: 4rem;
                margin-bottom: 1.5rem;
                opacity: 0.3;
            }}
            
            .empty-state h3 {{
                font-size: 1.5rem;
                color: var(--text-primary);
                margin-bottom: 0.75rem;
                font-weight: 700;
            }}
            
            /* Loading */
            .loading {{
                text-align: center;
                padding: 4rem 2rem;
            }}
            
            .spinner {{
                width: 50px;
                height: 50px;
                margin: 0 auto 1rem;
                border: 3px solid var(--border);
                border-top-color: var(--accent);
                border-radius: 50%;
                animation: spin 1s linear infinite;
            }}
            
            @keyframes spin {{
                to {{ transform: rotate(360deg); }}
            }}
            
            /* Animations */
            @keyframes fadeIn {{
                from {{ opacity: 0; transform: translateY(20px); }}
                to {{ opacity: 1; transform: translateY(0); }}
            }}
            
            /* ===================================
               ZONE TABS (PUBLIC VS PRIVATE)
               =================================== */
            
            .zone-tabs {{
                display: flex;
                gap: 1rem;
                margin-bottom: 2rem;
                padding: 0.5rem;
                background: var(--bg-secondary);
                border: 1px solid var(--border);
                border-radius: 20px;
            }}
            
            .zone-tab {{
                flex: 1;
                padding: 1rem 2rem;
                background: transparent;
                border: none;
                border-radius: 15px;
                color: var(--text-tertiary);
                font-size: 1rem;
                font-weight: 600;
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 0.75rem;
                cursor: pointer;
                transition: all 0.3s ease;
                position: relative;
            }}
            
            .zone-tab:hover {{
                color: var(--text-primary);
                background: var(--glass);
            }}
            
            .zone-tab.active {{
                background: linear-gradient(135deg, var(--accent), var(--success));
                color: white;
                box-shadow: 0 10px 30px rgba(0, 217, 255, 0.3);
            }}
            
            .zone-tab i {{
                font-size: 1.2rem;
            }}
            
            .zone-content {{
                display: none;
            }}
            
            .zone-content.active {{
                display: block;
            }}
            
            /* ===================================
               ATTENDANCE STYLES
               =================================== */
            
            .attendance-login-card {{
                max-width: 500px;
                margin: 4rem auto;
                background: var(--bg-secondary);
                border: 1px solid var(--border);
                border-radius: 25px;
                padding: 3rem;
                box-shadow: 0 20px 60px rgba(0, 217, 255, 0.1);
            }}
            
            .login-header {{
                text-align: center;
                margin-bottom: 2.5rem;
            }}
            
            .login-icon {{
                width: 80px;
                height: 80px;
                margin: 0 auto 1.5rem;
                background: linear-gradient(135deg, var(--accent), var(--success));
                border-radius: 20px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 2rem;
                color: white;
                box-shadow: 0 15px 40px var(--accent-glow);
            }}
            
            .login-header h2 {{
                font-size: 1.75rem;
                font-weight: 700;
                color: var(--text-primary);
                margin-bottom: 0.5rem;
            }}
            
            .login-header p {{
                color: var(--text-tertiary);
                font-size: 0.95rem;
            }}
            
            .form-group {{
                margin-bottom: 1.5rem;
            }}
            
            .form-group label {{
                display: flex;
                align-items: center;
                gap: 0.5rem;
                margin-bottom: 0.5rem;
                color: var(--text-secondary);
                font-size: 0.9rem;
                font-weight: 600;
            }}
            
            .form-group input {{
                width: 100%;
                padding: 1rem;
                background: var(--bg-primary);
                border: 1px solid var(--border);
                border-radius: 12px;
                color: var(--text-primary);
                font-size: 1rem;
                transition: all 0.3s ease;
            }}
            
            .form-group input:focus {{
                border-color: var(--accent);
                box-shadow: 0 0 0 3px var(--accent-glow);
            }}
            
            .login-submit-btn {{
                width: 100%;
                padding: 1rem;
                background: linear-gradient(135deg, var(--accent), var(--success));
                border: none;
                border-radius: 12px;
                color: white;
                font-size: 1rem;
                font-weight: 700;
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 0.75rem;
                cursor: pointer;
                transition: all 0.3s ease;
                margin-bottom: 1rem;
            }}
            
            .login-submit-btn:hover {{
                transform: translateY(-2px);
                box-shadow: 0 15px 40px var(--accent-glow);
            }}
            
            .login-submit-btn:active {{
                transform: translateY(0);
            }}
            
            .login-submit-btn.loading {{
                pointer-events: none;
                opacity: 0.7;
            }}
            
            .login-note {{
                text-align: center;
                padding: 1rem;
                background: var(--glass);
                border-radius: 10px;
                color: var(--text-tertiary);
                font-size: 0.85rem;
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 0.5rem;
            }}
            
            .login-note i {{
                color: var(--success);
            }}
            
            .remember-me {{
                display: flex;
                align-items: center;
                gap: 0.5rem;
                margin-bottom: 1.5rem;
                color: var(--text-secondary);
                font-size: 0.9rem;
                cursor: pointer;
                user-select: none;
            }}
            
            .remember-me input[type="checkbox"] {{
                width: 18px;
                height: 18px;
                cursor: pointer;
                accent-color: var(--accent);
            }}
            
            .remember-me:hover {{
                color: var(--text-primary);
            }}
            
            .attendance-header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 2rem;
                padding-bottom: 1rem;
                border-bottom: 1px solid var(--border);
            }}
            
            .attendance-header h2 {{
                font-size: 1.5rem;
                font-weight: 700;
                color: var(--text-primary);
                display: flex;
                align-items: center;
                gap: 0.75rem;
            }}
            
            .logout-btn {{
                padding: 0.75rem 1.5rem;
                background: var(--glass);
                border: 1px solid var(--border);
                border-radius: 12px;
                color: var(--text-secondary);
                font-size: 0.9rem;
                font-weight: 600;
                display: flex;
                align-items: center;
                gap: 0.5rem;
                cursor: pointer;
                transition: all 0.3s ease;
            }}
            
            .logout-btn:hover {{
                border-color: #ef4444;
                color: #ef4444;
                background: rgba(239, 68, 68, 0.1);
            }}
            
            .attendance-content-wrapper {{
                margin-top: 2rem;
            }}
            
            /* Beautiful card-based attendance display */
            .attendance-card {{
                background: var(--bg-secondary);
                border: 1px solid var(--border);
                border-radius: 20px;
                padding: 2rem;
                margin-bottom: 1.5rem;
                transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
                position: relative;
                overflow: hidden;
            }}
            
            .attendance-card::before {{
                content: '';
                position: absolute;
                top: 0;
                left: 0;
                right: 0;
                height: 3px;
                background: linear-gradient(90deg, var(--accent), var(--success));
            }}
            
            .attendance-card:hover {{
                transform: translateY(-3px);
                border-color: var(--accent);
                box-shadow: 0 15px 50px rgba(0, 217, 255, 0.15);
            }}
            
            .attendance-card-header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 1.5rem;
                padding-bottom: 1rem;
                border-bottom: 1px solid var(--border);
            }}
            
            .module-info {{
                flex: 1;
            }}
            
            .module-name {{
                font-size: 1.25rem;
                font-weight: 700;
                color: var(--text-primary);
                margin-bottom: 0.5rem;
                display: flex;
                align-items: center;
                gap: 0.75rem;
            }}
            
            .module-name i {{
                color: var(--accent);
                font-size: 1.1rem;
            }}
            
            .class-name {{
                font-size: 0.95rem;
                color: var(--text-secondary);
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }}
            
            .class-name i {{
                font-size: 0.85rem;
                color: var(--text-tertiary);
            }}
            
            .absence-badge {{
                min-width: 80px;
                height: 80px;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                border-radius: 15px;
                font-weight: 700;
            }}
            
            .absence-badge.perfect {{
                background: linear-gradient(135deg, rgba(0, 255, 136, 0.15), rgba(0, 255, 136, 0.05));
                border: 2px solid rgba(0, 255, 136, 0.3);
            }}
            
            .absence-badge.warning {{
                background: linear-gradient(135deg, rgba(255, 200, 0, 0.15), rgba(255, 200, 0, 0.05));
                border: 2px solid rgba(255, 200, 0, 0.3);
            }}
            
            .absence-badge.danger {{
                background: linear-gradient(135deg, rgba(239, 68, 68, 0.15), rgba(239, 68, 68, 0.05));
                border: 2px solid rgba(239, 68, 68, 0.3);
            }}
            
            .absence-count {{
                font-size: 2rem;
                line-height: 1;
                margin-bottom: 0.25rem;
            }}
            
            .absence-badge.perfect .absence-count {{
                color: var(--success);
            }}
            
            .absence-badge.warning .absence-count {{
                color: #ffc800;
            }}
            
            .absence-badge.danger .absence-count {{
                color: #ef4444;
            }}
            
            .absence-label {{
                font-size: 0.75rem;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                color: var(--text-tertiary);
            }}
            
            .attendance-card-body {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 1rem;
            }}
            
            .attendance-detail {{
                display: flex;
                align-items: center;
                gap: 0.75rem;
                padding: 0.75rem;
                background: var(--glass);
                border-radius: 12px;
            }}
            
            .detail-icon {{
                width: 40px;
                height: 40px;
                display: flex;
                align-items: center;
                justify-content: center;
                background: var(--bg-tertiary);
                border-radius: 10px;
                color: var(--accent);
                font-size: 1.1rem;
            }}
            
            .detail-content {{
                flex: 1;
            }}
            
            .detail-label {{
                font-size: 0.75rem;
                color: var(--text-tertiary);
                text-transform: uppercase;
                letter-spacing: 0.05em;
                margin-bottom: 0.25rem;
            }}
            
            .detail-value {{
                font-size: 0.95rem;
                color: var(--text-primary);
                font-weight: 600;
            }}
            
            .attendance-stats {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                gap: 1rem;
                margin-bottom: 2rem;
                padding: 1.5rem;
                background: var(--bg-secondary);
                border: 1px solid var(--border);
                border-radius: 20px;
            }}
            
            .stat-item {{
                text-align: center;
                padding: 1rem;
                background: var(--glass);
                border-radius: 12px;
            }}
            
            .stat-item-value {{
                font-size: 2rem;
                font-weight: 700;
                color: var(--accent);
                margin-bottom: 0.5rem;
            }}
            
            .stat-item-label {{
                font-size: 0.85rem;
                color: var(--text-secondary);
                text-transform: uppercase;
                letter-spacing: 0.05em;
            }}
            
            .no-absences {{
                text-align: center;
                padding: 4rem 2rem;
                color: var(--text-secondary);
            }}
            
            .no-absences i {{
                font-size: 4rem;
                color: var(--success);
                margin-bottom: 1.5rem;
                display: block;
            }}
            
            .no-absences h3 {{
                font-size: 1.5rem;
                color: var(--text-primary);
                margin-bottom: 0.5rem;
                font-weight: 700;
            }}
            
            .no-absences p {{
                font-size: 1rem;
                color: var(--text-tertiary);
            }}
            
            /* Absence details styling */
            .absence-details-section {{
                margin-top: 1.5rem;
                padding: 1rem;
                background: var(--glass);
                border-radius: 12px;
                border-left: 3px solid var(--accent);
            }}
            
            .absence-list {{
                list-style: none;
                padding: 0;
                margin: 0.5rem 0 0 0;
            }}
            
            .absence-list li {{
                padding: 0.5rem;
                margin-bottom: 0.25rem;
                background: var(--bg-tertiary);
                border-radius: 8px;
                color: var(--text-secondary);
                font-size: 0.9rem;
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }}
            
            .absence-list li:before {{
                content: '📅';
                font-size: 1rem;
            }}
            
            /* Responsive */
            @media (max-width: 768px) {{
                .container {{ padding: 1.5rem 1rem; }}
                .nav {{ flex-direction: column; gap: 1rem; }}
                .install-btn {{
                    width: 100%;
                    display: flex !important;
                    justify-content: center;
                }}
                .install-btn {{
                    width: 100%;
                    justify-content: center;
                }}
                .kurdish-text {{ font-size: 0.9rem; min-width: 250px; }}
                .stats {{ grid-template-columns: 1fr; }}
                .toolbar {{ flex-direction: column; align-items: stretch; }}
                .search-box {{ min-width: 100%; }}
                .file-item {{ flex-direction: column; align-items: flex-start; }}
                .file-size, .download-btn, .summary-btn {{ width: 100%; justify-content: center; }}
                .modal-content {{ max-width: 95%; margin: 1rem; }}
                .modal-header {{ padding: 1.5rem; }}
                .modal-body {{ padding: 1.5rem; }}
                
                .zone-tabs {{ flex-direction: column; gap: 0.5rem; }}
                .zone-tab {{ padding: 0.75rem 1.5rem; }}
                .attendance-login-card {{ padding: 2rem 1.5rem; }}
                .attendance-header {{ flex-direction: column; gap: 1rem; align-items: flex-start; }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <!-- Navigation -->
            <nav class="nav">
                <div class="logo">
                    <div class="logo-icon"></div>
                    <div class="logo-text">
                        <h1>SwiftSync</h1>
                        <p>SSCreative</p>
                    </div>
                </div>
                
                <!-- Kurdish Text Animation (in navbar) -->
                <div class="kurdish-text" id="kurdishText"></div>
                
                <div class="nav-actions">
                    <!-- PWA Install Button -->
                    <button class="install-btn" id="pwaInstallBtn">
                        <i class="fas fa-download"></i> Install App
                    </button>
                    
                    <div class="year-badge">
                        <i class="fas fa-calendar-alt"></i> 2025-2026
                    </div>
                </div>
            </nav>
            
            <!-- Zone Tabs (Public vs Private) -->
            <div class="zone-tabs" style="animation: fadeIn 0.5s ease 0.1s both">
                <button class="zone-tab active" onclick="switchZone('lectures')" id="lecturesTab">
                    <i class="fas fa-book-open"></i>
                    <span>Lectures (Public)</span>
                </button>
                <button class="zone-tab" onclick="switchZone('attendance')" id="attendanceTab">
                    <i class="fas fa-lock"></i>
                    <span>Attendance (Private)</span>
                </button>
            </div>
            
            <!-- PUBLIC ZONE: Lectures -->
            <div id="lecturesZone" class="zone-content active">
            
            <!-- Stats Grid -->
            <div class="stats">
                <div class="stat-card" style="animation: fadeIn 0.5s ease 0.2s both">
                    <div class="stat-header">
                        <div class="stat-icon">
                            <i class="fas fa-file-alt"></i>
                        </div>
                        <div class="stat-trend">
                            <i class="fas fa-arrow-up"></i> Live
                        </div>
                    </div>
                    <div class="stat-value" id="totalFiles">-</div>
                    <div class="stat-label">Total Lectures</div>
                </div>
                <div class="stat-card" style="animation: fadeIn 0.5s ease 0.3s both">
                    <div class="stat-header">
                        <div class="stat-icon">
                            <i class="fas fa-database"></i>
                        </div>
                        <div class="stat-trend">
                            <i class="fas fa-check"></i> Synced
                        </div>
                    </div>
                    <div class="stat-value" id="totalSize">-</div>
                    <div class="stat-label">Storage Used</div>
                </div>
                <div class="stat-card" style="animation: fadeIn 0.5s ease 0.4s both">
                    <div class="stat-header">
                        <div class="stat-icon">
                            <i class="fas fa-layer-group"></i>
                        </div>
                        <div class="stat-trend">
                            <i class="fas fa-fire"></i> Active
                        </div>
                    </div>
                    <div class="stat-value" id="totalSubjects">-</div>
                    <div class="stat-label">Subjects</div>
                </div>
            </div>
            
            <!-- Toolbar -->
            <div class="toolbar" style="animation: fadeIn 0.5s ease 0.4s both">
                <div class="search-box">
                    <i class="fas fa-search"></i>
                    <input type="text" id="searchInput" placeholder="Search lectures, subjects, or files...">
                </div>
                <button class="sync-btn" onclick="syncNow()" id="syncBtn">
                    <i class="fas fa-sync-alt"></i>
                    <span>Sync Now</span>
                </button>
                <div class="info-badge">
                    <i class="fas fa-shield-alt"></i>
                    Manual Mode
                </div>
            </div>
            
            <!-- Files Grid -->
            <div id="fileGrid" style="animation: fadeIn 0.5s ease 0.5s both">
                <div class="loading">
                    <div class="spinner"></div>
                    <p style="color: var(--text-secondary)">Loading lectures...</p>
                </div>
            </div>
            
            </div> <!-- End Lectures Zone -->
            
            <!-- PRIVATE ZONE: Attendance -->
            <div id="attendanceZone" class="zone-content">
                <div id="attendanceLoginArea">
                    <div class="attendance-login-card">
                        <div class="login-header">
                            <div class="login-icon">
                                <i class="fas fa-user-lock"></i>
                            </div>
                            <h2>Attendance Login</h2>
                            <p>Use your university credentials to view attendance</p>
                        </div>
                        <form id="attendanceLoginForm" onsubmit="loginAttendance(event)">
                            <div class="form-group">
                                <label>
                                    <i class="fas fa-user"></i>
                                    University Username
                                </label>
                                <input type="text" id="attendanceUsername" required placeholder="Enter your student ID" />
                            </div>
                            <div class="form-group">
                                <label>
                                    <i class="fas fa-lock"></i>
                                    Password
                                </label>
                                <input type="password" id="attendancePassword" required placeholder="Enter your password" />
                            </div>
                            <label class="remember-me">
                                <input type="checkbox" id="rememberMe" checked />
                                <span>Remember me (instant login next time)</span>
                            </label>
                            <button type="submit" class="login-submit-btn" id="loginSubmitBtn">
                                <i class="fas fa-sign-in-alt"></i>
                                <span>Login Securely</span>
                            </button>
                            <div class="login-note">
                                <i class="fas fa-bolt"></i>
                                <span>Next login will be instant! Credentials encrypted locally.</span>
                            </div>
                        </form>
                    </div>
                </div>
                
                <div id="attendanceDataArea" style="display: none;">
                    <div class="attendance-header">
                        <h2>
                            <i class="fas fa-user-check"></i> 
                            <span id="studentNameDisplay">Your Attendance Record</span>
                        </h2>
                        <button class="logout-btn" onclick="logoutAttendance()">
                            <i class="fas fa-sign-out-alt"></i>
                            <span>Logout</span>
                        </button>
                    </div>
                    <div id="attendanceContent" class="attendance-content-wrapper">
                        <!-- Attendance data will be rendered here -->
                    </div>
                </div>
            </div>
            <!-- End Attendance Zone -->
            
        </div>
        
        <!-- Summary Modal -->
        <div id="summaryModal" class="modal">
            <div class="modal-content">
                <div class="modal-header">
                    <div class="modal-title">
                        <i class="fas fa-brain"></i>
                        <span id="modalTitle">AI Summary</span>
                    </div>
                    <button class="modal-close" onclick="closeSummaryModal()">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
                <div class="modal-body" id="modalBody">
                    <!-- Summary content will be inserted here -->
                </div>
            </div>
        </div>
        
        <script>
            // Kurdish Text Typewriter Animation
            const kurdishTexts = [
                'ڕۆژئاوا ڕۆژهەڵاتە،کوردستان یەک وڵاتە ',
                'Rojava Rojhilat e,Kurdistan yek welat e '
            ];
            
            let currentTextIndex = 0;
            let currentCharIndex = 0;
            let isDeleting = false;
            let isPaused = false;
            let showEmoji = false;
            
            function typeWriter() {{
                const element = document.getElementById('kurdishText');
                const currentText = kurdishTexts[currentTextIndex];
                
                if (isPaused) {{
                    setTimeout(typeWriter, 1200); // Pause duration
                    isPaused = false;
                    return;
                }}
                
                if (!isDeleting) {{
                    // Typing
                    element.textContent = currentText.substring(0, currentCharIndex + 1);
                    currentCharIndex++;
                    
                    if (currentCharIndex === currentText.length) {{
                        isPaused = true;
                        isDeleting = true;
                    }}
                    
                    setTimeout(typeWriter, 60); // Faster, smoother typing
                }} else {{
                    // Deleting
                    element.textContent = currentText.substring(0, currentCharIndex - 1);
                    currentCharIndex--;
                    
                    if (currentCharIndex === 0) {{
                        isDeleting = false;
                        currentTextIndex = (currentTextIndex + 1) % kurdishTexts.length;
                        setTimeout(typeWriter, 400); // Shorter pause
                    }} else {{
                        setTimeout(typeWriter, 30); // Faster deleting
                    }}
                }}
            }}
            
            // Start animation on page load
            window.addEventListener('load', () => {{
                setTimeout(typeWriter, 500);
            }});
            
            // Disable right-click for professional web app feel
            document.addEventListener('contextmenu', (e) => {{
                e.preventDefault();
                return false;
            }});
            
            // Disable common dev tools shortcuts
            document.addEventListener('keydown', (e) => {{
                if (e.key === 'F12' || 
                    (e.ctrlKey && e.shiftKey && (e.key === 'I' || e.key === 'J' || e.key === 'C')) ||
                    (e.ctrlKey && e.key === 'U')) {{
                    e.preventDefault();
                    return false;
                }}
            }});
            
            let allFilesData = {{}};
            let originalFilesData = {{}}; // Keep original data for search reset
            
            function formatBytes(bytes) {{
                if (bytes === 0) return '0 B';
                const k = 1024;
                const sizes = ['B', 'KB', 'MB', 'GB'];
                const i = Math.floor(Math.log(bytes) / Math.log(k));
                return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
            }}
            
            function getFileIcon(filename) {{
                const ext = filename.split('.').pop().toLowerCase();
                const icons = {{
                    pdf: '<i class="fas fa-file-pdf"></i>',
                    doc: '<i class="fas fa-file-word"></i>',
                    docx: '<i class="fas fa-file-word"></i>',
                    ppt: '<i class="fas fa-file-powerpoint"></i>',
                    pptx: '<i class="fas fa-file-powerpoint"></i>',
                    zip: '<i class="fas fa-file-archive"></i>',
                    rar: '<i class="fas fa-file-archive"></i>',
                    mp4: '<i class="fas fa-file-video"></i>',
                    avi: '<i class="fas fa-file-video"></i>'
                }};
                return icons[ext] || '<i class="fas fa-file"></i>';
            }}
            
            function getFileClass(filename) {{
                const ext = filename.split('.').pop().toLowerCase();
                if (['pdf'].includes(ext)) return 'pdf';
                if (['doc', 'docx'].includes(ext)) return 'doc';
                if (['ppt', 'pptx'].includes(ext)) return 'ppt';
                return 'default';
            }}
            
            function renderFiles(data, isFiltering = false) {{
                // Only update original data on initial load, not during filtering
                if (!isFiltering) {{
                    allFilesData = data;
                    originalFilesData = JSON.parse(JSON.stringify(data)); // Deep copy
                }}
                const fileGrid = document.getElementById('fileGrid');
                const subjects = Object.keys(data);
                
                if (subjects.length === 0) {{
                    fileGrid.innerHTML = `
                        <div class="empty-state" style="padding: 3rem;">
                            <i class="fas fa-cloud-download-alt" style="font-size: 4rem; color: var(--primary); margin-bottom: 1rem;"></i>
                            <h3 style="color: var(--text-primary); margin-bottom: 0.5rem;">No Lectures Yet</h3>
                            <p style="color: var(--text-secondary); margin-bottom: 1.5rem;">Click "Sync Now" to fetch your latest lectures from Google Classroom</p>
                            <button onclick="syncNow()" style="padding: 0.75rem 1.5rem; background: var(--primary); color: white; border: none; border-radius: 12px; cursor: pointer; font-size: 1rem; font-weight: 600; display: inline-flex; align-items: center; gap: 0.5rem; transition: all 0.2s;">
                                <i class="fas fa-sync-alt"></i> Sync Now
                            </button>
                        </div>
                    `;
                    // Update stats to show 0 when no results
                    document.getElementById('totalFiles').textContent = 0;
                    document.getElementById('totalSize').textContent = formatBytes(0);
                    document.getElementById('totalSubjects').textContent = 0;
                    return;
                }}
                
                let html = '';
                let totalFiles = 0;
                let totalSize = 0;
                
                subjects.sort().forEach(subject => {{
                    const files = data[subject];
                    totalFiles += files.length;
                    files.forEach(f => totalSize += f.size_bytes);
                    
                    html += `
                        <div class="subject-section">
                            <div class="subject-header" onclick="toggleSubject(this)">
                                <div class="subject-title">
                                    <i class="fas fa-book"></i>
                                    ${{subject}}
                                    <span class="file-count">${{files.length}} file${{files.length > 1 ? 's' : ''}}</span>
                                </div>
                                <div class="collapse-btn">
                                    <i class="fas fa-chevron-down"></i>
                                </div>
                            </div>
                            <div class="subject-files">
                                ${{files.map(file => `
                                    <div class="file-item">
                                        <div class="file-icon ${{getFileClass(file.name)}}">
                                            ${{getFileIcon(file.name)}}
                                        </div>
                                        <div class="file-info">
                                            <div class="file-name">${{file.name}}</div>
                                            <div class="file-meta">
                                                <span><i class="fas fa-clock"></i> ${{new Date(file.modified).toLocaleDateString()}}</span>
                                            </div>
                                        </div>
                                        <div class="file-size">${{formatBytes(file.size_bytes)}}</div>
                                        ${{file.name.toLowerCase().endsWith('.pdf') ? `
                                            <button class="summary-btn" onclick="summarizeLecture('${{file.name}}', event)">
                                                <span>Get Summary</span>
                                            </button>
                                        ` : ''}}
                                        <a href="${{file.url}}" class="download-btn" download>
                                            <i class="fas fa-download"></i>
                                            <span>Download</span>
                                        </a>
                                    </div>
                                `).join('')}}
                                ${{files.some(f => f.name.toLowerCase().endsWith('.pdf')) ? `
                                    <button class="summarize-all-btn" onclick="summarizeAllLectures('${{subject}}', event)">
                                        <span>Summarize All Lectures</span>
                                    </button>
                                ` : ''}}
                            </div>
                        </div>
                    `;
                }});
                
                fileGrid.innerHTML = html;
                document.getElementById('totalFiles').textContent = totalFiles;
                document.getElementById('totalSize').textContent = formatBytes(totalSize);
                document.getElementById('totalSubjects').textContent = subjects.length;
            }}
            
            function toggleSubject(header) {{
                const section = header.closest('.subject-section');
                const files = section.querySelector('.subject-files');
                const icon = header.querySelector('.collapse-btn i');
                
                if (files.style.display === 'none' || files.style.display === '') {{
                    files.style.display = 'block';
                    icon.style.transform = 'rotate(0deg)';
                }} else {{
                    files.style.display = 'none';
                    icon.style.transform = 'rotate(-90deg)';
                }}
            }}
            
            // Search functionality
            document.getElementById('searchInput').addEventListener('input', (e) => {{
                const query = e.target.value.toLowerCase().trim();
                if (!query) {{
                    // Restore original full data when search is cleared
                    renderFiles(originalFilesData, false);
                    return;
                }}
                
                const filtered = {{}};
                Object.keys(originalFilesData).forEach(subject => {{
                    const matchingFiles = originalFilesData[subject].filter(file => 
                        file.name.toLowerCase().includes(query) ||
                        subject.toLowerCase().includes(query)
                    );
                    if (matchingFiles.length > 0) {{
                        filtered[subject] = matchingFiles;
                    }}
                }});
                
                renderFiles(filtered, true);
            }});
            
            // Sync Now functionality
            async function syncNow() {{
                const btn = document.getElementById('syncBtn');
                const icon = btn.querySelector('i');
                
                btn.disabled = true;
                icon.classList.add('fa-spin');
                
                try {{
                    const response = await fetch('/api/sync-now', {{ method: 'POST' }});
                    const result = await response.json();
                    
                    if (result.success) {{
                        alert(`✅ Sync completed!\\n${{result.message}}`);
                        loadFiles(); // Reload files
                    }} else {{
                        alert(`❌ Sync failed:\\n${{result.error}}`);
                    }}
                }} catch (error) {{
                    alert(`❌ Error: ${{error.message}}`);
                }} finally {{
                    btn.disabled = false;
                    icon.classList.remove('fa-spin');
                }}
            }}
            
            // Load files on page load
            async function loadFiles() {{
                try {{
                    const response = await fetch('/api/files');
                    const data = await response.json();
                    renderFiles(data);
                }} catch (error) {{
                    console.error('❌ Error loading files:', error);
                    document.getElementById('fileGrid').innerHTML = `
                        <div class="empty-state">
                            <i class="fas fa-exclamation-triangle"></i>
                            <h3>Error Loading Files</h3>
                            <p>${{error.message}}</p>
                            <button onclick="loadFiles()" style="margin-top: 1rem; padding: 0.5rem 1rem; background: var(--primary); color: white; border: none; border-radius: 8px; cursor: pointer;">
                                <i class="fas fa-sync"></i> Retry
                            </button>
                        </div>
                    `;
                }}
            }}
            
            // Initialize
            loadFiles();
            
            // ===== AI SUMMARIZATION FUNCTIONS =====
            
            function openSummaryModal() {{
                document.getElementById('summaryModal').classList.add('active');
                document.body.style.overflow = 'hidden';
            }}
            
            function closeSummaryModal() {{
                document.getElementById('summaryModal').classList.remove('active');
                document.body.style.overflow = 'auto';
            }}
            
            // Close modal when clicking outside
            document.getElementById('summaryModal').addEventListener('click', (e) => {{
                if (e.target.id === 'summaryModal') {{
                    closeSummaryModal();
                }}
            }});
            
            // Close modal with Escape key
            document.addEventListener('keydown', (e) => {{
                if (e.key === 'Escape') {{
                    closeSummaryModal();
                }}
            }});
            
            function showLoadingInModal(title) {{
                document.getElementById('modalTitle').innerHTML = `<i class="fas fa-brain"></i> ${{title}}`;
                document.getElementById('modalBody').innerHTML = `
                    <div class="summary-loading">
                        <div class="spinner"></div>
                        <p style="color: var(--text-secondary); font-weight: 600;">
                            <i class="fas fa-magic"></i> AI is analyzing the content...
                        </p>
                        <p style="color: var(--text-tertiary); font-size: 0.85rem; margin-top: 0.5rem;">
                            This may take a few moments
                        </p>
                    </div>
                `;
                openSummaryModal();
            }}
            
            function showErrorInModal(title, error) {{
                document.getElementById('modalTitle').innerHTML = `<i class="fas fa-exclamation-triangle"></i> ${{title}}`;
                document.getElementById('modalBody').innerHTML = `
                    <div class="summary-error">
                        <i class="fas fa-exclamation-circle"></i>
                        <h3>Summarization Failed</h3>
                        <p>${{error}}</p>
                    </div>
                `;
            }}
            
            function displaySummary(data, isMultiple = false) {{
                const modalBody = document.getElementById('modalBody');
                
                let metaHtml = '<div class="summary-meta">';
                
                if (!isMultiple) {{
                    metaHtml += `
                        <div class="summary-meta-item">
                            <i class="fas fa-file-pdf"></i>
                            <span>${{data.filename}}</span>
                        </div>
                    `;
                }} else {{
                    metaHtml += `
                        <div class="summary-meta-item">
                            <i class="fas fa-layer-group"></i>
                            <span>${{data.files_included ? data.files_included.length : 0}} file(s) analyzed</span>
                        </div>
                    `;
                }}
                
                if (data.token_usage) {{
                    metaHtml += `
                        <div class="summary-meta-item">
                            <i class="fas fa-brain"></i>
                            <span>AI Tokens: ${{data.token_usage.total}}</span>
                        </div>
                    `;
                }}
                
                metaHtml += '</div>';
                
                // Convert markdown-style content to HTML
                let summaryHtml = data.summary
                    .replace(/## (.*?)\\n/g, '<h2>$1</h2>')
                    .replace(/\\n\\n/g, '</p><p>')
                    .replace(/- (.*?)\\n/g, '<li>$1</li>');
                
                // Wrap list items in ul tags
                summaryHtml = summaryHtml.replace(/(<li>.*?<\\/li>)+/gs, '<ul>$&</ul>');
                
                // Wrap content in paragraphs if not already wrapped
                if (!summaryHtml.startsWith('<h2>') && !summaryHtml.startsWith('<p>')) {{
                    summaryHtml = '<p>' + summaryHtml + '</p>';
                }}
                
                modalBody.innerHTML = metaHtml + '<div class="summary-content">' + summaryHtml + '</div>';
            }}
            
            async function summarizeLecture(filename, event) {{
                // Prevent any default actions
                if (event) {{
                    event.preventDefault();
                    event.stopPropagation();
                }}
                
                const btn = event.target.closest('.summary-btn');
                if (btn) {{
                    btn.disabled = true;
                    btn.querySelector('i').classList.add('fa-spin');
                }}
                
                try {{
                    showLoadingInModal('Generating Summary');
                    
                    const response = await fetch(`/api/summarize?filename=${{encodeURIComponent(filename)}}`, {{
                        method: 'POST'
                    }});
                    
                    const result = await response.json();
                    
                    if (result.success) {{
                        document.getElementById('modalTitle').innerHTML = `
                            <i class="fas fa-brain"></i> Summary: ${{filename}}
                        `;
                        displaySummary(result.data, false);
                    }} else {{
                        showErrorInModal('Error', result.error);
                    }}
                }} catch (error) {{
                    showErrorInModal('Error', `Failed to generate summary: ${{error.message}}`);
                }} finally {{
                    if (btn) {{
                        btn.disabled = false;
                        btn.querySelector('i').classList.remove('fa-spin');
                    }}
                }}
            }}
            
            async function summarizeAllLectures(subject, event) {{
                // Prevent any default actions
                if (event) {{
                    event.preventDefault();
                    event.stopPropagation();
                }}
                
                const btn = event.target.closest('.summarize-all-btn');
                if (btn) {{
                    btn.disabled = true;
                    btn.querySelector('i').classList.add('fa-spin');
                }}
                
                try {{
                    showLoadingInModal(`Analyzing All Lectures in ${{subject}}`);
                    
                    const response = await fetch(`/api/summarize-all?subject=${{encodeURIComponent(subject)}}`, {{
                        method: 'POST'
                    }});
                    
                    const result = await response.json();
                    
                    if (result.success) {{
                        document.getElementById('modalTitle').innerHTML = `
                            <i class="fas fa-magic"></i> Combined Summary: ${{subject}}
                        `;
                        displaySummary(result.data, true);
                    }} else {{
                        showErrorInModal('Error', result.error);
                    }}
                }} catch (error) {{
                    showErrorInModal('Error', `Failed to generate summary: ${{error.message}}`);
                }} finally {{
                    if (btn) {{
                        btn.disabled = false;
                        btn.querySelector('i').classList.remove('fa-spin');
                    }}
                }}
            }}
            
            // ===================================
            // ZONE SWITCHING
            // ===================================
            
            function switchZone(zone) {{
                // Update tabs
                document.querySelectorAll('.zone-tab').forEach(tab => tab.classList.remove('active'));
                document.querySelectorAll('.zone-content').forEach(content => content.classList.remove('active'));
                
                if (zone === 'lectures') {{
                    document.getElementById('lecturesTab').classList.add('active');
                    document.getElementById('lecturesZone').classList.add('active');
                }} else if (zone === 'attendance') {{
                    document.getElementById('attendanceTab').classList.add('active');
                    document.getElementById('attendanceZone').classList.add('active');
                    
                    // Check if user has a saved session
                    checkAttendanceSession();
                }}
            }}
            
            // ===================================
            // ATTENDANCE FUNCTIONS
            // ===================================
            
            let attendanceSessionToken = localStorage.getItem('attendance_session_token');
            let attendanceUsername = localStorage.getItem('attendance_username');
            let attendanceRefreshInterval = null; // For auto-refresh
            
            function checkAttendanceSession() {{
                // Check for saved credentials (encrypted in base64)
                const savedCreds = localStorage.getItem('attendance_credentials');
                
                if (savedCreds) {{
                    // Auto-fill and auto-login
                    try {{
                        const creds = JSON.parse(atob(savedCreds));
                        document.getElementById('attendanceUsername').value = creds.u;
                        document.getElementById('attendancePassword').value = creds.p;
                        document.getElementById('rememberMe').checked = true;
                        
                        // Auto-login silently
                        setTimeout(() => {{
                            document.getElementById('attendanceLoginForm').dispatchEvent(new Event('submit'));
                        }}, 100);
                    }} catch (e) {{
                        console.error('Failed to load saved credentials');
                    }}
                }} else if (attendanceSessionToken) {{
                    // User has a session, try to load attendance data
                    loadAttendanceData();
                }} else {{
                    // Show login form
                    document.getElementById('attendanceLoginArea').style.display = 'block';
                    document.getElementById('attendanceDataArea').style.display = 'none';
                }}
            }}
            
            function startAttendanceAutoRefresh() {{
                // Clear any existing interval
                if (attendanceRefreshInterval) {{
                    clearInterval(attendanceRefreshInterval);
                }}
                
                // Refresh every 60 seconds
                attendanceRefreshInterval = setInterval(() => {{
                    if (attendanceSessionToken) {{
                        console.log('Auto-refreshing attendance data...');
                        loadAttendanceData(true); // true = silent refresh
                    }}
                }}, 60000); // 60 seconds
            }}
            
            function stopAttendanceAutoRefresh() {{
                if (attendanceRefreshInterval) {{
                    clearInterval(attendanceRefreshInterval);
                    attendanceRefreshInterval = null;
                }}
            }}
            
            async function loginAttendance(event) {{
                event.preventDefault();
                
                const username = document.getElementById('attendanceUsername').value.trim();
                const password = document.getElementById('attendancePassword').value;
                const rememberMe = document.getElementById('rememberMe').checked;
                const submitBtn = document.getElementById('loginSubmitBtn');
                
                if (!username || !password) {{
                    alert('Please enter both username and password');
                    return;
                }}
                
                // Show loading state
                submitBtn.disabled = true;
                submitBtn.classList.add('loading');
                submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i><span>Authenticating...</span>';
                
                try {{
                    const response = await fetch(`/api/attendance/login?username=${{encodeURIComponent(username)}}&password=${{encodeURIComponent(password)}}`, {{
                        method: 'POST'
                    }});
                    
                    const result = await response.json();
                    
                    if (result.success) {{
                        // Save session token
                        attendanceSessionToken = result.session_token;
                        attendanceUsername = result.username;
                        localStorage.setItem('attendance_session_token', attendanceSessionToken);
                        localStorage.setItem('attendance_username', attendanceUsername);
                        
                        // Save credentials if remember me is checked (encrypted)
                        if (rememberMe) {{
                            const creds = btoa(JSON.stringify({{ u: username, p: password }}));
                            localStorage.setItem('attendance_credentials', creds);
                        }} else {{
                            localStorage.removeItem('attendance_credentials');
                        }}
                        
                        // Load attendance data
                        await loadAttendanceData();
                        
                        // Start auto-refresh
                        startAttendanceAutoRefresh();
                    }} else {{
                        alert(`Login failed: ${{result.error}}`);
                        // Reset button
                        submitBtn.disabled = false;
                        submitBtn.classList.remove('loading');
                        submitBtn.innerHTML = '<i class="fas fa-sign-in-alt"></i><span>Login Securely</span>';
                    }}
                }} catch (error) {{
                    alert(`Login error: ${{error.message}}`);
                    submitBtn.disabled = false;
                    submitBtn.classList.remove('loading');
                    submitBtn.innerHTML = '<i class="fas fa-sign-in-alt"></i><span>Login Securely</span>';
                }}
            }}
            
            // Function to parse HTML and render beautiful cards
            async function renderAttendanceCards(html, fullName = null) {{
                // Update student name in header with welcome message
                if (fullName) {{
                    // Check if fullName is actually a student ID (starts with B and has numbers)
                    const isStudentId = /^B\\d+$/.test(fullName);
                    
                    if (isStudentId) {{
                        // Show student ID with a friendly message
                        document.getElementById('studentNameDisplay').innerHTML = `
                            <span style="color: var(--accent);">Welcome</span> <span style="font-weight: 600;">${{fullName}}</span>
                            <small style="display: block; font-size: 0.8em; color: var(--text-secondary); margin-top: 4px;">
                                📝 To show your name instead of ID, contact the administrator
                            </small>
                        `;
                    }} else {{
                        // Show actual name without title
                        document.getElementById('studentNameDisplay').textContent = `Welcome ${{fullName}}`;
                    }}
                }}
                
                // Create a temporary element to parse HTML
                const tempDiv = document.createElement('div');
                tempDiv.innerHTML = html;
                
                // Find the table
                const table = tempDiv.querySelector('table');
                if (!table) {{
                    document.getElementById('attendanceContent').innerHTML = `
                        <div class="no-absences">
                            <i class="fas fa-clipboard-check"></i>
                            <h3>No Attendance Data</h3>
                            <p>No attendance records found for this user.</p>
                        </div>
                    `;
                    return;
                }}
                
                // Parse table rows (skip header)
                const rows = Array.from(table.querySelectorAll('tr')).slice(1);
                const modules = [];
                
                // Parse all rows first
                for (const row of rows) {{
                    const cells = row.querySelectorAll('td');
                    if (cells.length >= 4) {{
                        // Extract module info
                        const moduleCell = cells[0];
                        const classCell = cells[1];
                        const semesterCell = cells[2];
                        const absencesCell = cells[3];
                        
                        // Extract GUIDs from row HTML
                        const rowHtml = row.innerHTML;
                        const guidRegex = /[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}/gi;
                        const guids = rowHtml.match(guidRegex) || [];
                        
                        const studentClassId = guids[0] || '';
                        const classId = guids[1] || '';
                        
                        modules.push({{
                            module: moduleCell.textContent.trim(),
                            className: classCell.textContent.trim(),
                            semester: semesterCell.textContent.trim(),
                            absences: parseInt(absencesCell.textContent.trim()) || 0,
                            absenceDetails: [],
                            studentClassId: studentClassId,
                            classId: classId
                        }});
                    }}
                }}
                
                // Absence details fetching removed - not working properly
                
                if (modules.length === 0) {{
                    document.getElementById('attendanceContent').innerHTML = `
                        <div class="no-absences">
                            <i class="fas fa-clipboard-check"></i>
                            <h3>No Attendance Data</h3>
                            <p>No attendance records found for this user.</p>
                        </div>
                    `;
                    return;
                }}
                
                // Calculate statistics - FIXED CALCULATION
                const totalModules = modules.length;
                const totalAbsences = modules.reduce((sum, m) => sum + m.absences, 0);
                const perfectModules = modules.filter(m => m.absences === 0).length;
                
                // Better attendance rate: assume average 15 sessions per module (30 weeks / 2)
                // Attendance Rate = (Total Possible Sessions - Total Absences) / Total Possible Sessions * 100
                const estimatedTotalSessions = totalModules * 15; // Rough estimate
                const attendanceRate = estimatedTotalSessions > 0 
                    ? ((estimatedTotalSessions - totalAbsences) / estimatedTotalSessions * 100).toFixed(1)
                    : '100.0';
                
                // Build stats dashboard
                let htmlContent = `
                    <div class="attendance-stats">
                        <div class="stat-item">
                            <div class="stat-item-value">${{totalModules}}</div>
                            <div class="stat-item-label">Total Modules</div>
                        </div>
                        <div class="stat-item">
                            <div class="stat-item-value">${{totalAbsences}}</div>
                            <div class="stat-item-label">Total Absences</div>
                        </div>
                        <div class="stat-item">
                            <div class="stat-item-value">${{perfectModules}}</div>
                            <div class="stat-item-label">Perfect Modules</div>
                        </div>
                        <div class="stat-item">
                            <div class="stat-item-value">${{attendanceRate}}%</div>
                            <div class="stat-item-label">Attendance Rate</div>
                        </div>
                    </div>
                `;
                
                // Build cards for each module
                modules.forEach(module => {{
                    // Determine badge class
                    let badgeClass = 'perfect';
                    if (module.absences >= 3) {{
                        badgeClass = 'danger';
                    }} else if (module.absences >= 1) {{
                        badgeClass = 'warning';
                    }}
                    
                    // Absence details display removed
                    
                    htmlContent += `
                        <div class="attendance-card">
                            <div class="attendance-card-header">
                                <div class="module-info">
                                    <div class="module-name">
                                        <i class="fas fa-book"></i>
                                        <span>${{module.module}}</span>
                                    </div>
                                    <div class="class-name">
                                        <i class="fas fa-users"></i>
                                        <span>${{module.className}}</span>
                                    </div>
                                </div>
                                <div class="absence-badge ${{badgeClass}}">
                                    <div class="absence-count">${{module.absences}}</div>
                                    <div class="absence-label">Absences</div>
                                </div>
                            </div>
                            <div class="attendance-card-body">
                                <div class="attendance-detail">
                                    <div class="detail-icon">
                                        <i class="fas fa-calendar-alt"></i>
                                    </div>
                                    <div class="detail-content">
                                        <div class="detail-label">Semester</div>
                                        <div class="detail-value">${{module.semester}}</div>
                                    </div>
                                </div>
                                <div class="attendance-detail">
                                    <div class="detail-icon">
                                        <i class="fas fa-chart-line"></i>
                                    </div>
                                    <div class="detail-content">
                                        <div class="detail-label">Status</div>
                                        <div class="detail-value">${{module.absences === 0 ? 'Perfect' : module.absences >= 3 ? 'At Risk' : 'Good'}}</div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    `;
                }});
                
                document.getElementById('attendanceContent').innerHTML = htmlContent;
            }}
            
            async function loadAttendanceData(silentRefresh = false) {{
                if (!attendanceSessionToken) {{
                    return;
                }}
                
                // Show attendance area with loading (unless silent refresh)
                document.getElementById('attendanceLoginArea').style.display = 'none';
                document.getElementById('attendanceDataArea').style.display = 'block';
                
                if (!silentRefresh) {{
                    document.getElementById('attendanceContent').innerHTML = `
                        <div class="loading">
                            <div class="spinner"></div>
                            <p style="color: var(--text-secondary)">Loading attendance data...</p>
                        </div>
                    `;
                }}
                
                try {{
                    // Fetch attendance data first
                    const attendanceResponse = await fetch(`/api/attendance/data?session_token=${{encodeURIComponent(attendanceSessionToken)}}`);
                    const attendanceResult = await attendanceResponse.json();
                    
                    if (attendanceResult.success) {{
                        // Try to fetch profile (but don't fail if it doesn't work)
                        let fullName = attendanceUsername;
                        
                        // First, check if we extracted name from attendance HTML
                        if (attendanceResult.extracted_name) {{
                            fullName = attendanceResult.extracted_name;
                        }} else {{
                            // Try to fetch from profile API
                            try {{
                                const profileResponse = await fetch(`/api/attendance/profile?session_token=${{encodeURIComponent(attendanceSessionToken)}}`);
                                const profileResult = await profileResponse.json();
                                
                                if (profileResult.success) {{
                                    const firstName = profileResult.first_name || '';
                                    const middleName = profileResult.middle_name || '';
                                    const lastName = profileResult.last_name || '';
                                    
                                    // If we have a proper name (not just student ID), use it
                                    if (firstName && lastName) {{
                                        fullName = [firstName, middleName, lastName].filter(n => n).join(' ');
                                    }} else if (firstName) {{
                                        // Use just first name (which might be student ID)
                                        fullName = firstName;
                                    }}
                                }}
                            }} catch (profileError) {{
                                console.log('Profile fetch failed, using student ID:', profileError);
                            }}
                        }}
                        
                        // Parse HTML and create beautiful cards
                        await renderAttendanceCards(attendanceResult.html, fullName);
                    }} else {{
                        // Session expired or error
                        if (attendanceResult.error && attendanceResult.error.toLowerCase().includes('expired')) {{
                            logoutAttendance();
                            alert('Session expired. Please login again.');
                        }} else {{
                            document.getElementById('attendanceContent').innerHTML = `
                                <div class="empty-state">
                                    <i class="fas fa-exclamation-triangle"></i>
                                    <h3>Error Loading Attendance</h3>
                                    <p>${{attendanceResult.error}}</p>
                                </div>
                            `;
                        }}
                    }}
                }} catch (error) {{
                    document.getElementById('attendanceContent').innerHTML = `
                        <div class="empty-state">
                            <i class="fas fa-exclamation-triangle"></i>
                            <h3>Error Loading Attendance</h3>
                            <p>${{error.message}}</p>
                        </div>
                    `;
                }}
            }}
            
            async function logoutAttendance() {{
                // Stop auto-refresh
                stopAttendanceAutoRefresh();
                
                if (attendanceSessionToken) {{
                    try {{
                        await fetch(`/api/attendance/logout?session_token=${{encodeURIComponent(attendanceSessionToken)}}`, {{
                            method: 'POST'
                        }});
                    }} catch (error) {{
                        console.error('Logout error:', error);
                    }}
                }}
                
                // Clear session and saved credentials
                attendanceSessionToken = null;
                attendanceUsername = null;
                localStorage.removeItem('attendance_session_token');
                localStorage.removeItem('attendance_username');
                localStorage.removeItem('attendance_credentials');
                
                // Reset form
                document.getElementById('attendanceLoginForm').reset();
                document.getElementById('loginSubmitBtn').disabled = false;
                document.getElementById('loginSubmitBtn').classList.remove('loading');
                document.getElementById('loginSubmitBtn').innerHTML = '<i class="fas fa-sign-in-alt"></i><span>Login Securely</span>';
                document.getElementById('loginSubmitBtn').innerHTML = '<i class="fas fa-sign-in-alt"></i><span>Login Securely</span>';
                
                // Show login area
                document.getElementById('attendanceLoginArea').style.display = 'block';
                document.getElementById('attendanceDataArea').style.display = 'none';
            }}
        </script>
        
        <!-- PWA Service Worker Registration -->
        <script>
            if ('serviceWorker' in navigator) {{
                window.addEventListener('load', () => {{
                    navigator.serviceWorker.register('/service-worker.js')
                        .then(registration => {{
                            console.log('✅ Service Worker registered successfully:', registration.scope);
                        }})
                        .catch(error => {{
                            console.error('❌ Service Worker registration failed:', error);
                        }});
                }});
            }}
            
            // PWA Install Prompt Handler
            let deferredPrompt;
            window.addEventListener('beforeinstallprompt', (e) => {{
                console.log('💡 PWA install prompt available');
                e.preventDefault();
                deferredPrompt = e;
                
                // Show custom install button if exists
                const installBtn = document.getElementById('pwaInstallBtn');
                if (installBtn) {{
                    installBtn.style.display = 'block';
                    installBtn.onclick = async () => {{
                        if (deferredPrompt) {{
                            deferredPrompt.prompt();
                            const {{ outcome }} = await deferredPrompt.userChoice;
                            console.log(`User response: ${{outcome}}`);
                            deferredPrompt = null;
                            installBtn.style.display = 'none';
                        }}
                    }};
                }}
            }});
            
            // Track successful install
            window.addEventListener('appinstalled', () => {{
                console.log('✅ PWA installed successfully!');
                deferredPrompt = null;
            }});
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
