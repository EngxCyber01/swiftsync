import asyncio
import hmac
import ipaddress
import json
import logging
import os
import re
import sqlite3
import time
import requests
from datetime import datetime
from pathlib import Path
from typing import List
from contextlib import asynccontextmanager
from bs4 import BeautifulSoup

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
import uvicorn

from auth import AuthClient, AuthConfig, AuthError
from sync import DOWNLOAD_DIR, SYNC_INTERVAL_SECONDS, sync_once, _was_notified, _mark_notified, _get_semester_from_subject
from summarizer import summarize_single_lecture, summarize_all_lectures, SummarizationError
from attendance import attendance_service
from results import results_service
import database as db
from telegram_notifier import notify_new_lecture, notify_multiple_lectures, test_telegram_connection

load_dotenv(override=True)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
# Get base URL from environment or detect from request
BASE_URL = os.getenv("BASE_URL", "https://swiftsync-013r.onrender.com")
IS_PRODUCTION = os.getenv("ENVIRONMENT", "").lower() == "production"
_gemini_key = os.getenv("GEMINI_API_KEY")
_openai_key = os.getenv("OPENAI_API_KEY")
ADMIN_SECRET_KEY = (os.getenv("SECRET_ADMIN_KEY") or os.getenv("ADMIN_KEY") or "").strip()


def _is_valid_admin_key(candidate: str) -> bool:
    return bool(ADMIN_SECRET_KEY) and hmac.compare_digest(candidate or "", ADMIN_SECRET_KEY)

if _gemini_key and _gemini_key != "your_gemini_api_key_here":
    logger.info(f"[OK] Gemini API key loaded (FREE tier) - starts with: {_gemini_key[:20]}...")
elif _openai_key and _openai_key != "your_openai_api_key_here":
    logger.info(f"[OK] OpenAI API key loaded (starts with: {_openai_key[:20]}...)")
else:
    logger.debug("[DEBUG] No AI API key configured - summarization features disabled")

# Log admin key for debugging
if ADMIN_SECRET_KEY:
    logger.info("[OK] Admin SOC key configured (hidden for security)")
else:
    logger.warning("[WARN] No admin key found")
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events"""
    # Startup
    # asyncio.create_task(sync_worker())
    
    yield
    
    # Shutdown (if needed)
    logger.info("Application shutting down")

app = FastAPI(
    title="SwiftSync - Lecture Sync Dashboard by SSCreative",
    lifespan=lifespan,
    docs_url=None if IS_PRODUCTION else "/docs",  # Disable docs in production for performance
    redoc_url=None if IS_PRODUCTION else "/redoc"
)
auth_client = AuthClient(AuthConfig())

# Add compression for faster data transfer (70% smaller responses)
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=6)

# Add CORS middleware with safe defaults (allow explicit origins only)
_allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "").strip()
if _allowed_origins_env:
    _allowed_origins = [origin.strip() for origin in _allowed_origins_env.split(",") if origin.strip()]
else:
    _allowed_origins = [
        BASE_URL,
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    max_age=3600,  # Cache preflight requests for 1 hour
)

# Ensure the lectures_storage directory exists before mounting
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/files", StaticFiles(directory=DOWNLOAD_DIR, html=False), name="files")
static_dir = Path("static")
static_dir.mkdir(exist_ok=True)

# Cache official results snapshots to avoid hard failures when upstream is slow/unstable.
OFFICIAL_RESULTS_CACHE_PATH = Path(os.getenv("OFFICIAL_RESULTS_CACHE_PATH", "data/official_results_cache.json"))
OFFICIAL_RESULTS_CACHE_TTL_SECONDS = max(300, int(os.getenv("OFFICIAL_RESULTS_CACHE_TTL_SECONDS", "21600")))


def _read_official_results_cache() -> dict:
    try:
        if not OFFICIAL_RESULTS_CACHE_PATH.exists():
            return {}
        return json.loads(OFFICIAL_RESULTS_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_official_results_cache(cache: dict) -> None:
    try:
        OFFICIAL_RESULTS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        OFFICIAL_RESULTS_CACHE_PATH.write_text(json.dumps(cache), encoding="utf-8")
    except Exception:
        pass


def _get_cached_official_results(student_id: str) -> dict:
    cache = _read_official_results_cache()
    entry = cache.get(student_id)
    if not isinstance(entry, dict):
        return {}

    ts = int(entry.get("timestamp", 0) or 0)
    if ts <= 0:
        return {}

    if (int(time.time()) - ts) > OFFICIAL_RESULTS_CACHE_TTL_SECONDS:
        return {}

    results = entry.get("results", [])
    if not isinstance(results, list):
        return {}

    return {"results": results, "timestamp": ts}


def _set_cached_official_results(student_id: str, results: list) -> None:
    if not isinstance(results, list):
        return
    cache = _read_official_results_cache()
    cache[student_id] = {
        "timestamp": int(time.time()),
        "results": results,
    }
    _write_official_results_cache(cache)

@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    """Serve favicon.ico from the static directory so /favicon.ico works."""
    favicon_path = static_dir / "favicon.ico"
    if favicon_path.is_file():
        return FileResponse(favicon_path)
    raise HTTPException(status_code=404, detail="Favicon not found")


def get_real_client_ip(request: Request) -> str:
    """
    Get the real client IP address from request, handling all proxy headers.
    Checks multiple headers in order of reliability.
    """
    direct_ip = request.client.host if request.client else "unknown"

    # Only trust forwarded headers when explicitly enabled.
    if not TRUST_PROXY_HEADERS:
        return direct_ip

    # If a trusted-proxy list is configured, require direct peer match.
    if TRUSTED_PROXY_IPS and direct_ip not in TRUSTED_PROXY_IPS:
        return direct_ip

    # Check proxy headers in order of preference with IP validation.
    cf_ip = _normalize_ip(request.headers.get("CF-Connecting-IP", ""))
    if cf_ip:
        return cf_ip

    real_ip = _normalize_ip(request.headers.get("X-Real-IP", ""))
    if real_ip:
        return real_ip

    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        for part in forwarded_for.split(","):
            candidate = _normalize_ip(part)
            if candidate:
                return candidate

    return direct_ip


def _normalize_ip(value: str) -> str:
    """Return canonical IP string, or empty if invalid."""
    candidate = (value or "").strip()
    if not candidate:
        return ""
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return ""


TRUST_PROXY_HEADERS = os.getenv("TRUST_PROXY_HEADERS", "false").strip().lower() in {"1", "true", "yes"}
_trusted_proxy_env = os.getenv("TRUSTED_PROXY_IPS", "").strip()
TRUSTED_PROXY_IPS = {
    normalized
    for normalized in (
        _normalize_ip(item)
        for item in _trusted_proxy_env.split(",")
    )
    if normalized
}


RATE_LIMIT_SYNC_PER_MINUTE = int(os.getenv("RATE_LIMIT_SYNC_PER_MINUTE", "6"))
RATE_LIMIT_SUMMARY_PER_MINUTE = int(os.getenv("RATE_LIMIT_SUMMARY_PER_MINUTE", "30"))
_rate_limiter_store = {}


def _resolve_session_token(request: Request) -> str:
    """Resolve session token from secure channels only (cookie or auth headers)."""
    cookie_token = request.cookies.get("session_token")
    if cookie_token and cookie_token.strip():
        return cookie_token.strip()

    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        bearer_token = auth_header[7:].strip()
        if bearer_token:
            return bearer_token

    header_token = request.headers.get("X-Session-Token", "")
    if header_token and header_token.strip():
        return header_token.strip()

    return ""


def _is_rate_limited(client_ip: str, scope: str, max_requests: int, window_seconds: int = 60) -> bool:
    """Simple in-memory sliding-window limiter to protect expensive endpoints."""
    now = time.monotonic()
    key = f"{client_ip}:{scope}"
    timestamps = _rate_limiter_store.get(key, [])
    valid_after = now - window_seconds
    timestamps = [ts for ts in timestamps if ts >= valid_after]
    limited = len(timestamps) >= max_requests
    if not limited:
        timestamps.append(now)
    _rate_limiter_store[key] = timestamps
    return limited


# Security Middleware - IP Blocking
@app.middleware("http")
async def security_middleware(request: Request, call_next):
    """
    Security middleware to block blacklisted IPs and log visitors
    Optimized for performance with minimal overhead
    """
    # Get real client IP (handle all proxy headers)
    client_ip = get_real_client_ip(request)
    
    # Continue processing request
    response = await call_next(request)
    
    # Add PWA and mobile-friendly headers
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    
    # Allow service worker and manifest to be cached
    if request.url.path in ["/service-worker.js", "/manifest.json"]:
        response.headers["Cache-Control"] = "public, max-age=0"
    
    return response


@app.middleware("http")
async def visitor_tracking_middleware(request: Request, call_next):
    """
    Separate middleware for visitor tracking and security checks
    """
    # Get real client IP (handle all proxy headers)
    client_ip = get_real_client_ip(request)
    
    # Allow admin portal access with correct key even if IP is blocked
    if request.url.path.startswith("/admin-portal"):
        admin_key = request.query_params.get("admin_key")
        if _is_valid_admin_key(admin_key):
            # Log the access and continue
            db.log_visitor(client_ip, f"Admin Portal Access (Bypassed Block)", request.headers.get("user-agent"), request.url.path)
            return await call_next(request)
    
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
    """
    Background worker that syncs lectures periodically.
    Only sends Telegram notifications for NEW lectures (not on every check).
    Uses notification tracking to prevent duplicate alerts on Render wake-up.
    """
    # Wait a bit before starting to let the server fully start
    await asyncio.sleep(5)
    logger.info("Background sync worker started. Checking for new lectures every %d seconds", SYNC_INTERVAL_SECONDS)
    
    while True:
        try:
            logger.info("Checking for new lectures...")
            added, files, new_item_ids, subject_map = await asyncio.to_thread(sync_once, auth_client, send_notifications=True)
            
            if new_item_ids:
                logger.info("✅ Synced %s new file(s), sending notifications for %s NEW items", added, len(new_item_ids))
                
                # Send Telegram notifications ONLY for items not yet notified
                try:
                    if len(new_item_ids) == 1 and files:
                        # Get subject for single lecture
                        subject = subject_map.get(new_item_ids[0], "بابەتی جیاواز")
                        sent_ok = notify_new_lecture(files[0], subject=subject, base_url=BASE_URL)
                        if sent_ok:
                            _mark_notified(new_item_ids[0])
                            logger.info(f"✅ Telegram notification sent for 1 lecture (ID: {new_item_ids[0]}, Subject: {subject})")
                        else:
                            logger.warning(f"⚠️ Telegram send failed for 1 lecture (ID: {new_item_ids[0]}, Subject: {subject})")
                    elif len(new_item_ids) > 1:
                        # Group lectures by subject
                        subjects_count = {}
                        for item_id in new_item_ids:
                            subject = subject_map.get(item_id, "بابەتی جیاواز")
                            subjects_count[subject] = subjects_count.get(subject, 0) + 1
                        
                        # Send notification for each subject with multiple lectures
                        all_sent_ok = True
                        for subject, count in subjects_count.items():
                            sent_ok = notify_multiple_lectures(count, subject=subject)
                            if sent_ok:
                                logger.info(f"✅ Telegram notification sent for {count} lectures in {subject}")
                            else:
                                all_sent_ok = False
                                logger.warning(f"⚠️ Telegram send failed for {count} lectures in {subject}")
                        
                        # Mark all as notified only if grouped send succeeded.
                        if all_sent_ok:
                            for item_id in new_item_ids:
                                _mark_notified(item_id)
                except Exception as e:
                    logger.error(f"❌ Failed to send Telegram notification: {e}")
            else:
                logger.info("[OK] No new lectures found")
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
async def manual_sync(request: Request) -> JSONResponse:
    """Trigger immediate sync (for testing)"""
    try:
        client_ip = get_real_client_ip(request)
        if _is_rate_limited(client_ip, "sync-now", RATE_LIMIT_SYNC_PER_MINUTE):
            return JSONResponse({
                "success": False,
                "error": "Too many sync requests. Please wait and try again."
            }, status_code=429)

        added, files, new_item_ids, subject_map = await asyncio.to_thread(sync_once, auth_client, send_notifications=True)
        
        # Send Telegram notifications ONLY for items that haven't been notified yet
        notifications_sent = 0
        notifications_failed = 0
        if new_item_ids:
            try:
                if len(new_item_ids) == 1 and files:
                    # Single lecture notification
                    subject = subject_map.get(new_item_ids[0], "بابەتی جیاواز")
                    sent_ok = notify_new_lecture(files[0], subject=subject, base_url=BASE_URL)
                    if sent_ok:
                        _mark_notified(new_item_ids[0])
                        notifications_sent = 1
                        logger.info(f"✅ Manual sync: Telegram sent for 1 lecture (ID: {new_item_ids[0]}, Subject: {subject})")
                    else:
                        notifications_failed = 1
                        logger.warning(f"⚠️ Manual sync: Telegram failed for 1 lecture (ID: {new_item_ids[0]}, Subject: {subject})")
                elif len(new_item_ids) > 1:
                    # Group lectures by subject
                    subjects_count = {}
                    for item_id in new_item_ids:
                        subject = subject_map.get(item_id, "بابەتی جیاواز")
                        subjects_count[subject] = subjects_count.get(subject, 0) + 1
                    
                    # Send notification for each subject with multiple lectures
                    all_sent_ok = True
                    for subject, count in subjects_count.items():
                        sent_ok = notify_multiple_lectures(count, subject=subject)
                        if sent_ok:
                            logger.info(f"✅ Manual sync: Telegram sent for {count} lectures in {subject}")
                        else:
                            all_sent_ok = False
                            logger.warning(f"⚠️ Manual sync: Telegram failed for {count} lectures in {subject}")
                    
                    # Mark all as notified only when grouped sends succeeded.
                    if all_sent_ok:
                        for item_id in new_item_ids:
                            _mark_notified(item_id)
                        notifications_sent = len(new_item_ids)
                    else:
                        notifications_failed = len(new_item_ids)
            except Exception as e:
                logger.error(f"❌ Manual sync: Failed to send Telegram notification: {e}")
                notifications_failed = len(new_item_ids)
        
        return JSONResponse({
            "success": True,
            "message": f"Synced {added} new file(s)",
            "files": [f.name for f in files],
            "new_item_ids": new_item_ids,
            "notifications_sent": notifications_sent,
            "notifications_failed": notifications_failed,
            "telegram": {
                "bot_token_set": bool((os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()),
                "target_id_set": bool((os.getenv("TELEGRAM_GROUP_ID") or os.getenv("TELEGRAM_CHAT_ID") or "").strip())
            }
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


@app.post("/api/telegram/test")
async def test_telegram_notification(request: Request, admin_key: str = "") -> JSONResponse:
    """Admin-only endpoint to send a Telegram test message immediately."""
    if not _is_valid_admin_key(admin_key):
        return JSONResponse({"success": False, "error": "Unauthorized"}, status_code=401)

    token_set = bool((os.getenv("TELEGRAM_BOT_TOKEN") or "").strip())
    target_set = bool((os.getenv("TELEGRAM_GROUP_ID") or os.getenv("TELEGRAM_CHAT_ID") or "").strip())

    ok = test_telegram_connection()
    if ok:
        return JSONResponse({
            "success": True,
            "message": "Telegram test sent successfully.",
            "config": {
                "bot_token_set": token_set,
                "target_id_set": target_set,
            },
        })

    return JSONResponse({
        "success": False,
        "error": "Telegram test failed. Check Render logs and bot/chat permissions.",
        "config": {
            "bot_token_set": token_set,
            "target_id_set": target_set,
        },
    }, status_code=500)


@app.post("/api/admin/upload-data")
async def upload_data(request: Request, package: bytes = None, admin_key: str = None, x_admin_key: str = Header(default=None)) -> JSONResponse:
    """Admin endpoint to upload database and files from local system"""
    import sqlite3
    import zipfile
    import tempfile
    import shutil
    from fastapi import File, UploadFile, Header
    
    effective_key = x_admin_key or admin_key
    if not _is_valid_admin_key(effective_key):
        return JSONResponse({
            "success": False,
            "error": "Unauthorized"
        }, status_code=401)
    
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


def _infer_subject_from_filename(filename: str):
    """Best-effort subject guess from the lecture filename.

    This is used when the sync database doesn't yet have a subject
    (for example, if the portal HTML changed or a fallback path ran).
    It tries to avoid putting files into the generic "Other" bucket
    when we can reasonably match them to a known subject.
    """
    name = filename.lower()

    subject_keywords = {
        "Data Communication": ["data communication"],
        "Database Design": ["database design", "db design"],
        "Numerical Analysis and Probability": ["numerical analysis", "probability"],
        "Object Oriented Programming": ["object oriented programming", "oop"],
        "Software Design and Modelling with UML": ["software design", "uml"],
        "Combinatorics and Graph Theory": ["combinatorics", "graph theory"],
        "Database Principles": ["database principles"],
        "Data Structures and Algorithms": ["data structures", "algorithms"],
        "Mathematics III": ["mathematics iii", "math iii", "math 3"],
        "Software Engineering Principles": ["software engineering"],
        "Introduction to OOP": ["introduction to oop", "intro to oop"],
    }

    for subject, keywords in subject_keywords.items():
        for kw in keywords:
            if kw in name:
                return subject
    return None


def _infer_semester_from_filename(filename: str) -> str:
    """Infer semester from filename when DB metadata is missing."""
    name = filename.lower()
    if "fall semester" in name or " fall " in f" {name} ":
        return "Fall Semester"
    if "spring semester" in name or " spring " in f" {name} ":
        return "Spring Semester"
    return ""


@app.get("/api/files")
async def list_files() -> JSONResponse:
    """List all files grouped by semester and subject"""
    import sqlite3
    from pathlib import Path

    files_by_semester = {}

    # Try to get subject, semester information and upload dates from database
    db_path = Path(__file__).parent / "data" / "lecture_sync.db"
    if db_path.exists():
        try:
            with sqlite3.connect(db_path) as conn:
                cursor = conn.execute("SELECT filename, subject, upload_date, semester FROM synced_items WHERE filename IS NOT NULL")
                db_info = {row[0]: {"subject": row[1], "upload_date": row[2], "semester": row[3]} for row in cursor.fetchall()}
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

                # Prefer subject from DB, otherwise try to infer from filename
                subject = file_db_info.get("subject")
                if not subject:
                    subject = _infer_subject_from_filename(path.name)
                if not subject:
                    subject = "Other"

                # Prefer semester from DB, otherwise derive from subject (if known)
                semester = file_db_info.get("semester")
                inferred_semester = _infer_semester_from_filename(path.name)
                if inferred_semester:
                    semester = inferred_semester
                if not semester:
                    if subject and subject != "Other":
                        try:
                            semester = _get_semester_from_subject(subject)
                        except Exception:
                            semester = "Spring Semester"
                    else:
                        semester = "Spring Semester"

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

                # Group by semester first, then by subject
                if semester not in files_by_semester:
                    files_by_semester[semester] = {}
                if subject not in files_by_semester[semester]:
                    files_by_semester[semester][subject] = []
                files_by_semester[semester][subject].append(file_info)

    logger.info(f"📊 API returning {len(files_by_semester)} semesters with total {sum(sum(len(files) for files in subjects.values()) for subjects in files_by_semester.values())} files")
    return JSONResponse(files_by_semester)


@app.get("/api/download/{filename}")
async def download_file(filename: str, request: Request, _: str = None):
    """
    Download a file with forced attachment headers - prevents preview and caching
    
    iOS Safari Fix: Forces download instead of preview
    - Uses application/octet-stream for PDFs to prevent Safari's inline viewer
    - Adds X-Content-Type-Options to prevent MIME sniffing
    - Multiple Content-Disposition formats for maximum compatibility
    
    Note: Safari may still open PDFs if user taps "Open in..." after download
    This is iOS behavior and cannot be prevented server-side.
    """
    from fastapi.responses import FileResponse
    import urllib.parse
    import os
    
    safe_filename = Path(filename).name
    base_dir = DOWNLOAD_DIR.resolve()
    file_path = (DOWNLOAD_DIR / safe_filename).resolve()

    if base_dir not in file_path.parents:
        raise HTTPException(status_code=400, detail="Invalid filename")

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    
    # Get file size for Content-Length
    file_size = os.path.getsize(file_path)
    
    # URL encode filename for proper header
    encoded_filename = urllib.parse.quote(safe_filename)
    
    # Detect if request is from iOS Safari (enhanced detection)
    user_agent = request.headers.get("User-Agent", "").lower()
    is_ios = "iphone" in user_agent or "ipad" in user_agent or "ipod" in user_agent
    is_safari = "safari" in user_agent and "chrome" not in user_agent and "crios" not in user_agent
    is_ios_safari = is_ios and is_safari
    
    # iOS SAFARI FIX: Force download by always using octet-stream for PDFs on iOS
    # Safari's PDF viewer cannot be bypassed reliably, so we force binary download
    if safe_filename.lower().endswith('.pdf'):
        if is_ios:
            # Force download on ALL iOS browsers (Safari, Chrome, Firefox on iOS)
            content_type = 'application/octet-stream'
            logger.info(f"iOS device detected - forcing PDF download for {safe_filename}")
        else:
            content_type = 'application/pdf'  # Normal behavior for other platforms
    else:
        content_type = 'application/octet-stream'
    
    return FileResponse(
        path=file_path,
        filename=safe_filename,
        media_type=content_type,
        headers={
            # Multiple Content-Disposition formats for maximum compatibility
            'Content-Disposition': f'attachment; filename="{safe_filename}"; filename*=UTF-8\'\'{encoded_filename}',
            'Content-Type': content_type,
            'Content-Length': str(file_size),
            
            # Prevent MIME sniffing (iOS may try to detect PDF and show preview)
            'X-Content-Type-Options': 'nosniff',
            
            # Force no caching - critical for iOS
            'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0, private',
            'Pragma': 'no-cache',
            'Expires': '0',
            
            # iOS-specific: Prevent inline viewing and force download
            'Content-Transfer-Encoding': 'binary',
            'X-Download-Options': 'noopen',  # IE/Edge specific
            'X-Frame-Options': 'DENY'  # Prevent embedding in iframe
        }
    )


@app.post("/api/summarize")
async def summarize_lecture(request: Request, filename: str) -> JSONResponse:
    """
    Summarize a single lecture PDF
    
    Query params:
        filename: Name of the PDF file to summarize
    """
    try:
        client_ip = get_real_client_ip(request)
        if _is_rate_limited(client_ip, "summarize-single", RATE_LIMIT_SUMMARY_PER_MINUTE):
            return JSONResponse({
                "success": False,
                "error": "Too many summarize requests. Please wait and try again."
            }, status_code=429)

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
async def summarize_subject(request: Request, subject: str) -> JSONResponse:
    """
    Summarize all lectures in a subject
    
    Query params:
        subject: Name of the subject
    """
    try:
        client_ip = get_real_client_ip(request)
        if _is_rate_limited(client_ip, "summarize-all", RATE_LIMIT_SUMMARY_PER_MINUTE):
            return JSONResponse({
                "success": False,
                "error": "Too many summarize requests. Please wait and try again."
            }, status_code=429)

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
async def attendance_login(request: Request) -> JSONResponse:
    """
    Authenticate user for attendance access
    Creates a secure session token
    
    Android Fix: Sets HTTP cookie with SameSite=Lax (Android-safe)
    - SameSite=None requires Secure flag and breaks on some Android browsers
    - SameSite=Lax works across all browsers while maintaining security
    - Cookie persists across page refreshes and browser restarts
    """
    username = ""
    try:
        payload = {}
        try:
            payload = await request.json()
        except Exception:
            payload = {}

        username = str(payload.get("username", "")).strip()
        password = str(payload.get("password", ""))
        remember_me = bool(payload.get("remember_me", False))

        # Get real client IP
        client_ip = get_real_client_ip(request)
        user_agent = request.headers.get("User-Agent", "Unknown")
        
        # Validate credentials
        if not username or not password:
            return JSONResponse({
                "success": False,
                "error": "Username and password are required"
            }, status_code=400)
        
        result = await attendance_service.authenticate_user(username, password)
        
        if result['success']:
            # Log successful attendance login with student info
            student_display = result.get('username', username)
            db.log_visitor(
                client_ip, 
                f"Attendance Login: {student_display}",
                user_agent,
                "/api/attendance/login",
                username=student_display
            )
            logger.info(f"✅ Attendance login successful: {student_display} from IP {client_ip}")
            
            # Create response with session data
            response = JSONResponse({
                "success": True,
                "student_id": result['student_id'],
                "username": result['username'],
                # Fallback token for clients where cookie persistence is delayed/restricted.
                "session_token": result.get('session_token', '')
            })

            # Browsers reject Secure cookies on http://localhost.
            is_secure_request = request.url.scheme == "https"
            cookie_max_age = 7 * 24 * 60 * 60 if remember_me else 60 * 60
            
            # ANDROID FIX: Set HTTP cookie for session persistence
            # Using explicit cookie settings for maximum Android compatibility
            response.set_cookie(
                key="session_token",
                value=result['session_token'],
                max_age=cookie_max_age,
                path="/",
                domain=None,  # Prevents subdomain mismatch issues
                secure=is_secure_request,
                httponly=True,  # Security: Prevent XSS attacks
                samesite="lax"  # Safer default for same-site app flows
            )
            
            return response
        else:
            error_msg = result.get('error', 'Authentication failed')
            # Log failed login attempt
            db.log_visitor(
                client_ip,
                f"Failed Attendance Login: {username}",
                user_agent,
                "/api/attendance/login",
                username=username
            )
            logger.error(f"❌ Authentication failed for {username} from IP {client_ip}: {error_msg}")
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
async def get_attendance(request: Request) -> JSONResponse:
    """
    Fetch attendance data for authenticated user
    Requires valid session token from login
    
    Android Fix: Uses HttpOnly cookie for session persistence
    """
    try:
        session_token = _resolve_session_token(request)
        
        if not session_token or session_token.strip() == "":
            return JSONResponse({
                "success": False,
                "error": "Session token required"
            }, status_code=401)
        
        client_ip = get_real_client_ip(request)
        logger.info("Fetching attendance for authenticated session from IP: %s", client_ip)
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
async def get_profile(request: Request) -> JSONResponse:
    """
    Fetch student profile (name)
    
    Android Fix: Uses HttpOnly cookie for session persistence
    """
    try:
        session_token = _resolve_session_token(request)
        
        if not session_token or session_token.strip() == "":
            return JSONResponse({
                "success": False,
                "error": "Session token required"
            }, status_code=401)
        
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


@app.get("/api/results/data")
async def get_results(request: Request) -> JSONResponse:
    """
    Fetch results data for authenticated user
    Uses notification API as source for results
    Requires valid session token from attendance login
    
    Android Fix: Uses HttpOnly cookie for session persistence
    """
    try:
        session_token = _resolve_session_token(request)
        
        if not session_token or session_token.strip() == "":
            return JSONResponse({
                "success": False,
                "error": "Session token required. Please login first."
            }, status_code=401)
        
        client_ip = get_real_client_ip(request)
        logger.info("Fetching results for authenticated session from IP: %s", client_ip)
        
        # Use attendance service's session manager to validate session
        result = await results_service.get_results(session_token, attendance_service.session_manager)
        logger.info("Results fetch: success=%s, count=%s", result.get('success'), result.get('total_count', 0))
        
        if result['success']:
            return JSONResponse({
                "success": True,
                "results": result['results'],
                "total_count": result.get('total_count', 0)
            })
        else:
            error_msg = result.get('error', 'Failed to fetch results')
            if 'expired' in error_msg.lower():
                return JSONResponse({
                    "success": False,
                    "error": error_msg,
                    "results": []
                }, status_code=401)
            return JSONResponse({
                "success": True,
                "results": [],
                "total_count": 0,
                "warning": error_msg
            })
    
    except Exception as exc:
        logger.exception("Error fetching results data: %s", str(exc))
        return JSONResponse({
            "success": False,
            "error": f"Error fetching results: {str(exc)}",
            "results": []
        }, status_code=500)


@app.get("/api/official-results/data")
async def get_official_results(request: Request) -> JSONResponse:
    """
    Fetch official results from StudentResult endpoint for authenticated user
    Uses official StudentResult/List API endpoint
    Requires valid session token from attendance login
    
    Security: Only returns results for the authenticated student's ID
    Android Fix: Uses HttpOnly cookie for session persistence
    """
    try:
        session_token = _resolve_session_token(request)
        
        if not session_token or session_token.strip() == "":
            return JSONResponse({
                "success": False,
                "error": "Session token required. Please login first."
            }, status_code=401)
        
        client_ip = get_real_client_ip(request)
        logger.info("Fetching official results for authenticated session from IP: %s", client_ip)
        
        # Validate session using attendance service's session manager
        session = attendance_service.session_manager.get_session(session_token)
        
        if not session:
            return JSONResponse({
                "success": False,
                "error": "Session expired or invalid. Please login again."
            }, status_code=401)
        
        # Get student ID from session (this is the authenticated user's ID)
        student_id = session.get('student_id', '')
        cookies = session.get('cookies', {})
        
        if not student_id:
            return JSONResponse({
                "success": False,
                "error": "Student ID not found in session."
            }, status_code=400)
        
        # Sanitize student_id to prevent injection
        student_id = str(student_id).strip()
        if not student_id.isalnum() and not all(c.isalnum() or c in ['-', '_'] for c in student_id):
            return JSONResponse({
                "success": False,
                "error": "Invalid student ID format."
            }, status_code=400)
        
        logger.info("Fetching official results for student ID: %s", student_id)

        cached_official = _get_cached_official_results(student_id)
        
        # Fetch results from official endpoint
        official_endpoint = f"https://tempapp-su.awrosoft.com/University/StudentResult/List?studentId={student_id}"
        
        def fetch_official_results():
            """Fetch official results from StudentResult endpoint"""
            try:
                response = requests.get(
                    official_endpoint,
                    cookies=cookies,
                    timeout=15,
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                        'Accept': 'application/json, text/html, */*',
                        'Referer': 'https://tempapp-su.awrosoft.com/'
                    }
                )
                
                if response.status_code == 401:
                    return {
                        'success': False,
                        'error': 'Unauthorized. Session may have expired.',
                        'results': []
                    }

                if response.status_code != 200:
                    return {
                        'success': False,
                        'error': f'Failed to fetch results. Status code: {response.status_code}',
                        'results': []
                    }
                # Parse response (HTML or JSON)
                try:
                    content_type = response.headers.get('Content-Type', '')
                    response_text = response.text
                    
                    # Log response details for debugging
                    logger.info(f"Response Content-Type: {content_type}")
                    logger.info(f"Response length: {len(response_text)} bytes")
                    
                    # Check if response is HTML (the API returns HTML formatted results)
                    if 'text/html' in content_type or response_text.strip().startswith('<'):
                        logger.info("Received HTML response - parsing HTML results")
                        
                        # Parse HTML to extract results
                        soup = BeautifulSoup(response_text, 'html.parser')
                        
                        # Find all result cards (each card = one semester)
                        result_cards = soup.find_all('div', class_='card')
                        results = []
                        best_by_key = {}  # (year, semester, title_lower) -> result dict
                        
                        for card in result_cards:
                            try:
                                # Extract header info (Academic Year and Semester)
                                card_header = card.find('div', class_='card-header')
                                if not card_header:
                                    continue
                                    
                                header_text = card_header.get_text(strip=True)
                                logger.info(f"Parsing card header: {header_text}")
                                
                                # Parse header to extract academic year and semester
                                # Common formats:
                                # - "Result of 2025"
                                # - "2024-2025 Fall Semester"  
                                # - "2024-2025 - Fall Semester"
                                # - "Spring Semester 2024-2025"
                                # IMPORTANT: Do not default to a specific semester/year.
                                # If parsing fails, we will preserve the portal's raw header label to avoid mis-grouping.
                                academic_year = ""
                                semester_name = ""
                                semester_label = (header_text or '').strip()
                                
                                if header_text:
                                    import re
                                    
                                    # Extract year pattern (2024-2025 or just 2025)
                                    year_pattern = re.search(r'(\d{4})\s*-?\s*(\d{4})', header_text)
                                    if year_pattern:
                                        academic_year = f"{year_pattern.group(1)}-{year_pattern.group(2)}"
                                    elif 'result of' in header_text.lower():
                                        # Handle "Result of 2025" format
                                        single_year_match = re.search(r'result\s+of\s+(\d{4})', header_text, re.IGNORECASE)
                                        if single_year_match:
                                            year = int(single_year_match.group(1))
                                            academic_year = f"{year-1}-{year}"

                                    # If year wasn't found in the header, try to infer it from nearby/parent elements
                                    if not academic_year:
                                        try:
                                            yr_re = re.compile(r'(\d{4})\s*[-–]\s*(\d{4})')
                                            # Search closest ancestors first (accordion headers often live there)
                                            parent = card
                                            for _ in range(6):
                                                if not parent:
                                                    break
                                                parent = parent.parent
                                                if not parent or not hasattr(parent, 'get_text'):
                                                    continue
                                                parent_text = parent.get_text(' ', strip=True)
                                                m = yr_re.search(parent_text or '')
                                                if m:
                                                    academic_year = f"{m.group(1)}-{m.group(2)}"
                                                    break
                                        except Exception:
                                            pass
                                    
                                    # Extract semester name (handle common English/Arabic/Kurdish variants)
                                    ht_lower = header_text.lower()

                                    # English seasons
                                    if 'fall' in ht_lower:
                                        semester_name = "Fall Semester"
                                    elif 'spring' in ht_lower:
                                        semester_name = "Spring Semester"
                                    elif 'summer' in ht_lower:
                                        semester_name = "Summer Semester"

                                    # Arabic seasons
                                    elif 'خريف' in header_text or 'الخريف' in header_text:
                                        semester_name = "Fall Semester"
                                    elif 'ربيع' in header_text or 'الربيع' in header_text:
                                        semester_name = "Spring Semester"
                                    elif 'صيف' in header_text or 'الصيف' in header_text:
                                        semester_name = "Summer Semester"

                                    # Kurdish seasons (best-effort)
                                    elif 'خەزان' in header_text:
                                        semester_name = "Fall Semester"
                                    elif 'بەهار' in header_text:
                                        semester_name = "Spring Semester"
                                    elif 'هاوین' in header_text:
                                        semester_name = "Summer Semester"

                                    # Generic semester numbering (do NOT translate to fall/spring unless explicitly stated)
                                    elif re.search(r'\b(1st|first)\s+semester\b', ht_lower) or 'الفصل الأول' in header_text or 'الفصل الاول' in header_text or 'وەرزی یەکەم' in header_text:
                                        semester_name = "First Semester"
                                    elif re.search(r'\b(2nd|second)\s+semester\b', ht_lower) or 'الفصل الثاني' in header_text or 'الفصل الثانى' in header_text or 'وەرزی دووەم' in header_text:
                                        semester_name = "Second Semester"
                                    elif re.search(r'\bsemester\s*(1|one)\b', ht_lower):
                                        semester_name = "First Semester"
                                    elif re.search(r'\bsemester\s*(2|two)\b', ht_lower):
                                        semester_name = "Second Semester"

                                    # If semester still unknown, scan the whole card text (some headers are year-only: "Result of2024-2025")
                                    if not semester_name:
                                        try:
                                            card_text = card.get_text(' ', strip=True)
                                            card_lower = (card_text or '').lower()

                                            # Only infer semester from body text when it is unambiguous.
                                            # Some portal cards include BOTH fall and spring in the same card (year-only header).
                                            # In that case, guessing would duplicate subjects across semesters.
                                            detected = []

                                            fall_hit = ('fall' in card_lower) or ('خريف' in card_text) or ('الخريف' in card_text) or ('خەزان' in card_text)
                                            spring_hit = ('spring' in card_lower) or ('ربيع' in card_text) or ('الربيع' in card_text) or ('بەهار' in card_text)
                                            summer_hit = ('summer' in card_lower) or ('صيف' in card_text) or ('الصيف' in card_text) or ('هاوین' in card_text)

                                            first_hit = bool(re.search(r'\b(1st|first)\s+semester\b', card_lower)) or ('الفصل الأول' in card_text) or ('الفصل الاول' in card_text) or ('وەرزی یەکەم' in card_text)
                                            second_hit = bool(re.search(r'\b(2nd|second)\s+semester\b', card_lower)) or ('الفصل الثاني' in card_text) or ('الفصل الثانى' in card_text) or ('وەرزی دووەم' in card_text)

                                            if fall_hit:
                                                detected.append('fall')
                                            if spring_hit:
                                                detected.append('spring')
                                            if summer_hit:
                                                detected.append('summer')
                                            if first_hit:
                                                detected.append('first')
                                            if second_hit:
                                                detected.append('second')

                                            # If exactly one semester type is present, map it.
                                            if len(detected) == 1:
                                                one = detected[0]
                                                if one == 'fall':
                                                    semester_name = "Fall Semester"
                                                elif one == 'spring':
                                                    semester_name = "Spring Semester"
                                                elif one == 'summer':
                                                    semester_name = "Summer Semester"
                                                elif one == 'first':
                                                    semester_name = "First Semester"
                                                elif one == 'second':
                                                    semester_name = "Second Semester"
                                        except Exception:
                                            pass
                                    
                                # If semester name couldn't be parsed, do NOT fall back to year-only labels.
                                # We prefer skipping/marking unknown rather than mis-grouping.
                                if not semester_name:
                                    semester_name = "Unknown Semester"

                                logger.info(f"Detected: {academic_year} - {semester_name}")
                                
                                # Extract table data
                                table = card.find('table')
                                if not table:
                                    logger.warning(f"No table found in card with header: {header_text}")
                                    continue

                                import re

                                _grade_tokens = [
                                    # English
                                    'accept', 'excellent', 'verygood', 'very good', 'good', 'medium', 'weak',
                                    'pass', 'fail', 'pending', 'not marked', 'not marked yet',
                                    # Arabic / Kurdish common labels
                                    'ناجح', 'راسب', 'مقبول', 'جيد', 'جيد جدا', 'ممتاز', 'قيد الانتظار', 'غير مصحح'
                                ]
                                _grade_re = re.compile(r'(' + '|'.join(re.escape(t) for t in _grade_tokens) + r')', re.IGNORECASE)

                                def _extract_grade_token(text: str) -> str:
                                    m = _grade_re.search((text or '').strip())
                                    return m.group(1).strip() if m else ''

                                def _extract_last_number(text: str) -> str:
                                    nums = re.findall(r'\d+(?:\.\d+)?', (text or '').strip())
                                    return nums[-1] if nums else ''

                                def _parse_portal_summary_cell(cell) -> tuple[str, str]:
                                    """Return (total_grade_number, status_label) from the nested summary tables."""
                                    if cell is None:
                                        return ('', '')

                                    # The portal renders a mini-table like:
                                    # headers: Continuous Exam | Total
                                    # row:     31.5           | VeryGood
                                    nested_tables = cell.find_all('table')
                                    for nt in nested_tables:
                                        # Read all rows and look for a grade token in any cell.
                                        for tr in nt.find_all('tr'):
                                            tds = tr.find_all(['td', 'th'])
                                            if len(tds) < 2:
                                                continue
                                            texts = [td.get_text(' ', strip=True) for td in tds]
                                            joined = ' '.join(texts)
                                            grade = _extract_grade_token(joined)
                                            if not grade:
                                                continue
                                            # Prefer a number from the same row
                                            num = ''
                                            for tx in texts:
                                                num = _extract_last_number(tx)
                                                if num:
                                                    break
                                            return (num, grade)

                                    # Fallback: scan the whole cell text
                                    cell_text = cell.get_text(' ', strip=True)
                                    return (_extract_last_number(cell_text), _extract_grade_token(cell_text))

                                def _is_non_subject_title(title: str) -> bool:
                                    t = (title or '').strip().lower()
                                    if not t:
                                        return True
                                    # Obvious non-subject/assessment lines
                                    bad_tokens = [
                                        'total', 'sum', 'subtotal', 'overall', 'result',
                                        'quiz', 'mid term', 'midterm', 'activity', 'assignment', 'report',
                                        'presentation', 'seminar', 'practical', 'lab', 'project',
                                        'hw', 'homework', 'home work',
                                        'exam', 'normal exam'
                                    ]
                                    if any(tok in t for tok in bad_tokens):
                                        return True
                                    if any(tok in t for tok in ['المجموع', 'مجموع', 'الكلي', 'كۆی', 'کۆی گشتی', 'جمع']):
                                        return True
                                    # If the title itself is only a grade token
                                    if _grade_re.fullmatch((title or '').strip()):
                                        return True
                                    return False

                                # ===== Preferred parsing path (matches the portal UI) =====
                                # Table columns often are: Title | Credit | Continuous Exams Summary (nested mini-table)
                                # We will parse each <tr> structurally to avoid confusing credit/rowspan.
                                # Try to detect the Title column from the table header (some portals include a Code column first).
                                title_col_idx = None
                                try:
                                    header_tr = None
                                    thead = table.find('thead')
                                    if thead:
                                        header_tr = thead.find('tr')
                                    if not header_tr:
                                        # Fallback: first row containing <th>
                                        for _tr in table.find_all('tr'):
                                            if _tr.find('th'):
                                                header_tr = _tr
                                                break
                                    if header_tr:
                                        header_cells = header_tr.find_all(['th', 'td'])
                                        header_texts = [c.get_text(' ', strip=True).lower() for c in header_cells]
                                        for i, ht in enumerate(header_texts):
                                            if any(tok in ht for tok in ['title', 'course title', 'subject', 'المادة', 'المقرر', 'ناونیشان', 'ناوی']):
                                                title_col_idx = i
                                                break
                                except Exception:
                                    title_col_idx = None

                                body_rows = []
                                tbody = table.find('tbody')
                                if tbody:
                                    body_rows = tbody.find_all('tr', recursive=False) or tbody.find_all('tr')
                                else:
                                    # fallback: all trs excluding header
                                    body_rows = table.find_all('tr')
                                    if body_rows and body_rows[0].find('th'):
                                        body_rows = body_rows[1:]

                                parsed_any_structured = False
                                for tr in body_rows:
                                    tds = tr.find_all('td', recursive=False) or tr.find_all('td')
                                    if not tds:
                                        continue

                                    # Title column (header-driven when possible; otherwise heuristics)
                                    subject_title = ''
                                    if title_col_idx is not None and 0 <= title_col_idx < len(tds):
                                        subject_title = tds[title_col_idx].get_text(' ', strip=True)
                                    else:
                                        # Heuristic: choose the first cell that contains letters (not pure numeric code)
                                        cell_texts = [td.get_text(' ', strip=True) for td in tds]
                                        for tx in cell_texts:
                                            if tx and any(ch.isalpha() for ch in tx):
                                                subject_title = tx
                                                break
                                        if not subject_title and cell_texts:
                                            subject_title = cell_texts[0]

                                    subject_title = (subject_title or '').strip()
                                    # If the "title" is actually a code like 0108/5105, try another cell
                                    if re.fullmatch(r'\d{3,}', subject_title):
                                        for td in tds:
                                            tx = td.get_text(' ', strip=True).strip()
                                            if tx and any(ch.isalpha() for ch in tx):
                                                subject_title = tx
                                                break

                                    # Still numeric? skip (not a subject name row)
                                    if re.fullmatch(r'\d{3,}', subject_title or ''):
                                        continue

                                    if _is_non_subject_title(subject_title):
                                        continue

                                    # Summary cell is usually the last column
                                    summary_cell = tds[-1]
                                    total_num, grade_label = _parse_portal_summary_cell(summary_cell)
                                    if not grade_label:
                                        # If it doesn't carry a final label, don't show it.
                                        continue

                                    # If numeric total is missing, keep '-' (portal sometimes shows only label)
                                    if not total_num:
                                        total_num = '-'

                                    results.append({
                                        'AcademicYear': academic_year,
                                        'SemesterName': semester_name,
                                        'SemesterLabel': semester_label,
                                        'SubjectName': subject_title,
                                        'ContinuousSummary': total_num,
                                        'Title': subject_title,
                                        'TotalGrade': total_num,
                                        'Status': grade_label,
                                        'StudentId': student_id,
                                    })
                                    # De-duplicate within same year+semester for identical titles (avoid duplicates)
                                    try:
                                        t_norm = (subject_title or '').strip().lower()
                                        if t_norm and 'retake' not in t_norm and 'اعادة' not in t_norm and 'إعادة' not in t_norm:
                                            k = (academic_year or '', semester_name or '', t_norm)
                                            new_row = results[-1]
                                            existing = best_by_key.get(k)
                                            if existing is None:
                                                best_by_key[k] = new_row
                                            else:
                                                # Prefer rows with numeric TotalGrade and non-empty Status
                                                def _score(row):
                                                    tg = str(row.get('TotalGrade', '')).strip()
                                                    st = str(row.get('Status', '')).strip()
                                                    has_num = 1 if re.fullmatch(r'\d+(?:\.\d+)?', tg) else 0
                                                    has_status = 1 if st and st != '-' else 0
                                                    return (has_num, has_status, float(tg) if has_num else -1.0)
                                                if _score(new_row) > _score(existing):
                                                    best_by_key[k] = new_row
                                    except Exception:
                                        pass
                                    parsed_any_structured = True

                                # If we successfully parsed the table in structured mode, do not fall back to heuristics.
                                if parsed_any_structured:
                                    continue

                                def _cell_value(cell) -> str:
                                    """Best-effort text extraction for cells that may be icon-only."""
                                    if cell is None:
                                        return ''
                                    text = cell.get_text(' ', strip=True)
                                    if text:
                                        return text
                                    for attr in ('title', 'aria-label', 'data-original-title', 'data-title'):
                                        v = cell.get(attr)
                                        if v and str(v).strip():
                                            return str(v).strip()
                                    inner_with_title = cell.find(attrs={'title': True})
                                    if inner_with_title:
                                        v = inner_with_title.get('title')
                                        if v and str(v).strip():
                                            return str(v).strip()
                                    return ''

                                def _safe_int(value, default=1):
                                    try:
                                        return int(str(value))
                                    except Exception:
                                        return default

                                def _expand_rows_with_spans(trs):
                                    """Expand a list of <tr> into a grid of strings, honoring rowspan/colspan."""
                                    grid = []
                                    spans = {}  # col_index -> [remaining_rows, text]

                                    for tr in trs:
                                        row = []
                                        col = 0

                                        def _fill_spans_until_free():
                                            nonlocal col
                                            while col in spans:
                                                remaining, val = spans[col]
                                                row.append(val)
                                                remaining -= 1
                                                if remaining <= 0:
                                                    del spans[col]
                                                else:
                                                    spans[col] = [remaining, val]
                                                col += 1

                                        _fill_spans_until_free()

                                        cells = tr.find_all(['td', 'th'], recursive=False)
                                        if not cells:
                                            cells = tr.find_all(['td', 'th'])

                                        for cell in cells:
                                            _fill_spans_until_free()
                                            text = _cell_value(cell)
                                            rowspan = _safe_int(cell.get('rowspan'), 1)
                                            colspan = _safe_int(cell.get('colspan'), 1)

                                            for _ in range(max(1, colspan)):
                                                row.append(text)
                                                if rowspan and rowspan > 1:
                                                    spans[col] = [rowspan - 1, text]
                                                col += 1

                                        # Fill trailing spans that appear after the last explicit cell
                                        _fill_spans_until_free()
                                        if any((c or '').strip() for c in row):
                                            grid.append(row)

                                    return grid

                                # Determine column indices based on header labels (college system table)
                                header_row = None
                                thead = table.find('thead')
                                if thead:
                                    header_row = thead.find('tr')
                                if not header_row:
                                    # Fallback: first row that contains <th>
                                    for tr in table.find_all('tr'):
                                        if tr.find('th'):
                                            header_row = tr
                                            break

                                headers = []
                                if header_row:
                                    headers = [th.get_text(' ', strip=True) for th in header_row.find_all(['th', 'td'])]

                                # Log header labels (shape inspection) without logging student data rows
                                if headers:
                                    logger.info("Official results table headers: %s", headers)

                                def _norm_header(text: str) -> str:
                                    import re
                                    return re.sub(r'\s+', ' ', (text or '').strip().lower())

                                idx_subject = None
                                idx_grade = None
                                idx_cont_summary = None
                                idx_total = None
                                idx_status = None

                                # Build an index map using common English/Arabic/Kurdish tokens
                                for i, h in enumerate(headers):
                                    hn = _norm_header(h)
                                    # Subject name / course title
                                    if idx_subject is None and any(tok in hn for tok in ['course title', 'course', 'subject', 'title', 'ناونیشان', 'ناوی', 'المادة', 'المقرر']):
                                        idx_subject = i

                                    # Grade / evaluation label (often contains Accept/Excellent/Medium)
                                    if idx_grade is None and any(tok in hn for tok in ['grade', 'evaluation', 'result', 'التقدير', 'الدرجة', 'درجة', 'پۆل', 'پلە', 'نمرە']):
                                        idx_grade = i

                                    # Continuous Exams Summary (prefer explicit continuous/summary labels)
                                    if idx_cont_summary is None and any(tok in hn for tok in ['continuous exam', 'continuous exams', 'continuous exam', 'continuous', 'continous', 'summary', 'continuous exams summary', 'تقييم مستمر', 'الامتحانات المستمرة', 'خولاو', 'چالاکی']):
                                        idx_cont_summary = i

                                    # If no explicit continuous summary exists, allow points/score as a fallback (NOT total label)
                                    if idx_cont_summary is None and any(tok in hn for tok in ['points', 'point', 'score', 'النقاط']):
                                        idx_cont_summary = i

                                    # Final numeric total (do NOT confuse with Status)
                                    if idx_total is None and any(tok in hn for tok in ['total', 'overall', 'المجموع', 'المجموع الكلي', 'المجموع الكلي', 'الكلي', 'كۆی', 'کۆی گشتی', 'جمع']):
                                        idx_total = i

                                    # Status / state label
                                    if idx_status is None and any(tok in hn for tok in ['status', 'state', 'الحالة', 'حالة', 'بار', 'دۆخ']):
                                        idx_status = i

                                # Identify data rows and expand rowspan/colspan to prevent column shifts
                                all_trs = table.find_all('tr')
                                data_trs = []
                                if header_row and header_row in all_trs:
                                    header_index = all_trs.index(header_row)
                                    data_trs = all_trs[header_index + 1:]
                                else:
                                    data_trs = all_trs
                                    if data_trs and data_trs[0].find('th'):
                                        data_trs = data_trs[1:]

                                grid = _expand_rows_with_spans(data_trs)

                                def _get_cell(row, idx):
                                    if idx is None:
                                        return ''
                                    if idx < 0:
                                        return ''
                                    return row[idx] if idx < len(row) else ''

                                # If headers are missing, infer common column layout from data width
                                if not headers and grid:
                                    width = max(len(r) for r in grid)
                                    # Common layouts:
                                    # 4 cols: COURSE | GRADE | TOTAL | STATUS
                                    # 5 cols: NO | COURSE | GRADE | TOTAL | STATUS
                                    if width == 4:
                                        idx_subject, idx_grade, idx_total, idx_status = 0, 1, 2, 3
                                        idx_cont_summary = idx_cont_summary if idx_cont_summary is not None else 2
                                    elif width >= 5:
                                        idx_subject, idx_grade, idx_total, idx_status = 1, 2, 3, 4
                                        idx_cont_summary = idx_cont_summary if idx_cont_summary is not None else 3
                                    else:
                                        idx_subject = 0
                                        idx_total = max(0, width - 1)
                                        idx_cont_summary = idx_cont_summary if idx_cont_summary is not None else idx_total
                                        idx_status = idx_status if idx_status is not None else max(0, width - 1)

                                # If some indices weren't detected, assume the standard order
                                # Standard order commonly seen: NO | COURSE TITLE | GRADE | POINTS | STATUS
                                if idx_subject is None and headers and len(headers) >= 2:
                                    idx_subject = 1
                                if idx_grade is None and headers and len(headers) >= 3:
                                    idx_grade = 2
                                if idx_total is None and headers and len(headers) >= 4:
                                    idx_total = 3
                                if idx_status is None and headers and len(headers) >= 5:
                                    idx_status = 4
                                if idx_cont_summary is None:
                                    idx_cont_summary = idx_total

                                # Heuristic guard: subject column should not be mostly numeric
                                if grid and idx_subject is not None:
                                    import re
                                    sample = grid[: min(12, len(grid))]
                                    subj_values = [(_get_cell(r, idx_subject) or '').strip() for r in sample]
                                    numeric_like = sum(1 for v in subj_values if re.fullmatch(r'\d+(?:\.\d+)?', v or ''))
                                    if numeric_like >= max(2, len(subj_values) // 2):
                                        best_idx = idx_subject
                                        best_score = -10**9
                                        max_cols = max(len(r) for r in sample)
                                        for ci in range(max_cols):
                                            vals = [(_get_cell(r, ci) or '').strip() for r in sample]
                                            alpha = sum(1 for v in vals if any(ch.isalpha() for ch in v))
                                            num = sum(1 for v in vals if re.fullmatch(r'\d+(?:\.\d+)?', v or ''))
                                            score = alpha - (2 * num)
                                            if score > best_score:
                                                best_score = score
                                                best_idx = ci
                                        idx_subject = best_idx

                                logger.info(f"Found {len(grid)} result rows in semester: {header_text}")

                                for row in grid:
                                    subject_name = (_get_cell(row, idx_subject) or '').strip()
                                    cont_summary = (_get_cell(row, idx_cont_summary) or '').strip()
                                    total_text = (_get_cell(row, idx_total) or '').strip()
                                    status_text = (_get_cell(row, idx_status) or '').strip()
                                    grade_text = (_get_cell(row, idx_grade) or '').strip()

                                    # Skip empty rows
                                    if not subject_name or subject_name == '-':
                                        continue
                                    # Subject should not be pure numeric; if it is, skip (rowspan expansion should prevent this)
                                    if re.fullmatch(r'\d+(?:\.\d+)?', subject_name):
                                        continue

                                    def _last_number(text: str) -> str:
                                        nums = re.findall(r'\d+(?:\.\d+)?', (text or '').strip())
                                        return nums[-1] if nums else ''

                                    # Prefer the explicit Total column (if present), otherwise fall back to continuous/points
                                    total_clean = _last_number(total_text)
                                    cont_summary_clean = _last_number(cont_summary)

                                    if not total_clean:
                                        total_clean = cont_summary_clean

                                    if not total_clean:
                                        total_clean = "-"

                                    # If we still don't have a plausible numeric total, try to infer from the row
                                    if total_clean in ["-", "0"]:
                                        all_nums = []
                                        for cell_text in row:
                                            for n in re.findall(r'\d+(?:\.\d+)?', (cell_text or '')):
                                                try:
                                                    all_nums.append(float(n))
                                                except Exception:
                                                    pass
                                        # Avoid credits like 5/6; continuous exam scores tend to be >= 10
                                        candidates = [n for n in all_nums if n >= 10]
                                        if candidates:
                                            total_clean = str(candidates[-1]).rstrip('0').rstrip('.')
                                        else:
                                            total_clean = "-"

                                    # Status: prefer explicit Status column; if empty, fall back to non-numeric Grade labels
                                    status_clean = (status_text or '').strip()
                                    # Guard: status should not be numeric (numeric values belong to total/summary columns)
                                    if status_clean and re.fullmatch(r'\d+(?:\.\d+)?', status_clean):
                                        status_clean = ''
                                    if not status_clean:
                                        # Many portal tables put Accept/Excellent/Medium/etc under Grade
                                        if grade_text and not re.fullmatch(r'\d+(?:\.\d+)?', grade_text):
                                            status_clean = grade_text.strip()

                                    # If still empty, scan other cells for grade-like tokens (handles nested "Continuous Exam / Total" blocks)
                                    if not status_clean:
                                        for cell_text in reversed(row):
                                            ct = (cell_text or '').strip()
                                            if not ct:
                                                continue
                                            m = _grade_re.search(ct)
                                            if m:
                                                # Always use the matched grade token; do not include surrounding text.
                                                status_clean = m.group(1)
                                                break

                                    # No guessing: only show portal-provided labels; if missing, show '-'
                                    if not status_clean:
                                        status_clean = "-"

                                    # === FILTER: keep ONLY final subject rows (drop quiz/midterm/summary lines) ===
                                    subj_lower = subject_name.strip().lower()
                                    status_lower = status_clean.strip().lower()

                                    def _contains_any(text: str, tokens) -> bool:
                                        t = (text or '').lower()
                                        return any(tok in t for tok in tokens)

                                    # Drop obvious non-subject summary lines
                                    if subj_lower in {'total', 'sum', 'subtotal', 'overall', 'result'}:
                                        continue
                                    if _contains_any(subj_lower, ['total', 'subtotal', 'overall', 'sum', 'result', 'المجموع', 'مجموع', 'الكلي', 'كۆی', 'کۆی گشتی', 'جمع']):
                                        continue

                                    # Drop rows where the "subject" itself is just a grade label (e.g., 'Medium')
                                    if _grade_re.fullmatch(subject_name.strip()):
                                        continue

                                    # Drop assessment-detail rows (quiz/midterm/etc.) unless they truly carry final labels
                                    assessment_like = any(tok in subj_lower for tok in [
                                        'quiz', 'mid term', 'midterm', 'activity', 'act.', 'ass.', 'assignment',
                                        'report', 'seminar', 'practical', 'presentation', 'final',
                                        'hw', 'homework', 'home work', 'project', 'lab'
                                    ])

                                    # A final subject row should have a final-status-like label OR be explicitly pending/not marked.
                                    status_looks_final = bool(_grade_re.search(status_clean))
                                    if status_clean == '-':
                                        status_looks_final = False

                                    # If it's assessment-like and does not look like a final status row, drop it
                                    if assessment_like and not status_looks_final:
                                        continue

                                    # If it does not look like a final status row AND also has no usable total, drop it
                                    if not status_looks_final and total_clean in ['-', '0', '0.0']:
                                        continue

                                    # If the "status" text itself looks like an assessment label (HW 2, Quiz, etc.), drop it
                                    if _contains_any(status_lower, ['hw', 'homework', 'quiz', 'mid term', 'midterm', 'assignment', 'report', 'presentation', 'project', 'lab']):
                                        continue

                                    results.append({
                                        'AcademicYear': academic_year,
                                        'SemesterName': semester_name,
                                        'SemesterLabel': semester_label,
                                        # Back-compat keys (used by existing frontend fallbacks)
                                        'SubjectName': subject_name,
                                        'ContinuousSummary': total_clean,
                                        # Explicit simplified keys for final table mapping
                                        'Title': subject_name,
                                        'TotalGrade': total_clean,
                                        'Status': status_clean,
                                        'StudentId': student_id,
                                    })
                                    # De-duplicate within same year+semester for identical titles (avoid duplicates)
                                    try:
                                        t_norm = (subject_name or '').strip().lower()
                                        if t_norm and 'retake' not in t_norm and 'اعادة' not in t_norm and 'إعادة' not in t_norm:
                                            k = (academic_year or '', semester_name or '', t_norm)
                                            new_row = results[-1]
                                            existing = best_by_key.get(k)
                                            if existing is None:
                                                best_by_key[k] = new_row
                                            else:
                                                def _score(row):
                                                    tg = str(row.get('TotalGrade', '')).strip()
                                                    st = str(row.get('Status', '')).strip()
                                                    has_num = 1 if re.fullmatch(r'\d+(?:\.\d+)?', tg) else 0
                                                    has_status = 1 if st and st != '-' else 0
                                                    return (has_num, has_status, float(tg) if has_num else -1.0)
                                                if _score(new_row) > _score(existing):
                                                    best_by_key[k] = new_row
                                    except Exception:
                                        pass
                            except Exception as row_error:
                                logger.error(f"Error parsing result card: {row_error}")
                                continue
                        
                        # Finalize: keep only the best row per (year, semester, title) and drop ambiguous semester rows
                        final_results = []
                        try:
                            import re
                            for row in results:
                                year = str(row.get('AcademicYear', '') or '').strip()
                                sem = str(row.get('SemesterName', '') or '').strip()
                                title = str(row.get('Title') or row.get('SubjectName') or '').strip()
                                t_norm = title.lower()
                                is_retake = ('retake' in t_norm) or ('اعادة' in t_norm) or ('إعادة' in t_norm)

                                # Only keep rows that can be placed in a real semester
                                if not year:
                                    continue
                                if not sem or sem == 'Unknown Semester':
                                    continue

                                if is_retake:
                                    final_results.append(row)
                                    continue

                                k = (year, sem, t_norm)
                                if best_by_key.get(k) is row:
                                    final_results.append(row)
                        except Exception:
                            final_results = results

                        results = final_results

                        logger.info(f"[OK] Successfully parsed {len(results)} official results for student {student_id}")
                        
                        return {
                            'success': True,
                            'results': results,
                            'total_count': len(results)
                        }
                    
                    # Try JSON if not HTML
                    data = response.json()
                    logger.info(f"Parsed JSON structure - Type: {type(data)}, Keys: {data.keys() if isinstance(data, dict) else 'N/A'}")
                    
                    # Handle different API response structures
                    results = []
                    if isinstance(data, list):
                        results = data
                    elif isinstance(data, dict):
                        for key in ['data', 'Data', 'results', 'Results', 'items', 'Items', 'list', 'List']:
                            if key in data:
                                results = data[key]
                                break
                        if not results and data:
                            results = [data]
                    
                    if not isinstance(results, list):
                        results = [results] if results else []
                    
                    logger.info(f"[OK] Successfully fetched {len(results)} official results for student {student_id}")
                    
                    return {
                        'success': True,
                        'results': results,
                        'total_count': len(results)
                    }
                    
                except ValueError as e:
                    logger.error(f"Response parsing failed: {str(e)}")
                    logger.error(f"Response content: {response.text[:500]}")
                    return {
                        'success': False,
                        'error': 'Unable to parse server response. Please try again.',
                        'results': []
                    }
                    
            except requests.Timeout:
                return {
                    'success': False,
                    'error': 'Request timeout. Please try again.',
                    'results': []
                }
            except requests.RequestException as e:
                logger.error(f"Request error fetching official results: {str(e)}")
                return {
                    'success': False,
                    'error': f'Network error: {str(e)}',
                    'results': []
                }
            except Exception as e:
                logger.exception(f"Unexpected error fetching official results: {str(e)}")
                return {
                    'success': False,
                    'error': f'Error: {str(e)}',
                    'results': []
                }
        
        # Fetch results in thread to avoid blocking
        result = await asyncio.to_thread(fetch_official_results)
        
        if result['success']:
            _set_cached_official_results(student_id, result.get('results', []))
            return JSONResponse({
                "success": True,
                "results": result['results'],
                "total_count": result.get('total_count', 0)
            })
        else:
            error_msg = result.get('error', 'Failed to fetch official results')

            # Graceful fallback: return recently cached official results if available.
            if cached_official.get('results'):
                return JSONResponse({
                    "success": True,
                    "results": cached_official['results'],
                    "total_count": len(cached_official['results']),
                    "warning": error_msg,
                    "source": "cache"
                })

            # Session-related errors should still force re-login.
            if 'expired' in error_msg.lower():
                return JSONResponse({
                    "success": False,
                    "error": error_msg,
                    "results": []
                }, status_code=401)

            # Avoid HTTP 500/401 hard-fail screens for temporary upstream issues.
            return JSONResponse({
                "success": True,
                "results": [],
                "total_count": 0,
                "warning": error_msg,
                "source": "live"
            })
    
    except Exception as exc:
        logger.exception("Error fetching official results data: %s", str(exc))
        return JSONResponse({
            "success": False,
            "error": f"Server error: {str(exc)}",
            "results": []
        }, status_code=500)


@app.get("/api/results/debug")
async def debug_results(request: Request) -> JSONResponse:
    """
    DEBUG ENDPOINT: Show all stored results (filtered and unfiltered) for current user
    Helps diagnose semester detection and filtering issues
    """
    try:
        session_token = _resolve_session_token(request)
        
        if not session_token or session_token.strip() == "":
            return JSONResponse({
                "success": False,
                "error": "Session token required. Please login first."
            }, status_code=401)
        
        # Get session and student ID
        session = attendance_service.session_manager.get_session(session_token)
        if not session:
            return JSONResponse({
                "success": False,
                "error": "Session expired or invalid."
            }, status_code=401)
        
        student_id = session.get('student_id', '')
        if not student_id:
            return JSONResponse({
                "success": False,
                "error": "Student ID not found in session."
            }, status_code=400)
        
        # Get ALL stored results for this student (no filtering)
        from database import get_student_results
        all_stored = get_student_results(student_id, limit=500)
        
        # Analyze each result
        debug_results = []
        for stored in all_stored:
            raw_text = stored.get('raw_text', '')
            semester_raw = stored.get('semester', '')
            
            # Check if it passes year filter
            year_check = results_service._belongs_to_target_year(semester_raw, raw_text)
            
            # Get semester display (if passes year filter)
            semester_display = results_service._to_semester_display(semester_raw, raw_text) if year_check else None
            
            # Check fall/spring detection
            combined = f"{semester_raw or ''} {raw_text or ''}".lower()
            is_fall = bool(re.search(r'(?:[_\-]f[_\-]?\d{2}-\d{2}|\bfall\b|\b1st\s+semester\b|\bfirst\s+semester\b)', combined))
            is_spring = bool(re.search(r'(?:[_\-]s[_\-]?\d{2}-\d{2}|\bspring\b|\b2nd\s+semester\b|\bsecond\s+semester\b)', combined))
            
            debug_results.append({
                'subject': stored.get('subject'),
                'exam_type': stored.get('exam_type'),
                'score': stored.get('score'),
                'semester_raw': semester_raw,
                'raw_text_sample': raw_text[:100] if raw_text else '',
                'passes_year_filter': year_check,
                'is_fall_detected': is_fall,
                'is_spring_detected': is_spring,
                'semester_display_mapped': semester_display,
                'created_at': stored.get('created_at', '')
            })
        
        # Count by semester
        fall_count = sum(1 for r in debug_results if r['is_fall_detected'])
        spring_count = sum(1 for r in debug_results if r['is_spring_detected'])
        pass_filter_count = sum(1 for r in debug_results if r['passes_year_filter'])
        
        return JSONResponse({
            "success": True,
            "student_id": student_id,
            "summary": {
                "total_stored": len(all_stored),
                "pass_year_filter": pass_filter_count,
                "fall_detected": fall_count,
                "spring_detected": spring_count,
                "no_semester_detected": len(all_stored) - fall_count - spring_count
            },
            "debug_results": debug_results,
            "target_year": f"{results_service.TARGET_ACADEMIC_YEAR_FULL} ({results_service.TARGET_ACADEMIC_YEAR_SHORT})"
        })
    
    except Exception as exc:
        logger.exception("Error in debug results: %s", str(exc))
        return JSONResponse({
            "success": False,
            "error": f"Error: {str(exc)}",
            "debug_results": []
        }, status_code=500)


@app.post("/api/results/refresh")
async def refresh_results(request: Request) -> JSONResponse:
    """
    REFRESH ENDPOINT: Clear cached results and force fetch fresh from portal
    Useful when you know portal has new data and cached data is stale
    Clears old data and triggers immediate re-fetch from portal API
    """
    try:
        session_token = _resolve_session_token(request)
        
        if not session_token or session_token.strip() == "":
            return JSONResponse({
                "success": False,
                "error": "Session token required. Please login first."
            }, status_code=401)
        
        # Get session and student ID
        session = attendance_service.session_manager.get_session(session_token)
        if not session:
            return JSONResponse({
                "success": False,
                "error": "Session expired or invalid."
            }, status_code=401)
        
        student_id = session.get('student_id', '')
        if not student_id:
            return JSONResponse({
                "success": False,
                "error": "Student ID not found in session."
            }, status_code=400)
        
        # Clear all old results for this student
        from database import clear_student_results
        cleared_count = clear_student_results(student_id)
        logger.info(f"Cleared {cleared_count} old results for student {student_id}")
        
        # Now force fetch fresh from portal
        result = await results_service.get_results(session_token, attendance_service.session_manager)
        logger.info(f"Fresh fetch: success={result.get('success')}, new_saved={result.get('new_results_saved', 0)}, total={result.get('total_count', 0)}")
        
        if result['success']:
            return JSONResponse({
                "success": True,
                "message": f"Cleared {cleared_count} old results. Fetched {result.get('new_results_saved', 0)} fresh results from portal.",
                "results": result['results'],
                "total_count": result.get('total_count', 0),
                "new_results_saved": result.get('new_results_saved', 0)
            })
        else:
            return JSONResponse({
                "success": False,
                "error": result.get('error', 'Failed to fetch fresh results'),
                "results": []
            }, status_code=500)
    
    except Exception as exc:
        logger.exception("Error refreshing results: %s", str(exc))
        return JSONResponse({
            "success": False,
            "error": f"Error: {str(exc)}",
            "results": []
        }, status_code=500)



# ============================================
# ADMIN SOC (Security Operations Center)
# ============================================

SECRET_ADMIN_KEY = ADMIN_SECRET_KEY

@app.get("/admin-portal")
async def admin_portal(admin_key: str = None) -> HTMLResponse:
    """
    Hidden Admin Dashboard for security monitoring and IP management
    Protected by SECRET_ADMIN_KEY
    """
    logo_version = "2026-03-18"

    if not _is_valid_admin_key(admin_key):
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

    def _render_device_info(user_agent: str) -> str:
        if not user_agent:
            return "<span style='color: var(--text-secondary);'>Unknown</span>"
        device = db.detect_device_type(user_agent)
        return (
            "<div style=\"display: flex; flex-direction: column; gap: 4px;\">"
            "<span style=\"display: flex; align-items: center; gap: 6px; color: var(--kurdish-yellow); font-weight: 600; font-size: 0.875rem;\">"
            f"<i class=\"fas {device['icon']}\"></i>{device['device']}"
            "</span>"
            "<span style=\"color: var(--text-secondary); font-size: 0.75rem;\">"
            f"<i class=\"fas fa-desktop\" style=\"font-size: 0.7rem;\"></i> {device['os']}"
            "</span>"
            "<span style=\"color: var(--text-secondary); font-size: 0.75rem;\">"
            f"<i class=\"fas fa-globe\" style=\"font-size: 0.7rem;\"></i> {device['browser']}"
            "</span>"
            "</div>"
        )
    
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
            .logo-text {{
                display: flex;
                flex-direction: column;
                justify-content: center;
                gap: 0.15rem;
            }}
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
                row-gap: 0.35rem;
                flex-direction: column;
            
            .stats-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
                gap: 1.5rem;
                margin-bottom: 2rem;
            }}
            
            .stat-card {{
                flex-shrink: 0;
                display: inline-flex;
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
            
            /* Mobile Responsiveness */
            @media (max-width: 768px) {{
                body {{
                    padding: 0.75rem;
                }}
                
                .header {{
                    flex-direction: column;
                    gap: 1rem;
                    padding: 1rem;
                }}
                
                .header-left {{
                    width: 100%;
                    justify-content: center;
                }}
                
                .header h1 {{
                    font-size: 1.25rem;
                }}
                
                .stats-grid {{
                    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                    gap: 0.75rem;
                }}
                
                .stat-card {{
                    padding: 1rem;
                }}
                
                .stat-card .value {{
                    font-size: 1.75rem;
                }}
                
                .section {{
                    padding: 1rem;
                }}
                
                .threat-rules-grid {{
                    grid-template-columns: 1fr;
                }}
                
                .threat-actions {{
                    flex-direction: column;
                }}
                
                .threat-btn {{
                    width: 100%;
                    min-width: auto;
                }}
                
                .table-wrapper {{
                    overflow-x: auto;
                    -webkit-overflow-scrolling: touch;
                }}
                
                table {{
                    font-size: 0.75rem;
                }}
                
                th, td {{
                    padding: 0.5rem;
                    white-space: nowrap;
                }}
                
                .btn {{
                    padding: 0.5rem 0.75rem;
                    font-size: 0.75rem;
                }}
                
                .ip-address {{
                    font-size: 0.75rem;
                    padding: 0.25rem 0.5rem;
                }}
            }}
        </style>
    </head>
    <body oncontextmenu="return false;">
        <!-- Splash Screen -->
        <div id="splash-screen">
            <img src="/static/icons/icon-192x192.png?v={logo_version}" alt="SwiftSync" class="splash-logo">
            <div class="splash-text">SwiftSync</div>
            <div class="splash-subtitle">by SSCreative</div>
        </div>
        
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
                
                // Prompt for admin key (never hardcode it!)
                const adminKey = prompt('Enter admin key:');
                if (!adminKey) {{
                    alert('Admin key required');
                    return;
                }}
                
                try {{
                    const response = await fetch(`/admin-portal/clear-activity?admin_key=${{encodeURIComponent(adminKey)}}`, {{
                        method: 'POST'
                    }});
                    const data = await response.json();
                    
                    if (data.success) {{
                        alert(data.message);
                        location.reload();
                    }} else {{
                        alert('Error: ' + data.error);
                    }}
                }} catch (error) {{
                    alert('Failed to clear activity: ' + error.message);
                }}
            }}
        </script>
        <div class="container">
            <div class="header">
                <div class="header-left">
                    <div>
                        <h1>Admin <span style="color: #FFD700;">SOC</span></h1>
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
                    <button class="btn threat-btn" onclick="showNotification('Threat analytics feature coming soon')">
                        <i class="fas fa-chart-bar"></i> View Analytics
                    </button>
                    <button class="btn threat-btn" onclick="showNotification('Advanced rule configuration available in settings')">
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
                    notification.innerHTML = '<i class="fas fa-info-circle" style="margin-right: 0.5rem;"></i>' + message;
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
                    <h2>Recent Visitors & Activity Log</h2>
                </div>
                <div class="table-wrapper">
                    <table>
                        <thead>
                            <tr>
                                <th><i class="fas fa-network-wired"></i> IP Address</th>
                                <th><i class="fas fa-user"></i> User ID</th>
                                <th><i class="fas fa-mobile-alt"></i> Device</th>
                                <th><i class="fas fa-clock"></i> Timestamp</th>
                                <th><i class="fas fa-bolt"></i> Action</th>
                                <th><i class="fas fa-shield-alt"></i> Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {"".join([f'''
                            <tr style="{"border-left: 4px solid #ef4444;" if db.has_threat_log(visitor['ip_address']) else ""}">
                                <td>
                                    <span class="ip-address" style="{"border-color: rgba(239, 68, 68, 0.5); color: #ef4444; background: rgba(239, 68, 68, 0.1);" if db.has_threat_log(visitor['ip_address']) else ""}">
                                        {visitor['ip_address']}
                                        {"<i class='fas fa-exclamation-triangle' style='color: #ef4444; margin-left: 6px;' title='Threat Detected'></i>" if db.has_threat_log(visitor['ip_address']) else ""}
                                    </span>
                                </td>
                                <td>
                                    <span class="action-badge" style="background: rgba(34, 139, 34, 0.1); color: var(--kurdish-green); border: 1px solid rgba(34, 139, 34, 0.3);">
                                        <i class="fas fa-id-card"></i> {visitor.get('username', 'Guest')}
                                    </span>
                                </td>
                                <td>
                                    {_render_device_info(visitor['user_agent'])}
                                </td>
                                <td class="timestamp" style="font-family: 'SF Mono', monospace; font-size: 0.8rem;">
                                    <i class="fas fa-calendar-alt" style="color: var(--kurdish-yellow); margin-right: 4px;"></i>
                                    {visitor['timestamp']}
                                </td>
                                <td>
                                    <span class="action-badge" style="background: rgba(59, 130, 246, 0.1); color: var(--info); border: 1px solid rgba(59, 130, 246, 0.3);">
                                        <i class="fas fa-bolt"></i> {visitor['action']}
                                    </span>
                                </td>
                                <td>
                                    <button class="btn btn-block" onclick="blockIP('{visitor['ip_address']}')" style="font-size: 0.8rem; padding: 0.5rem 1rem;">
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
    if not _is_valid_admin_key(admin_key):
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
    if not _is_valid_admin_key(admin_key):
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
    if not _is_valid_admin_key(admin_key):
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
async def get_absence_details(request: Request, student_class_id: str = None, class_id: str = None) -> JSONResponse:
    """
    Fetch absence details (dates/times) for specific module
    
    Android Fix: Uses HttpOnly cookie for session persistence
    """
    try:
        session_token = _resolve_session_token(request)
        
        if not session_token or session_token.strip() == "":
            return JSONResponse({
                "success": False,
                "error": "Session token required"
            }, status_code=401)
        
        if not student_class_id or not class_id:
            return JSONResponse({
                "success": False,
                "error": "student_class_id and class_id are required"
            }, status_code=400)
        
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
async def attendance_logout(request: Request) -> JSONResponse:
    """
    Logout user and invalidate session
    
    Android Fix: Uses HttpOnly cookie session and clears cookie
    """
    try:
        session_token = _resolve_session_token(request)
        
        if not session_token or session_token.strip() == "":
            return JSONResponse({
                "success": False,
                "message": "No active session"
            })
        
        success = attendance_service.logout(session_token)
        
        # Create response
        response = JSONResponse({
            "success": success,
            "message": "Logged out successfully" if success else "Session not found"
        })
        
        # ANDROID FIX: Clear the cookie on logout
        response.delete_cookie(key="session_token", path="/")
        
        return response
        
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
    logo_version = "2026-03-18"
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
        <title>SwiftSync • 2025/2026</title>
        
        <!-- PWA Meta Tags -->
        <meta name="description" content="SwiftSync - Student lecture management by SSCreative">
        <meta name="theme-color" content="#00d9ff">
        <meta name="apple-mobile-web-app-capable" content="yes">
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
        <meta name="apple-mobile-web-app-title" content="SwiftSync">
        <meta name="mobile-web-app-capable" content="yes">
        <link rel="manifest" href="/manifest.json">
        <link rel="apple-touch-icon" href="/static/icons/icon-192x192.png?v={logo_version}">
        
        <!-- PERFORMANCE: Preconnect to external resources for faster loading -->
        <link rel="preconnect" href="https://cdnjs.cloudflare.com" crossorigin>
        <link rel="preconnect" href="https://fonts.googleapis.com" crossorigin>
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link rel="dns-prefetch" href="https://cdnjs.cloudflare.com">
        <link rel="dns-prefetch" href="https://fonts.googleapis.com">
        
        <!-- PERFORMANCE: Preload critical resources -->
        <link rel="preload" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" as="style">
        <link rel="preload" href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;900&family=Outfit:wght@400;500;600;700;800&display=swap" as="style">
        
        <!-- Preload critical resources for instant display -->
        <link rel="preload" href="/static/icons/icon-192x192.png?v={logo_version}" as="image">
        
        <!-- Load CSS -->
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;900&family=Outfit:wght@400;500;600;700;800&display=swap" rel="stylesheet">
        <style>
            /* ========================================
               PERFORMANCE OPTIMIZATIONS
               ======================================== */
            
            /* Splash Screen for PWA - Optimized for instant display */
            #splash-screen {{
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100vh;
                background: linear-gradient(135deg, #0a0a0a 0%, #1a1a2e 100%);
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                z-index: 99999;
                opacity: 1;
                transition: opacity 0.3s ease;
            }}
            
            #splash-screen.hidden {{
                display: none;
            }}
            
            .splash-logo {{
                width: 120px;
                height: 120px;
                border-radius: 30px;
                animation: pulse 1.2s ease-in-out infinite;
                box-shadow: 0 8px 32px rgba(0, 217, 255, 0.3);
                will-change: transform;
                image-rendering: -webkit-optimize-contrast;
                image-rendering: crisp-edges;
            }}
            
            .splash-text {{
                color: #00d9ff;
                font-size: 2rem;
                font-weight: 800;
                margin-top: 1.5rem;
                animation: fadeInUp 0.8s ease;
            }}
            
            .splash-subtitle {{
                color: rgba(255, 255, 255, 0.7);
                font-size: 0.9rem;
                margin-top: 0.5rem;
                animation: fadeInUp 0.8s ease 0.2s both;
            }}
            
            /* Hide text cursor globally */
            * {{
                caret-color: transparent !important;
            }}
            
            input, textarea {{
                caret-color: transparent !important;
            }}
            
            /* Hide text cursor globally */
            * {{
                caret-color: transparent !important;
            }}
            
            input, textarea {{
                caret-color: transparent !important;
            }}
            
            @keyframes pulse {{
                0%, 100% {{ transform: scale(1); }}
                50% {{ transform: scale(1.05); }}
            }}
            
            @keyframes fadeInUp {{
                from {{
                    opacity: 0;
                    transform: translateY(20px);
                }}
                to {{
                    opacity: 1;
                    transform: translateY(0);
                }}
            }}
            
            @keyframes fadeOut {{
                to {{
                    opacity: 0;
                    visibility: hidden;
                }}
            }}
            
            * {{ 
                margin: 0; 
                padding: 0; 
                box-sizing: border-box;
            }}
            
            /* ULTRA-RESPONSIVE: Remove ALL delays and enable instant feedback */
            *, *:focus, *:active {{
                outline: none !important;
                -webkit-tap-highlight-color: transparent;  /* No iOS tap delay */
                -webkit-touch-callout: none;  /* Disable iOS callout */
            }}
            
            /* GPU acceleration for smooth animations */
            button, .sync-btn, .download-btn, .subject-header, .file-item {{
                -webkit-transform: translateZ(0);  /* Force GPU rendering */
                transform: translateZ(0);
                backface-visibility: hidden;  /* Smoother animations */
                will-change: transform, opacity;  /* Optimize for changes */
            }}
            
            /* Remove focus ring from buttons for instant feel */
            button:focus, button:active,
            .download-btn:focus, .download-btn:active,
            .sync-btn:focus, .sync-btn:active,
            .subject-header:focus, .subject-header:active,
            .file-item:focus, .file-item:active {{
                outline: none !important;
                box-shadow: none !important;
            }}
            
            /* Make ALL buttons ultra-responsive */
            button, .btn, .sync-btn, .download-btn {{
                cursor: pointer;
                touch-action: manipulation;  /* Prevent zoom delay on mobile */
                user-select: none;
                -webkit-user-select: none;
                transition: all 0.1s ease-out !important;  /* INSTANT response */
            }}
            
            button:active, .btn:active, .sync-btn:active, .download-btn:active {{
                transform: scale(0.97) !important;  /* INSTANT visual feedback */
                transition: transform 0.05s ease-out !important;
            }}

            .tap-active {{
                transform: scale(0.97) !important;
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
                --radius-lg: 20px;
                --radius-md: 14px;
                --radius-sm: 10px;
                --shadow-soft: 0 12px 30px rgba(0, 0, 0, 0.25);
                --shadow-accent: 0 18px 50px rgba(0, 217, 255, 0.18);
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
            
            /* Smooth scrolling globally */
            html {{
                scroll-behavior: smooth;
            }}
            
            body {{
                -webkit-font-smoothing: antialiased;
                -moz-osx-font-smoothing: grayscale;
            }}

            h1, h2, h3, .stat-value, .subject-title, .login-header h2, .attendance-header h2, .modal-title {{
                font-family: 'Outfit', 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
                letter-spacing: -0.01em;
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

            :root {{
                --card-pad-x: 1.35rem;
                --card-pad-y: 1.2rem;
                --mobile-card-pad-x: 1.1rem;
                --mobile-card-pad-y: 1rem;
                --icon-gap: 0.9rem;
            }}
            
            /* Header */
            .nav {{
                display: grid;
                grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
                align-items: center;
                column-gap: 1rem;
                padding: 1.05rem 1.25rem;
                margin-bottom: 2rem;
                background: rgba(22, 33, 62, 0.6);
                backdrop-filter: blur(5px);
                border-radius: var(--radius-lg);
                border: 1px solid rgba(34, 211, 238, 0.35);
                box-shadow: var(--shadow-soft);
            }}
            
            .logo {{
                display: flex;
                align-items: center;
                gap: 0.8rem;
                min-width: 0;
                justify-self: start;
            }}
            
            .logo-icon {{
                width: 56px;
                height: 56px;
                border-radius: 16px;
                overflow: visible;
                position: relative;
                display: flex;
                align-items: center;
                justify-content: center;
                background: linear-gradient(135deg, #22d3ee 0%, #14b8a6 50%, #0ea5e9 100%);
                box-shadow: 0 0 22px rgba(34, 211, 238, 0.7);
                animation: logoPulse 4s ease-in-out infinite;
                font-size: 28px;
                font-weight: 900;
                color: white;
                text-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
            }}
            .logo-icon::before,
            .logo-icon::after {{
                content: none;
            }}

            @keyframes logoPulse {{
                0%, 100% {{
                    transform: translateY(0) scale(1);
                    box-shadow: 0 0 18px rgba(34, 211, 238, 0.6);
                }}
                50% {{
                    transform: translateY(-2px) scale(1.03);
                    box-shadow: 0 0 30px rgba(56, 189, 248, 0.9);
                }}
            }}
            
            .logo-text h1 {{
                font-size: 1.45rem;
                font-weight: 900;
                line-height: 1.08;
                margin: 0;
                background: linear-gradient(135deg, #22d3ee 0%, #38bdf8 40%, #a5f3fc 80%, #e5e7eb 100%);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                background-clip: text;
                letter-spacing: -0.02em;
                animation: shimmer 3s ease-in-out infinite;
            }}

            .logo-text {{
                display: flex;
                flex-direction: column;
                justify-content: center;
                min-width: 0;
                gap: 0.15rem;
            }}
            
            @keyframes shimmer {{
                0%, 100% {{ filter: brightness(1); }}
                50% {{ filter: brightness(1.3); }}
            }}
            
            .logo-text p {{
                font-size: 0.72rem;
                            background: linear-gradient(90deg, #22d3ee 0%, #2dd4bf 50%, #4ade80 100%);
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
                border-radius: 10px;
                font-size: 0.85rem;
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
                align-items: center;
                justify-content: center;
                padding: 0.6rem 1.2rem;
                background: linear-gradient(135deg, rgba(0, 217, 255, 0.15), rgba(0, 150, 255, 0.15));
                color: #00d9ff;
                border: 2px solid rgba(0, 217, 255, 0.4);
                border-radius: 10px;
                font-size: 0.9rem;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.2s ease;
                white-space: nowrap;
                -webkit-tap-highlight-color: transparent;
                user-select: none;
                position: relative;
                overflow: hidden;
            }}
            
            .install-btn::before {{
                content: '';
                position: absolute;
                top: 50%;
                left: 50%;
                width: 0;
                height: 0;
                background: rgba(0, 217, 255, 0.3);
                border-radius: 50%;
                transform: translate(-50%, -50%);
                transition: width 0.4s ease, height 0.4s ease;
            }}
            
            .install-btn:hover::before,
            .install-btn:active::before {{
                width: 300px;
                height: 300px;
            }}
            
            .install-btn:hover {{
                background: linear-gradient(135deg, rgba(0, 217, 255, 0.3), rgba(0, 150, 255, 0.3));
                border-color: rgba(0, 217, 255, 0.6);
                transform: translateY(-2px) scale(1.02);
                box-shadow: 0 5px 20px rgba(0, 217, 255, 0.3);
            }}
            
            .install-btn:active {{
                transform: translateY(0) scale(0.98);
            }}
            
            .install-btn.pulse {{
                animation: pulse-install 2s ease-in-out infinite;
            }}
            
            @keyframes pulse-install {{
                0%, 100% {{
                    box-shadow: 0 0 0 0 rgba(0, 217, 255, 0.7);
                }}
                50% {{
                    box-shadow: 0 0 0 10px rgba(0, 217, 255, 0);
                }}
            }}
            
            .install-btn i {{
                margin-right: 0.5rem;
                position: relative;
                z-index: 1;
            }}
            
            .install-btn span {{
                position: relative;
                z-index: 1;
            }}
            
            .install-btn:disabled {{
                opacity: 0.6;
                cursor: not-allowed;
                transform: none;
            }}
            
            .nav-actions {{
                display: flex;
                gap: 0.65rem;
                align-items: center;
                flex-wrap: wrap;
                justify-content: flex-end;
                justify-self: end;
            }}
            
            /* Kurdish Text Animation (in navbar) - Fixed size to prevent layout shift */
            .kurdish-text {{
                font-size: 1rem;
                font-weight: 500;
                color: rgba(255, 255, 255, 0.95);
                letter-spacing: 0.03em;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #22d3ee 0%, #2dd4bf 50%, #4ade80 100%);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                background-clip: text;
                width: max-content;
                max-width: 360px;
                height: 30px;
                min-height: 30px;
                text-align: center;
                display: flex;
                align-items: center;
                justify-content: center;
                white-space: nowrap;
                overflow: hidden;
                justify-self: center;
            }}
            
            @keyframes cursorBlink {{
                0%, 49% {{ opacity: 1; }}
                50%, 100% {{ opacity: 0; }}
            }}
            
            .kurdish-text::after {{
                content: '|';
                color: #22d3ee;
                animation: cursorBlink 0.7s infinite;
                margin-left: 2px;
            }}
            
            /* Stats Grid */
            .stats {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
                gap: 1.25rem;
                margin-bottom: 2.5rem;
            }}
            
            .stat-card {{
                background: var(--bg-secondary);
                border: 1px solid var(--border);
                border-radius: var(--radius-lg);
                padding: 1.75rem;
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
                box-shadow: var(--shadow-accent);
            }}
            
            .stat-header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 1.2rem;
            }}
            
            .stat-icon {{
                width: 42px;
                height: 42px;
                background: var(--glass);
                border-radius: var(--radius-sm);
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 1.2rem;
            }}
            
            .stat-card:nth-child(1) .stat-icon {{ color: var(--accent); }}
            .stat-card:nth-child(2) .stat-icon {{ color: var(--accent); }}
            .stat-card:nth-child(3) .stat-icon {{ color: var(--accent); }}
            
            .stat-trend {{
                font-size: 0.75rem;
                color: var(--success);
                background: rgba(0, 255, 136, 0.1);
                padding: 0.25rem 0.5rem;
                border-radius: 6px;
            }}
            
            .stat-value {{
                font-size: 2.2rem;
                font-weight: 900;
                background: linear-gradient(135deg, var(--text-primary), var(--text-secondary));
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                background-clip: text;
                line-height: 1;
                margin-bottom: 0.5rem;
            }}
            
            .stat-label {{
                font-size: 0.8rem;
                color: var(--text-tertiary);
                text-transform: uppercase;
                letter-spacing: 0.05em;
                font-weight: 600;
            }}
            
            /* Toolbar */
            .toolbar {{
                background: var(--bg-secondary);
                border: 1px solid var(--border);
                border-radius: var(--radius-lg);
                padding: 1.25rem;
                margin-bottom: 1.75rem;
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
                padding: 0.95rem 1rem 0.95rem 3rem;
                background: var(--bg-tertiary);
                border: 1px solid var(--border);
                border-radius: var(--radius-md);
                color: var(--text-primary);
                font-size: 0.92rem;
                font-weight: 500;
                transition: all 0.3s;
                caret-color: var(--accent);
                cursor: text;
                overflow: hidden;
                text-overflow: ellipsis;
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
                padding: 0.9rem 1.7rem;
                background: linear-gradient(135deg, var(--accent), var(--success));
                color: var(--bg-primary);
                border: none;
                border-radius: var(--radius-md);
                cursor: pointer;
                font-weight: 700;
                font-size: 0.88rem;
                transition: all 0.1s ease-out;  /* ULTRA FAST response */
                display: flex;
                align-items: center;
                gap: 0.75rem;
                position: relative;
                overflow: hidden;
                user-select: none;
                -webkit-tap-highlight-color: transparent;  /* Remove mobile tap delay */
                touch-action: manipulation;  /* Prevent zoom on double-tap */
                will-change: transform, box-shadow;  /* GPU acceleration */
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
                transition: width 0.3s ease-out, height 0.3s ease-out;  /* Faster ripple */
            }}
            
            .sync-btn:hover::before {{
                width: 300px;
                height: 300px;
            }}
            
            .sync-btn:hover {{
                transform: translateY(-2px) scale(1.02);  /* More noticeable feedback */
                box-shadow: 0 10px 40px var(--accent-glow);
            }}
            
            .sync-btn:active {{
                transform: translateY(0) scale(0.98);  /* INSTANT press feedback */
                transition: all 0.05s ease-out;  /* INSTANT response on click */
            }}
            
            .sync-btn:disabled {{
                opacity: 0.5;
                cursor: not-allowed;
                transform: none !important;
            }}
            
            .info-badge {{
                display: flex;
                align-items: center;
                gap: 0.5rem;
                padding: 0.65rem 1.1rem;
                background: var(--glass);
                border: 1px solid var(--border);
                border-radius: 50px;
                font-size: 0.82rem;
                color: var(--text-secondary);
                backdrop-filter: blur(10px);
            }}
            
            .info-badge i {{
                color: var(--accent);
            }}
            
            /* Subject Sections - Clean Design */
            .subject-section {{
                background: var(--bg-secondary);
                border: 1px solid var(--border);
                border-radius: var(--radius-lg);
                margin-bottom: 1.5rem;
                overflow: hidden;
                transition: all 0.3s ease;
                position: relative;
            }}
            
            .subject-section:hover {{
                border-color: var(--accent);
                transform: translateY(-2px);
                box-shadow: 0 8px 24px rgba(0, 217, 255, 0.15);
            }}
            
            .subject-header {{
                padding: var(--card-pad-y) var(--card-pad-x);
                background: var(--bg-tertiary);
                cursor: pointer;
                display: grid;
                grid-template-columns: minmax(0, 1fr) auto;
                align-items: center;
                column-gap: 0.9rem;
                transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
                user-select: none;
                -webkit-tap-highlight-color: transparent;
                will-change: background, transform;
            }}
            
            .subject-header:hover {{
                background: rgba(0, 217, 255, 0.05);
                transform: translateX(2px);
            }}
            
            .subject-header:active {{
                transform: translateX(1px) scale(0.99);
            }}
            
            .subject-header:focus, .subject-header:active {{
                outline: none !important;
                border: none !important;
            }}
            
            .subject-title {{
                display: flex;
                align-items: center;
                gap: var(--icon-gap);
                font-size: 1.02rem;
                font-weight: 700;
                color: var(--text-primary);
                line-height: 1.35;
                flex-wrap: wrap;
                min-width: 0;
                padding-right: 0.25rem;
                word-break: break-word;
                row-gap: 0.35rem;
                overflow-wrap: anywhere;
            }}
            
            .subject-title i {{
                font-size: 1.3rem;
                color: var(--accent);
                flex-shrink: 0;
                margin-right: 0.05rem;
            }}
            
            .file-count {{
                font-size: 0.78rem;
                color: var(--text-tertiary);
                background: var(--glass);
                padding: 0.3rem 0.75rem;
                border-radius: 50px;
                margin-left: 0.75rem;
                white-space: nowrap;
                flex-shrink: 0;
                display: inline-flex;
            }}
            
            .collapse-btn {{
                width: 36px;
                height: 36px;
                background: var(--glass);
                border: 1px solid var(--border);
                border-radius: var(--radius-sm);
                color: var(--accent);
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: center;
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                will-change: transform, background;
                justify-self: end;
                margin-right: 0.1rem;
                flex-shrink: 0;
            }}
            
            .collapse-btn:hover {{
                background: var(--bg-tertiary);
                transform: scale(1.1);
                border-color: var(--accent);
            }}
            
            .collapse-btn:active {{
                transform: scale(0.95);
            }}
            
            .collapse-btn i {{
                transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                transform: rotate(-90deg);
                will-change: transform;
            }}
            
            /* Smooth content transitions */
            .subject-files,
            .semester-results-content,
            .semester-results-table,
            .year-content {{
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                overflow: hidden;
            }}
            
            .subject-files {{
                padding: var(--card-pad-y) var(--card-pad-x);
                display: none;
            }}
            
            /* File Items - Clean Design */
            .file-item {{
                display: flex;
                align-items: center;
                gap: 1rem;
                padding: var(--card-pad-y) var(--card-pad-x);
                background: var(--bg-tertiary);
                border: 1px solid var(--border);
                border-radius: var(--radius-md);
                margin-bottom: 1rem;
                transition: all 0.2s ease;
                position: relative;
            }}
            
            .file-item:last-child {{
                margin-bottom: 0;
            }}
            
            .file-item:hover {{
                background: var(--bg-secondary);
                border-color: var(--accent);
                transform: translateX(4px);
                box-shadow: 0 4px 16px rgba(0, 217, 255, 0.15);
            }}
            
            .file-icon {{
                width: 52px;
                height: 52px;
                display: flex;
                align-items: center;
                justify-content: center;
                border-radius: var(--radius-sm);
                font-size: 1.35rem;
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
                padding-right: 0.2rem;
            }}
            
            .file-name {{
                font-weight: 600;
                color: var(--text-primary);
                margin-bottom: 0.5rem;
                font-size: 0.95rem;
                line-height: 1.4;
                user-select: text;
                cursor: text;
                display: -webkit-box;
                -webkit-line-clamp: 2;
                -webkit-box-orient: vertical;
                overflow: hidden;
                overflow-wrap: anywhere;
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
                border-radius: var(--radius-sm);
                font-size: 0.85rem;
                font-weight: 600;
                color: var(--text-secondary);
                white-space: nowrap;
            }}
            
            .open-btn {{
                padding: 0.75rem 1.5rem;
                background: linear-gradient(135deg, #8b5cf6, #6366f1);
                color: white;
                border: none;
                border-radius: var(--radius-sm);
                cursor: pointer !important;
                font-weight: 700;
                font-size: 0.83rem;
                transition: all 0.15s ease-out;
                text-decoration: none !important;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                gap: 0.5rem;
                user-select: none;
                white-space: nowrap;
                touch-action: manipulation;
                -webkit-tap-highlight-color: transparent;
                flex-shrink: 0;
            }}
            
            .open-btn:hover {{
                transform: translateY(-2px);
                box-shadow: 0 8px 20px rgba(139, 92, 246, 0.4);
            }}
            
            .open-btn:active {{
                transform: translateY(0) scale(0.98);
                transition: all 0.05s ease-out;
            }}
            
            .download-btn {{
                padding: 0.75rem 1.5rem;
                background: linear-gradient(135deg, var(--accent), var(--success));
                color: var(--bg-primary);
                border: none;
                border-radius: var(--radius-sm);
                cursor: pointer !important;
                font-weight: 700;
                font-size: 0.83rem;
                transition: all 0.15s ease-out;
                text-decoration: none !important;
                display: inline-flex;
                align-items: center;
                gap: 0.5rem;
                user-select: none;
                white-space: nowrap;
                touch-action: manipulation;
                -webkit-tap-highlight-color: transparent;
                flex-shrink: 0;
            }}
            
            .download-btn:hover {{
                transform: translateY(-2px);
                box-shadow: 0 8px 20px var(--accent-glow);
            }}
            
            .download-btn:active {{
                transform: translateY(0) scale(0.98);
                transition: all 0.05s ease-out;
            }}
            
            /* AI Summary Button */
            .summary-btn {{
                padding: 0.75rem 1.5rem;
                background: linear-gradient(135deg, #DC143C 0%, #ff6b6b 100%);
                color: white;
                border: none;
                border-radius: var(--radius-sm);
                cursor: pointer !important;
                font-weight: 700;
                font-size: 0.83rem;
                transition: all 0.15s ease-out;
                display: inline-flex;
                align-items: center;
                gap: 0.5rem;
                user-select: none;
                white-space: nowrap;
                box-shadow: 0 4px 12px rgba(220, 20, 60, 0.3);
                touch-action: manipulation;
                -webkit-tap-highlight-color: transparent;
                flex-shrink: 0;
            }}
            
            .summary-btn:hover {{
                transform: translateY(-2px);
                box-shadow: 0 8px 20px rgba(220, 20, 60, 0.5);
                background: linear-gradient(135deg, #ff1744 0%, #ff4757 100%);
            }}
            
            .summary-btn:active {{
                transform: translateY(0) scale(0.98);
                transition: all 0.05s ease-out;
            }}
            
            .summary-btn:disabled {{
                opacity: 0.6;
                cursor: not-allowed;
                transform: none !important;
            }}
            
            /* Summarize All Button */
            .summarize-all-btn {{
                padding: 1rem 2rem;
                background: linear-gradient(135deg, #FFD700 0%, #2ea043 100%);
                color: #0f172a;
                border: none;
                border-radius: var(--radius-md);
                cursor: pointer !important;
                font-weight: 700;
                font-size: 0.88rem;
                transition: all 0.15s ease-out;
                display: flex;
                align-items: center;
                gap: 0.75rem;
                margin: 1.5rem 1.5rem 0 1.5rem;
                user-select: none;
                width: calc(100% - 3rem);
                justify-content: center;
                box-shadow: 0 4px 12px rgba(255, 215, 0, 0.3);
                touch-action: manipulation;
                -webkit-tap-highlight-color: transparent;
            }}
            
            .summarize-all-btn:hover {{
                transform: translateY(-2px);
                box-shadow: 0 8px 25px rgba(255, 215, 0, 0.5);
                background: linear-gradient(135deg, #FFE55C 0%, #3cb043 100%);
            }}
            
            .summarize-all-btn:active {{
                transform: translateY(0) scale(0.98);
                transition: all 0.05s ease-out;
            }}
            
            .summarize-all-btn:disabled {{
                opacity: 0.6;
                cursor: not-allowed !important;
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
                border-radius: var(--radius-lg);
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
                padding: 1.75rem;
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
                padding: 1.75rem;
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
                gap: 0.75rem;
                margin-bottom: 1.6rem;
                padding: 0.45rem;
                background: var(--bg-secondary);
                border: 1px solid var(--border);
                border-radius: var(--radius-lg);
            }}
            
            .zone-tab {{
                flex: 1;
                padding: 0.75rem 1.2rem;
                background: transparent;
                border: none;
                border-radius: var(--radius-md);
                color: var(--text-secondary);
                font-size: 0.92rem;
                font-weight: 600;
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 0.6rem;
                cursor: pointer;
                transition: all 0.3s ease;
                position: relative;
                min-height: 48px;
            }}

            .zone-tab:not(.active) {{
                background: rgba(255, 255, 255, 0.02);
            }}

            .zone-tab .tab-label {{
                letter-spacing: 0.01em;
            }}

            .zone-tab .tab-meta {{
                font-size: 0.82rem;
                color: rgba(255, 255, 255, 0.72);
                font-weight: 500;
            }}
            
            .zone-tab:hover {{
                color: var(--text-primary);
                background: var(--glass);
            }}
            
            .zone-tab.active {{
                background: linear-gradient(135deg, var(--accent), var(--success));
                color: white;
                box-shadow: 0 10px 25px rgba(0, 217, 255, 0.25);
            }}

            .zone-tab.active .tab-meta {{
                color: rgba(255, 255, 255, 0.95);
            }}
            
            .zone-tab i {{
                font-size: 1.1rem;
                flex-shrink: 0;
            }}
            
            .zone-content {{
                display: none;
            }}
            
            .zone-content.active {{
                display: block;
            }}
            
            /* ===================================
               PRIVATE MODE SUB-TABS
               =================================== */
            
            .private-subtabs {{
                display: flex;
                gap: 0.75rem;
                margin-bottom: 1.5rem;
                padding: 0.5rem;
                background: var(--bg-tertiary);
                border: 1px solid var(--border);
                border-radius: var(--radius-lg);
            }}
            
            .private-subtab {{
                flex: 1;
                padding: 0.75rem 1.15rem;
                background: transparent;
                border: none;
                border-radius: var(--radius-md);
                color: var(--text-secondary);
                font-size: 0.9rem;
                font-weight: 600;
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 0.5rem;
                cursor: pointer;
                transition: all 0.3s ease;
                min-height: 46px;
            }}
            
            .private-subtab:hover {{
                color: var(--text-primary);
                background: var(--glass);
            }}
            
            .private-subtab.active {{
                background: linear-gradient(135deg, var(--accent), var(--success));
                color: white;
                box-shadow: 0 8px 18px rgba(0, 217, 255, 0.22);
            }}
            
            .private-subtab i {{
                font-size: 1rem;
                flex-shrink: 0;
            }}
            
            .private-section {{
                display: none;
                animation: fadeIn 0.3s ease;
            }}
            
            .private-section.active {{
                display: block;
            }}
            
            /* ===================================
               ATTENDANCE STYLES
               =================================== */
            
            .attendance-login-card {{
                max-width: 500px;
                margin: 3rem auto;
                background: var(--bg-secondary);
                border: 1px solid var(--border);
                border-radius: 22px;
                padding: 2.5rem;
                box-shadow: var(--shadow-soft);
            }}
            
            .login-header {{
                text-align: center;
                margin-bottom: 2rem;
            }}
            
            .login-icon {{
                width: 72px;
                height: 72px;
                margin: 0 auto 1.5rem;
                background: linear-gradient(135deg, var(--accent), var(--success));
                border-radius: 18px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 2rem;
                color: white;
                box-shadow: 0 15px 40px var(--accent-glow);
            }}
            
            .login-header h2 {{
                font-size: 1.6rem;
                font-weight: 700;
                color: var(--text-primary);
                margin-bottom: 0.5rem;
            }}
            
            .login-header p {{
                color: var(--text-tertiary);
                font-size: 0.9rem;
            }}
            
            .form-group {{
                margin-bottom: 1.25rem;
            }}
            
            .form-group label {{
                display: flex;
                align-items: center;
                gap: 0.5rem;
                margin-bottom: 0.45rem;
                color: var(--text-secondary);
                font-size: 0.85rem;
                font-weight: 600;
            }}
            
            .form-group input {{
                width: 100%;
                padding: 0.9rem 1rem;
                background: var(--bg-primary);
                border: 1px solid var(--border);
                border-radius: var(--radius-md);
                color: var(--text-primary);
                font-size: 0.95rem;
                transition: all 0.3s ease;
            }}
            
            .form-group input:focus {{
                border-color: var(--accent);
                box-shadow: 0 0 0 3px rgba(0, 217, 255, 0.2);
            }}
            
            .login-submit-btn {{
                width: 100%;
                padding: 0.95rem;
                background: linear-gradient(135deg, var(--accent), var(--success));
                border: none;
                border-radius: var(--radius-md);
                color: white;
                font-size: 0.95rem;
                font-weight: 700;
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 0.75rem;
                cursor: pointer;
                transition: all 0.3s ease;
                margin-bottom: 0.85rem;
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
                padding: 0.85rem 1rem;
                background: var(--glass);
                border-radius: var(--radius-sm);
                color: var(--text-tertiary);
                font-size: 0.8rem;
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
                margin-bottom: 1.1rem;
                color: var(--text-secondary);
                font-size: 0.85rem;
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
                margin-bottom: 1.5rem;
                padding-bottom: 0.85rem;
                border-bottom: 1px solid var(--border);
            }}
            
            .attendance-header h2 {{
                font-size: 1.35rem;
                font-weight: 700;
                color: var(--text-primary);
                display: flex;
                align-items: center;
                gap: 0.75rem;
                flex-wrap: wrap;
                min-width: 0;
            }}

            .attendance-header h2 i {{
                flex-shrink: 0;
            }}
            
            .logout-btn {{
                padding: 0.6rem 1.1rem;
                background: var(--glass);
                border: 1px solid var(--border);
                border-radius: var(--radius-md);
                color: var(--text-secondary);
                font-size: 0.85rem;
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

            .logout-confirm-modal .modal-content {{
                max-width: 460px;
                width: calc(100% - 2rem);
                border: 1px solid color-mix(in srgb, var(--accent) 40%, transparent);
                box-shadow: 0 30px 60px rgba(0, 0, 0, 0.5);
            }}

            .logout-confirm-body {{
                padding: 2rem;
                text-align: center;
            }}

            .logout-confirm-icon {{
                width: 74px;
                height: 74px;
                border-radius: 50%;
                margin: 0 auto 1rem auto;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 1.9rem;
                color: var(--accent);
                background: radial-gradient(circle at center, color-mix(in srgb, var(--accent) 24%, transparent), color-mix(in srgb, var(--accent) 10%, transparent));
                border: 1px solid color-mix(in srgb, var(--accent) 38%, transparent);
            }}

            .logout-confirm-body h3 {{
                margin: 0 0 0.55rem 0;
                font-size: 1.25rem;
                color: var(--text-primary);
            }}

            .logout-confirm-body p {{
                margin: 0;
                color: var(--text-secondary);
                font-size: 0.95rem;
                line-height: 1.55;
            }}

            .logout-confirm-actions {{
                margin-top: 1.4rem;
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 0.75rem;
            }}

            .logout-cancel-btn,
            .logout-confirm-btn {{
                border: 1px solid var(--border);
                border-radius: 12px;
                min-height: 42px;
                font-size: 0.9rem;
                font-weight: 700;
                cursor: pointer;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                gap: 0.45rem;
                transition: all 0.25s ease;
            }}

            .logout-cancel-btn {{
                background: var(--glass);
                color: var(--text-primary);
            }}

            .logout-cancel-btn:hover {{
                background: var(--bg-tertiary);
                transform: translateY(-1px);
            }}

            .logout-confirm-btn {{
                border-color: color-mix(in srgb, var(--accent) 45%, transparent);
                background: linear-gradient(135deg, var(--accent), var(--success));
                color: #fff;
            }}

            .logout-confirm-btn:hover {{
                transform: translateY(-1px);
                box-shadow: 0 12px 24px var(--accent-glow);
            }}
            
            .attendance-content-wrapper {{
                margin-top: 2rem;
            }}
            
            /* Beautiful card-based attendance display */
            .attendance-card {{
                background: var(--bg-secondary);
                border: 1px solid var(--border);
                border-radius: var(--radius-lg);
                padding: 1.5rem var(--card-pad-x);
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
                box-shadow: var(--shadow-accent);
            }}
            
            .attendance-card-header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                column-gap: 1.25rem;
                margin-bottom: 1.25rem;
                padding-bottom: 0.85rem;
                border-bottom: 1px solid var(--border);
            }}
            
            .module-info {{
                flex: 1;
                min-width: 0;
            }}
            
            .module-name {{
                font-size: 1.15rem;
                font-weight: 700;
                color: var(--text-primary);
                margin-bottom: 0.5rem;
                display: flex;
                align-items: center;
                gap: var(--icon-gap);
                word-break: break-word;
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
                gap: 0.6rem;
                flex-wrap: wrap;
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
                border-radius: var(--radius-md);
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
                margin-bottom: 1.5rem;
                padding: 1.25rem;
                background: var(--bg-secondary);
                border: 1px solid var(--border);
                border-radius: var(--radius-lg);
            }}
            
            .stat-item {{
                text-align: center;
                padding: 0.9rem;
                background: var(--glass);
                border-radius: var(--radius-md);
            }}
            
            .stat-item-value {{
                font-size: 1.9rem;
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
                content: '•';
                font-size: 1rem;
            }}
            
            /* ===================================
               RESULTS TABLE STYLES
               =================================== */
            
            .results-table-container {{
                background: var(--bg-secondary);
                border: 1px solid var(--border);
                border-radius: var(--radius-lg);
                overflow: hidden;
                margin-top: 1.5rem;
                box-shadow: 0 8px 30px rgba(0, 0, 0, 0.1);
            }}
            
            .results-table {{
                width: 100%;
                border-collapse: collapse;
                font-size: 0.92rem;
            }}
            
            .results-table thead {{
                background: linear-gradient(135deg, rgba(0, 217, 255, 0.1), rgba(0, 255, 136, 0.1));
                border-bottom: 2px solid var(--accent);
            }}
            
            .results-table thead th {{
                padding: 0.9rem 1rem;
                text-align: left;
                color: var(--text-primary);
                font-weight: 700;
                font-size: 0.82rem;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                white-space: nowrap;
            }}
            
            .results-table thead th i {{
                margin-right: 0.5rem;
                color: var(--accent);
            }}
            
            .results-table tbody tr {{
                border-bottom: 1px solid var(--border);
                transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
                will-change: background, transform;
            }}
            
            .results-table tbody tr:hover {{
                background: var(--glass);
                transform: translateX(2px);
            }}
            
            .results-table tbody td {{
                padding: 0.85rem 1rem;
                color: var(--text-secondary);
                vertical-align: middle;
            }}
            
            .results-table .row-number {{
                font-weight: 700;
                color: var(--text-tertiary);
                font-size: 0.9rem;
                width: 50px;
                text-align: center;
            }}
            
            .results-table .subject-cell {{
                font-weight: 600;
                color: var(--text-primary);
            }}
            
            .results-table .subject-cell strong {{
                display: block;
                color: var(--accent);
            }}
            
            .results-table .score-cell {{
                text-align: center;
            }}
            
            .score-badge {{
                display: inline-block;
                padding: 0.375rem 0.875rem;
                background: var(--bg-tertiary);
                color: var(--text-primary);
                border-radius: 20px;
                font-weight: 700;
                font-size: 0.9rem;
                border: 1px solid var(--border);
            }}
            
            .status-badge {{
                display: inline-flex;
                align-items: center;
                gap: 0.5rem;
                padding: 0.5rem 1rem;
                border-radius: 20px;
                font-weight: 600;
                font-size: 0.85rem;
                text-transform: uppercase;
                letter-spacing: 0.05em;
            }}
            
            .status-badge i {{
                font-size: 1rem;
            }}
            
            .status-passed {{
                background: rgba(0, 255, 136, 0.15);
                color: var(--success);
                border: 1px solid var(--success);
            }}
            
            .status-failed {{
                background: rgba(239, 68, 68, 0.15);
                color: #ef4444;
                border: 1px solid #ef4444;
            }}
            
            .status-pending {{
                background: rgba(255, 184, 0, 0.15);
                color: #ffb800;
                border: 1px solid #ffb800;
            }}
            
            .results-table .date-cell {{
                color: var(--text-tertiary);
                font-size: 0.9rem;
            }}
            
            /* Modern Subject Result Card Styles */
            .subject-result-card {{
                will-change: transform, box-shadow;
            }}
            
            .subject-result-card .card-header {{
                transition: background 0.3s ease;
            }}
            
            .subject-result-card .assessment-item {{
                will-change: border-color, background;
            }}
            
            .subject-result-card .assessment-grid {{
                animation: fadeIn 0.4s ease-out;
            }}
            
            @keyframes fadeIn {{
                from {{
                    opacity: 0;
                    transform: translateY(10px);
                }}
                to {{
                    opacity: 1;
                    transform: translateY(0);
                }}
            }}
            
            /* Responsive Modern Cards */
            @media (max-width: 1200px) {{
                .subject-result-card .card-body > div {{
                    grid-template-columns: 1fr !important;
                }}
                
                .subject-result-card .summary-panel {{
                    max-width: 100% !important;
                    display: grid !important;
                    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                    gap: 1rem;
                }}
                
                .subject-result-card .summary-panel > div {{
                    display: grid !important;
                    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                    gap: 1rem;
                    text-align: left !important;
                }}
                
                .subject-result-card .grade-display {{
                    margin-bottom: 0 !important;
                }}
            }}
            
            @media (max-width: 768px) {{
                .subject-result-card .card-header > div {{
                    flex-direction: column !important;
                    align-items: flex-start !important;
                }}
                
                .subject-result-card .status-badge-container {{
                    width: 100%;
                    justify-content: flex-start !important;
                }}
                
                .subject-result-card .assessment-grid {{
                    grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)) !important;
                }}
                
                .subject-result-card .card-body {{
                    padding: 1rem !important;
                }}
                
                .semester-results-table {{
                    padding: 1rem !important;
                }}
            }}
            
            @media (max-width: 480px) {{
                .subject-result-card .assessment-grid {{
                    grid-template-columns: 1fr 1fr !important;
                }}
                
                .subject-result-card .subject-number {{
                    width: 36px !important;
                    height: 36px !important;
                    font-size: 1rem !important;
                }}
                
                .subject-result-card .course-name {{
                    font-size: 0.95rem !important;
                }}
            }}
            
            /* Responsive table on mobile */
            @media (max-width: 1024px) {{
                .results-table-container {{
                    overflow-x: auto;
                }}
                
                .results-table {{
                    min-width: 650px;
                }}
                
                .results-table thead th {{
                    padding: 0.75rem 0.5rem;
                    font-size: 0.8rem;
                }}
                
                .results-table tbody td {{
                    padding: 0.75rem 0.5rem;
                    font-size: 0.85rem;
                }}
            }}
            
            @media (max-width: 768px) {{
                .results-table {{
                    font-size: 0.8rem;
                    min-width: 550px;
                }}
                
                .score-badge, .status-badge {{
                    padding: 0.25rem 0.625rem;
                    font-size: 0.75rem;
                }}
            }}
            
            /* Notification System - Top Smooth */
            .notification {{
                position: fixed;
                top: -90px;
                left: 50%;
                transform: translateX(-50%);
                background: var(--bg-secondary);
                border: 1px solid var(--border);
                border-radius: var(--radius-md);
                padding: 0.9rem 1.6rem;
                display: flex;
                align-items: center;
                gap: 0.75rem;
                box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4), 0 0 0 1px rgba(0, 217, 255, 0.2);
                backdrop-filter: blur(10px);
                z-index: 10000;
                transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
                min-width: 300px;
                max-width: 90vw;
            }}
            
            .notification.show {{
                top: 2rem;
            }}
            
            .notification-success {{
                border-left: 4px solid var(--success);
                background: linear-gradient(135deg, rgba(0, 255, 136, 0.1), var(--bg-secondary));
            }}
            
            .notification-success i {{
                color: var(--success);
                font-size: 1.3rem;
            }}
            
            .notification-error {{
                border-left: 4px solid #ef4444;
                background: linear-gradient(135deg, rgba(239, 68, 68, 0.1), var(--bg-secondary));
            }}
            
            .notification-error i {{
                color: #ef4444;
                font-size: 1.3rem;
            }}
            
            .notification span {{
                color: var(--text-primary);
                font-weight: 600;
                font-size: 0.92rem;
            }}
            
            /* Responsive */
            @media (max-width: 768px) {{
                .container {{ padding: 1.5rem 1rem; }}
                .nav {{
                    display: flex;
                    flex-direction: column;
                    gap: 0.75rem;
                    padding: 0.95rem 1rem;
                    text-align: center;
                }}
                .logo {{ justify-content: center; gap: 0.75rem; width: 100%; }}
                .logo-icon {{ width: 52px; height: 52px; font-size: 24px; border-radius: 14px; }}
                .logo-text h1 {{ font-size: 1.32rem; }}
                .nav-actions {{ width: 100%; justify-content: center; }}
                .kurdish-text {{ width: 100%; }}
                /* Hide install button on mobile - use browser menu instead */
                .install-btn {{
                    display: none !important;
                }}
                .kurdish-text {{ font-size: 0.9rem; width: 100%; min-height: 22px; }}
                .stats {{ grid-template-columns: 1fr; }}
                .toolbar {{ flex-direction: column; align-items: stretch; }}
                .search-box {{ min-width: 100%; }}
                .modal-content {{ max-width: 95%; margin: 1rem; }}
                .modal-header {{ padding: 1.5rem; }}
                .modal-body {{ padding: 1.5rem; }}
                .logout-confirm-modal .modal-content {{ width: calc(100% - 1.25rem); }}
                .logout-confirm-body {{ padding: 1.4rem 1.1rem 1.3rem 1.1rem; }}
                .logout-confirm-actions {{ grid-template-columns: 1fr; }}
                
                .zone-tabs {{ flex-direction: column; gap: 0.4rem; margin-bottom: 1.1rem; padding: 0.4rem; border-radius: 16px; }}
                .zone-tab {{ padding: 0.55rem 0.9rem; font-size: 0.88rem; border-radius: 12px; gap: 0.45rem; min-height: 44px; }}
                .zone-tab i {{ font-size: 0.95rem; }}
                .zone-tab .tab-meta {{ font-size: 0.72rem; }}
                .attendance-login-card {{ padding: 1.75rem 1.25rem; margin: 2.5rem auto; }}
                .attendance-header {{ flex-direction: column; gap: 1rem; align-items: flex-start; }}
                .private-subtabs {{ gap: 0.5rem; padding: 0.4rem; border-radius: 16px; }}
                .private-subtab {{ padding: 0.6rem 0.9rem; font-size: 0.85rem; min-height: 42px; }}
                
                /* Mobile-specific: Subject sections - better spacing */
                .subject-section {{
                    margin-bottom: 1.25rem;
                    border-radius: 16px;
                }}
                
                .subject-header {{
                    padding: var(--mobile-card-pad-y) var(--mobile-card-pad-x);
                    display: grid;
                    grid-template-columns: minmax(0, 1fr) auto;
                    align-items: center;
                    column-gap: 0.8rem;
                }}
                
                .subject-title {{
                    font-size: 1rem;
                    gap: 0.7rem;
                    flex-wrap: wrap;
                    width: 100%;
                    padding-right: 0;
                }}
                
                .subject-title i {{
                    font-size: 1.1rem;
                }}
                
                .file-count {{
                    font-size: 0.75rem;
                    padding: 0.3rem 0.7rem;
                    margin-left: 0;
                    white-space: nowrap;
                }}
                
                .collapse-btn {{
                    position: static;
                    justify-self: end;
                    width: 36px;
                    height: 36px;
                    margin-right: 0;
                }}
                
                /* Mobile-specific: File items - organized and comfortable */
                .subject-files {{
                    padding: var(--mobile-card-pad-y) var(--mobile-card-pad-x);
                }}
                
                .file-item {{
                    flex-direction: column;
                    align-items: stretch;
                    gap: 1rem;
                    padding: var(--mobile-card-pad-y) var(--mobile-card-pad-x);
                    margin-bottom: 1rem;
                }}
                
                .file-item:hover {{
                    transform: none;
                }}
                
                .file-icon {{
                    width: 48px;
                    height: 48px;
                    font-size: 1.3rem;
                    align-self: flex-start;
                }}
                
                .file-info {{
                    width: 100%;
                    padding-left: 0;
                }}
                
                .file-name {{
                    font-size: 0.95rem;
                    line-height: 1.5;
                    margin-bottom: 0.75rem;
                    word-break: break-word;
                    -webkit-line-clamp: 3;
                }}
                
                .file-meta {{
                    font-size: 0.85rem;
                    margin-top: 0.5rem;
                }}
                
                .file-size {{
                    width: 100%;
                    justify-content: flex-start;
                    padding: 0.75rem;
                    background: var(--glass);
                    border-radius: 8px;
                    font-size: 0.9rem;
                }}
                
                .download-btn,
                .summary-btn {{
                    width: 100%;
                    justify-content: center;
                    padding: 1rem;
                    font-size: 0.95rem;
                }}
                
                .summary-btn {{
                    margin-top: 0.5rem;
                }}
                
                .summarize-all-btn {{
                    width: 100%;
                    padding: 1rem;
                    font-size: 0.95rem;
                    margin-top: 0.75rem;
                }}
                
                /* Mobile-specific: Attendance section - better spacing and readability */
                .attendance-card {{
                    padding: 1.25rem var(--mobile-card-pad-x);
                    margin-bottom: 1.2rem;
                    border-radius: 16px;
                }}
                
                .attendance-card-header {{
                    flex-direction: column;
                    align-items: flex-start;
                    gap: 1.25rem;
                    margin-bottom: 1.25rem;
                    padding-bottom: 1.25rem;
                }}
                
                .module-info {{
                    width: 100%;
                }}
                
                .module-name {{
                    font-size: 1.1rem;
                    gap: 0.6rem;
                    line-height: 1.4;
                    flex-wrap: wrap;
                }}
                
                .module-name i {{
                    font-size: 1rem;
                }}
                
                .class-name {{
                    font-size: 0.9rem;
                    margin-top: 0.5rem;
                    line-height: 1.4;
                }}
                
                .absence-badge {{
                    min-width: 100%;
                    height: auto;
                    padding: 1.25rem;
                    flex-direction: row;
                    justify-content: space-between;
                    border-radius: 12px;
                }}
                
                .absence-count {{
                    font-size: 2.5rem;
                }}
                
                .absence-label {{
                    font-size: 0.85rem;
                }}
                
                .attendance-card-body {{
                    grid-template-columns: 1fr;
                    gap: 1rem;
                }}
                
                .attendance-detail {{
                    padding: 1rem;
                    gap: 1rem;
                }}
                
                .detail-icon {{
                    width: 44px;
                    height: 44px;
                    font-size: 1.2rem;
                }}
                
                .detail-label {{
                    font-size: 0.8rem;
                    margin-bottom: 0.35rem;
                }}
                
                .detail-value {{
                    font-size: 1rem;
                    line-height: 1.4;
                }}
                
                .attendance-stats {{
                    grid-template-columns: 1fr;
                    gap: 1rem;
                    padding: 1.25rem 1rem;
                    margin-bottom: 1.5rem;
                }}
                
                .stat-item {{
                    padding: 1.25rem 1rem;
                }}
                
                .stat-item-value {{
                    font-size: 2.1rem;
                    margin-bottom: 0.6rem;
                }}
                
                .stat-item-label {{
                    font-size: 0.9rem;
                    line-height: 1.3;
                }}
                
                .absence-list li {{
                    padding: 0.85rem;
                    margin-bottom: 0.5rem;
                    font-size: 0.95rem;
                    gap: 0.75rem;
                    line-height: 1.5;
                }}
                
                .absence-details-section {{
                    padding: 1.25rem 1rem;
                    margin-top: 1.25rem;
                }}
                
                .no-absences {{
                    padding: 3rem 1.5rem;
                }}
                
                .no-absences i {{
                    font-size: 3.5rem;
                    margin-bottom: 1.25rem;
                }}
                
                .no-absences h3 {{
                    font-size: 1.35rem;
                    margin-bottom: 0.75rem;
                    line-height: 1.4;
                }}
                
                .no-absences p {{
                    font-size: 0.95rem;
                    line-height: 1.5;
                }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <!-- Navigation -->
            <nav class="nav">
                <div class="logo">
                    <div class="logo-icon">
                        <i class="fas fa-bolt"></i>
                    </div>
                    <div class="logo-text">
                        <h1>SwiftSync</h1>
                        <!--<p>SSCreative</p>-->
                    </div>
                </div>
                
                <!-- Kurdish Text Animation (in navbar) -->
                <div class="kurdish-text" id="kurdishText"></div>
                
                <div class="nav-actions">
                    <!-- PWA Install Button -->
                    <button class="install-btn" id="pwaInstallBtn">
                        <i class="fas fa-download"></i>
                        <span>Install App</span>
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
                    <span class="tab-label">Lectures</span>
                    <span class="tab-meta">(Public)</span>
                </button>
                <button class="zone-tab" onclick="switchZone('private')" id="privateTab">
                    <i class="fas fa-user-shield"></i>
                    <span class="tab-label">Student Portal</span>
                    <span class="tab-meta">(Private)</span>
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
            <!-- PRIVATE MODE: Unified Attendance + Results -->
            <div id="privateZone" class="zone-content">
                <!-- Login Area (shared for both attendance and results) -->
                <div id="privateLoginArea">
                    <div class="attendance-login-card">
                        <div class="login-header">
                            <div class="login-icon">
                                <i class="fas fa-user-lock"></i>
                            </div>
                            <h2>Student Login</h2>
                            <p>Access your attendance records and exam results</p>
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
                                <input type="checkbox" id="rememberMe" />
                                <span>Keep me signed in on this device</span>
                            </label>
                            <button type="submit" class="login-submit-btn" id="loginSubmitBtn">
                                <i class="fas fa-sign-in-alt"></i>
                                <span>Login Securely</span>
                            </button>
                            <div class="login-note">
                                <i class="fas fa-bolt"></i>
                                <span>Each student must login with their own university account.</span>
                            </div>
                        </form>
                    </div>
                </div>
                
                <!-- Data Area (shown after login) -->
                <div id="privateDataArea" style="display: none;">
                    <div class="attendance-header">
                        <h2>
                            <i class="fas fa-user-graduate"></i> 
                            <span id="studentNameDisplay">Student Portal</span>
                        </h2>
                        <button class="logout-btn" onclick="openLogoutConfirmModal()">
                            <i class="fas fa-sign-out-alt"></i>
                            <span>Logout</span>
                        </button>
                    </div>
                    
                    <!-- Internal Sub-tabs for Attendance, Result Alerts & Results -->
                    <div class="private-subtabs">
                        <button class="private-subtab active" onclick="switchPrivateSection('attendance')" id="attendanceSubtab">
                            <i class="fas fa-user-check"></i>
                            <span>Attendance</span>
                        </button>
                        <button class="private-subtab" onclick="switchPrivateSection('result-alerts')" id="resultAlertsSubtab">
                            <i class="fas fa-bell"></i>
                            <span>Result Alerts</span>
                        </button>
                        <button class="private-subtab" onclick="switchPrivateSection('official-results')" id="officialResultsSubtab">
                            <i class="fas fa-trophy"></i>
                            <span>Results</span>
                        </button>
                    </div>
                    
                    <!-- Attendance Section -->
                    <div id="attendanceSection" class="private-section active">
                        <div id="attendanceContent" class="attendance-content-wrapper">
                            <!-- Attendance data will be rendered here -->
                        </div>
                    </div>
                    
                    <!-- Result Alerts Section (Notification-based) -->
                    <div id="resultAlertsSection" class="private-section">
                        <div id="resultsContent" class="attendance-content-wrapper">
                            <!-- Result alerts from notifications will be rendered here -->
                        </div>
                    </div>
                    
                    <!-- Official Results Section (StudentResult API) -->
                    <div id="officialResultsSection" class="private-section">
                        <div id="officialResultsContent" class="attendance-content-wrapper">
                            <!-- Official results from StudentResult endpoint will be rendered here -->
                        </div>
                    </div>
                </div>
            </div>
            <!-- End Private Zone -->
            
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

        <div id="logoutConfirmModal" class="modal logout-confirm-modal">
            <div class="modal-content">
                <div class="logout-confirm-body">
                    <div class="logout-confirm-icon">
                        <i class="fas fa-sign-out-alt"></i>
                    </div>
                    <h3>Confirm Logout</h3>
                    <p>You are about to sign out from your private student area. Do you want to continue?</p>
                    <div class="logout-confirm-actions">
                        <button type="button" class="logout-cancel-btn" onclick="closeLogoutConfirmModal()">
                            <i class="fas fa-arrow-left"></i>
                            <span>Stay Logged In</span>
                        </button>
                        <button type="button" class="logout-confirm-btn" onclick="confirmLogoutAttendance()">
                            <i class="fas fa-check"></i>
                            <span>Yes, Logout</span>
                        </button>
                    </div>
                </div>
            </div>
        </div>
        
        <script>
            // ===================================
            // GLOBAL VARIABLES - DECLARE FIRST
            // ===================================
            
            // Safe localStorage wrapper to prevent access errors
            var safeStorage = {{
                _setCookie: function(name, value, days) {{
                    var expires = "";
                    if (days) {{
                        var date = new Date();
                        date.setTime(date.getTime() + (days * 24 * 60 * 60 * 1000));
                        expires = "; expires=" + date.toUTCString();
                    }}
                    var isSecure = window.location.protocol === 'https:';
                    var sameSite = isSecure ? 'SameSite=None; Secure' : 'SameSite=Lax';
                    document.cookie = name + "=" + (value || "") + expires + "; path=/; " + sameSite;
                }},
                _getCookie: function(name) {{
                    var nameEQ = name + "=";
                    var ca = document.cookie.split(';');
                    for (var i = 0; i < ca.length; i++) {{
                        var c = ca[i];
                        while (c.charAt(0) == ' ') c = c.substring(1, c.length);
                        if (c.indexOf(nameEQ) == 0) return c.substring(nameEQ.length, c.length);
                    }}
                    return null;
                }},
                _deleteCookie: function(name) {{
                    document.cookie = name + '=; Path=/; Expires=Thu, 01 Jan 1970 00:00:01 GMT;';
                }},
                getItem: function(key) {{
                    try {{
                        var value = localStorage.getItem(key);
                        if (!value) {{
                            value = this._getCookie(key);
                            if (value) {{
                                try {{
                                    localStorage.setItem(key, value);
                                }} catch (e) {{}}
                            }}
                        }}
                        return value;
                    }} catch (e) {{
                        return this._getCookie(key);
                    }}
                }},
                setItem: function(key, value) {{
                    try {{
                        localStorage.setItem(key, value);
                        this._setCookie(key, value, 7);
                        return true;
                    }} catch (e) {{
                        this._setCookie(key, value, 7);
                        return false;
                    }}
                }},
                removeItem: function(key) {{
                    try {{
                        localStorage.removeItem(key);
                    }} catch (e) {{}}
                    this._deleteCookie(key);
                }}
            }};
            
            // Attendance variables - Use safe storage
            var attendanceSessionToken = null;
            var attendanceUsername = null;
            var attendanceRefreshInterval = null;
            var privateDataBootstrapped = false;
            
            // Data cache for private sections (cleared on logout)
            var cachedResultAlerts = null;
            var cachedOfficialResults = null;
            var cachedAttendanceData = null;

            // Cache timestamps (avoid immediate duplicate refreshes)
            var cachedResultAlertsAt = 0;
            var cachedOfficialResultsAt = 0;
            var cachedAttendanceAt = 0;

            // Prevent duplicate requests + prevent cross-user cache bleed
            var privateCacheOwnerKey = null;
            var inFlightAttendance = null;
            var inFlightResultAlerts = null;
            var inFlightOfficialResults = null;
            var inFlightPrivateBootstrap = null;

            // Security hardening: do not keep saved plaintext credentials in storage.
            safeStorage.removeItem('attendance_credentials');

            // LocalStorage-only persistence for private data (DO NOT use cookies)
            // This makes Result Alerts + Results behave like Attendance across refresh.
            // Bump when the shape/meaning of persisted private payloads changes
            var PRIVATE_CACHE_VERSION = 2;
            var PRIVATE_CACHE_PREFIX = 'swiftsync_private_cache_v' + PRIVATE_CACHE_VERSION;

            function localOnlyGet(key) {{
                try {{
                    return localStorage.getItem(key);
                }} catch (e) {{
                    return null;
                }}
            }}

            function localOnlySet(key, value) {{
                try {{
                    localStorage.setItem(key, value);
                    return true;
                }} catch (e) {{
                    return false;
                }}
            }}

            function localOnlyRemove(key) {{
                try {{
                    localStorage.removeItem(key);
                }} catch (e) {{}}
            }}

            function getPrivateCacheStorageKey(kind, ownerKey) {{
                const owner = ownerKey || privateCacheOwnerKey || getPrivateOwnerKey();
                if (!owner) return null;
                const safeOwner = encodeURIComponent(owner);
                return `${{PRIVATE_CACHE_PREFIX}}:${{safeOwner}}:${{kind}}`;
            }}

            function persistPrivateCache(kind, payload) {{
                const key = getPrivateCacheStorageKey(kind);
                if (!key) return false;
                const record = {{ v: PRIVATE_CACHE_VERSION, at: Date.now(), data: payload }};
                return localOnlySet(key, JSON.stringify(record));
            }}

            function readPersistedPrivateCache(kind) {{
                const key = getPrivateCacheStorageKey(kind);
                if (!key) return null;
                const raw = localOnlyGet(key);
                if (!raw) return null;
                try {{
                    const record = JSON.parse(raw);
                    if (!record || record.v !== PRIVATE_CACHE_VERSION) return null;
                    // Keep caches only within session duration window for safety
                    if (record.at && (Date.now() - record.at) > SESSION_DURATION) return null;
                    return record;
                }} catch (e) {{
                    return null;
                }}
            }}

            function purgePersistedPrivateCaches(ownerKey) {{
                const kinds = ['attendance', 'result_alerts', 'official_results'];
                kinds.forEach(kind => {{
                    const key = getPrivateCacheStorageKey(kind, ownerKey);
                    if (key) localOnlyRemove(key);
                }});
            }}

            function rehydratePrivateCaches() {{
                ensurePrivateCacheOwner();
                if (!privateCacheOwnerKey) return;

                const att = readPersistedPrivateCache('attendance');
                if (att && att.data && att.data.html) {{
                    cachedAttendanceData = att.data;
                    cachedAttendanceAt = att.at || 0;
                }}

                const alerts = readPersistedPrivateCache('result_alerts');
                if (alerts && alerts.data && Array.isArray(alerts.data.results)) {{
                    cachedResultAlerts = alerts.data;
                    cachedResultAlertsAt = alerts.at || 0;
                }}

                const results = readPersistedPrivateCache('official_results');
                if (results && Array.isArray(results.data)) {{
                    cachedOfficialResults = results.data;
                    cachedOfficialResultsAt = results.at || 0;
                }}
            }}

            function getPrivateOwnerKey() {{
                // Scope private caches to the currently authenticated identity
                return attendanceUsername || attendanceSessionToken || '';
            }}

            function clearPrivateCaches() {{
                cachedResultAlerts = null;
                cachedOfficialResults = null;
                cachedAttendanceData = null;
                cachedResultAlertsAt = 0;
                cachedOfficialResultsAt = 0;
                cachedAttendanceAt = 0;
                privateCacheOwnerKey = null;
                // Drop references to in-flight promises (results will be ignored via guards)
                inFlightAttendance = null;
                inFlightResultAlerts = null;
                inFlightOfficialResults = null;
                inFlightPrivateBootstrap = null;
            }}

            function ensurePrivateCacheOwner() {{
                const key = getPrivateOwnerKey();
                if (!key) return;
                if (privateCacheOwnerKey && privateCacheOwnerKey !== key) {{
                    const prev = privateCacheOwnerKey;
                    clearPrivateCaches();
                    // Safety: do not keep other student's cached private payloads around
                    purgePersistedPrivateCaches(prev);
                }}
                privateCacheOwnerKey = key;
            }}

            function shouldBackgroundRefresh(cachedAt, maxAgeMs = 30000) {{
                // Keep private datasets stable during session unless user explicitly logs out.
                return false;
            }}

            async function apiFetchJson(url, options = {{}}, retries = 2, timeoutMs = 20000) {{
                for (let attempt = 0; attempt <= retries; attempt++) {{
                    const controller = new AbortController();
                    const timer = setTimeout(() => controller.abort(), timeoutMs);
                    try {{
                        const requestHeaders = {{
                            'Content-Type': 'application/json',
                            'X-Requested-With': 'XMLHttpRequest',
                            ...(options.headers || {{}})
                        }};

                        // Mobile fallback: when cookie persistence is delayed/restricted,
                        // send token via header so private APIs still authenticate.
                        if (attendanceSessionToken && attendanceSessionToken !== 'cookie-session') {{
                            requestHeaders['Authorization'] = `Bearer ${{attendanceSessionToken}}`;
                            requestHeaders['X-Session-Token'] = attendanceSessionToken;
                        }}

                        const response = await fetch(url, {{
                            method: options.method || 'GET',
                            headers: requestHeaders,
                            body: options.body,
                            credentials: 'same-origin',
                            cache: 'no-store',
                            signal: controller.signal
                        }});
                        clearTimeout(timer);

                        if (!response.ok) {{
                            if (attempt < retries && response.status >= 500) {{
                                await new Promise(r => setTimeout(r, 250 * (attempt + 1)));
                                continue;
                            }}
                            throw new Error(`HTTP ${{response.status}}`);
                        }}

                        return await response.json();
                    }} catch (err) {{
                        clearTimeout(timer);
                        if (err && (err.name === 'AbortError' || String(err.message || '').toLowerCase().includes('aborted'))) {{
                            if (attempt < retries) {{
                                await new Promise(r => setTimeout(r, 350 * (attempt + 1)));
                                continue;
                            }}
                            throw new Error('Request timed out. The server may be waking up or the connection may be slow. Please wait a moment and try again.');
                        }}
                        if (attempt < retries) {{
                            await new Promise(r => setTimeout(r, 250 * (attempt + 1)));
                            continue;
                        }}
                        throw err;
                    }}
                }}
            }}

            function preloadPrivateData(options = {{}}) {{
                if (!attendanceSessionToken) return;
                ensurePrivateCacheOwner();

                const skipAttendance = options.skipAttendance === true;
                const forceRefresh = options.forceRefresh === true;
                if (!skipAttendance && !cachedAttendanceData && !inFlightAttendance) {{
                    // Silent load, no spinners (used mainly for session restore)
                    loadAttendanceData(true);
                }}

                if (!inFlightResultAlerts) {{
                    if (forceRefresh || !cachedResultAlerts) {{
                        fetchResultAlerts(true);
                    }}
                }}

                if (!inFlightOfficialResults) {{
                    if (forceRefresh || !cachedOfficialResults) {{
                        fetchOfficialResults(true);
                    }}
                }}
            }}

            async function preloadPrivateDataForLogin(options = {{}}) {{
                if (!attendanceSessionToken) {{
                    return {{ attendanceReady: false, resultAlertsReady: false, officialResultsReady: false }};
                }}

                const deferUiReveal = options.deferUiReveal !== false;
                const forceRefresh = options.forceRefresh === true;

                if (inFlightPrivateBootstrap) {{
                    return inFlightPrivateBootstrap;
                }}

                inFlightPrivateBootstrap = (async () => {{
                    // Start results fetches immediately so they can overlap with attendance loading.
                    const resultAlertsPromise = (forceRefresh || !cachedResultAlerts)
                        ? fetchResultAlerts(true).catch(() => false)
                        : Promise.resolve(true);
                    const officialResultsPromise = (forceRefresh || !cachedOfficialResults)
                        ? fetchOfficialResults(true).catch(() => false)
                        : Promise.resolve(true);

                    // 1) Prioritize attendance readiness for login UX.
                    let attendanceReady = false;
                    try {{
                        attendanceReady = await loadAttendanceData(false, deferUiReveal);
                    }} catch (_) {{
                        attendanceReady = false;
                    }}

                    // One short retry for flaky mobile networks / cookie propagation delay.
                    if (!attendanceReady) {{
                        await new Promise(r => setTimeout(r, 700));
                        try {{
                            attendanceReady = await loadAttendanceData(true, deferUiReveal);
                        }} catch (_) {{
                            attendanceReady = false;
                        }}
                    }}

                    // 2) Kick off results fetches in background; do not block login reveal.
                    const resultAlertsReady = (await resultAlertsPromise) || !!cachedResultAlerts;
                    const officialResultsReady = (await officialResultsPromise) || !!cachedOfficialResults;

                    return {{ attendanceReady, resultAlertsReady, officialResultsReady }};
                }})().finally(() => {{
                    inFlightPrivateBootstrap = null;
                }});

                return inFlightPrivateBootstrap;
            }}
            
            // Lectures data variables
            let allFilesData = {{}};
            let originalFilesData = {{}}; // Keep original data for search reset
            
            // ===================================
            // KURDISH TEXT ANIMATION
            // ===================================
            
            // Kurdish Text Typewriter Animation
            const kurdishTexts = [
                'جــەژنــتــــــان پــیــــرۆز بـــێــت',
                'E I D     M U B A R A K ',
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
            
            // Start animation immediately for smoother UX
            document.addEventListener('DOMContentLoaded', () => {{
                setTimeout(typeWriter, 100); // Start almost immediately
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
            
            // Session management - 7 days expiration
            var SESSION_DURATION = 7 * 24 * 60 * 60 * 1000; // 7 days in milliseconds
            
            // Session helper functions
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
                console.log('🎨 Rendering files...', data);
                // Only update original data on initial load, not during filtering
                if (!isFiltering) {{
                    allFilesData = data;
                    originalFilesData = JSON.parse(JSON.stringify(data)); // Deep copy
                }}
                const fileGrid = document.getElementById('fileGrid');
                const semesters = Object.keys(data);
                console.log('📚 Semesters found:', semesters);
                
                if (semesters.length === 0) {{
                    fileGrid.innerHTML = `
                        <div class="empty-state" style="padding: 3rem;">
                            <i class="fas fa-cloud-download-alt" style="font-size: 4rem; color: var(--primary); margin-bottom: 1rem;"></i>
                            <h3 style="color: var(--text-primary); margin-bottom: 0.5rem;">No Lectures Yet</h3>
                            <p style="color: var(--text-secondary); margin-bottom: 1.5rem;">Click "Sync Now" to fetch your latest lectures</p>
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
                let totalSubjects = 0;
                
                // Sort semesters (Fall first, then Spring)
                const semesterOrder = ['Fall Semester', 'Spring Semester'];
                const sortedSemesters = semesters.sort((a, b) => {{
                    const aIndex = semesterOrder.indexOf(a);
                    const bIndex = semesterOrder.indexOf(b);
                    if (aIndex === -1) return 1;
                    if (bIndex === -1) return -1;
                    return aIndex - bIndex;
                }});
                
                sortedSemesters.forEach(semester => {{
                    const subjects = data[semester];
                    const subjectNames = Object.keys(subjects);
                    totalSubjects += subjectNames.length;
                    
                    // Calculate semester stats
                    let semesterFiles = 0;
                    subjectNames.forEach(subject => {{
                        semesterFiles += subjects[subject].length;
                        subjects[subject].forEach(f => totalSize += f.size_bytes);
                    }});
                    totalFiles += semesterFiles;
                    
                    // Semester section (using same styling as subject-section)
                    html += `
                        <div class="subject-section" style="margin-bottom: 1.5rem;">
                            <div class="subject-header" onclick="toggleSemester(this)" style="background: linear-gradient(135deg, var(--primary) 0%, var(--secondary) 100%); cursor: pointer;">
                                <div class="subject-title" style="color: white; font-size: 1.1rem; font-weight: 700;">
                                    <i class="fas fa-calendar-alt" style="color: white;"></i>
                                    ${{semester}}
                                    <span class="file-count" style="background: rgba(255,255,255,0.2); color: white;">${{semesterFiles}} file${{semesterFiles > 1 ? 's' : ''}}</span>
                                </div>
                                <div class="collapse-btn">
                                    <i class="fas fa-chevron-down" style="color: white; transform: rotate(-90deg);"></i>
                                </div>
                            </div>
                            <div class="semester-content" style="display: none; padding-left: 0;">
                    `;
                    
                    // Subjects within semester
                    subjectNames.sort((a, b) => {{
                        const aIsOther = a.toLowerCase() === 'other';
                        const bIsOther = b.toLowerCase() === 'other';
                        if (aIsOther && !bIsOther) return 1;
                        if (!aIsOther && bIsOther) return -1;
                        return a.localeCompare(b);
                    }}).forEach(subject => {{
                        const files = subjects[subject];
                        
                        html += `
                            <div class="subject-section" style="margin: 0 1rem 1rem 1rem;">
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
                                            <a href="${{file.url}}" class="open-btn" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation();">
                                                <i class="fas fa-external-link-alt"></i>
                                                <span>Open</span>
                                            </a>
                                            <button class="download-btn" onclick="downloadFile('${{file.url}}', '${{file.name}}', event); return false;">
                                                <i class="fas fa-download"></i>
                                                <span>Download</span>
                                            </button>
                                        </div>
                                    `).join('')}}
                                </div>
                            </div>
                        `;
                    }});
                    
                    html += `
                            </div>
                        </div>
                    `;
                }});
                
                fileGrid.innerHTML = html;
                document.getElementById('totalFiles').textContent = totalFiles;
                document.getElementById('totalSize').textContent = formatBytes(totalSize);
                document.getElementById('totalSubjects').textContent = totalSubjects;
                console.log('✅ Stats updated:', {{totalFiles, totalSize, totalSubjects}});
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
            
            function toggleSemester(header) {{
                const section = header.closest('.subject-section');
                const content = section.querySelector('.semester-content');
                const icon = header.querySelector('.collapse-btn i');
                
                if (content.style.display === 'none') {{
                    content.style.display = 'block';
                    icon.style.transform = 'rotate(0deg)';
                }} else {{
                    content.style.display = 'none';
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
                // Search through semester → subject → files structure
                Object.keys(originalFilesData).forEach(semester => {{
                    const subjects = originalFilesData[semester];
                    Object.keys(subjects).forEach(subject => {{
                        const matchingFiles = subjects[subject].filter(file => 
                            file.name.toLowerCase().includes(query) ||
                            subject.toLowerCase().includes(query) ||
                            semester.toLowerCase().includes(query)
                        );
                        if (matchingFiles.length > 0) {{
                            if (!filtered[semester]) filtered[semester] = {{}};
                            filtered[semester][subject] = matchingFiles;
                        }}
                    }});
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
                        showNotification('Sync completed!', 'success');
                        loadFiles(); // Reload files
                    }} else {{
                        showNotification(`Sync failed: ${{result.error}}`, 'error');
                    }}
                }} catch (error) {{
                    showNotification(`Error: ${{error.message}}`, 'error');
                }} finally {{
                    btn.disabled = false;
                    icon.classList.remove('fa-spin');
                }}
            }}
            
            // Show Notification Function
            function showNotification(message, type = 'success') {{
                const notification = document.createElement('div');
                notification.className = `notification notification-${{type}}`;
                notification.innerHTML = `
                    <i class="fas fa-${{type === 'success' ? 'check-circle' : 'exclamation-circle'}}"></i>
                    <span>${{message}}</span>
                `;
                document.body.appendChild(notification);
                
                // Trigger animation
                setTimeout(() => notification.classList.add('show'), 100);
                
                // Remove after 3 seconds
                setTimeout(() => {{
                    notification.classList.remove('show');
                    setTimeout(() => notification.remove(), 400);
                }}, 3000);
            }}
            
            // Download File Function
            async function downloadFile(url, filename, event) {{
                if (event) {{
                    event.preventDefault();
                    event.stopPropagation();
                }}
                
                try {{
                    // OFFLINE CHECK: Don't attempt download if offline
                    if (!navigator.onLine) {{
                        showNotification('No internet connection', 'error');
                        return;
                    }}
                    
                    // Generate unique download URL with timestamp to prevent 'download again' dialog
                    const timestamp = new Date().getTime();
                    const downloadUrl = `/api/download/${{encodeURIComponent(filename)}}?_=${{timestamp}}`;
                    
                    // Fetch with strict no-cache policy
                    const response = await fetch(downloadUrl, {{
                        cache: 'no-store',
                        headers: {{
                            'Cache-Control': 'no-cache, no-store, must-revalidate',
                            'Pragma': 'no-cache'
                        }}
                    }});
                    
                    if (!response.ok) throw new Error('Download failed');
                    
                    const blob = await response.blob();
                    const blobUrl = URL.createObjectURL(blob);
                    
                    // Create hidden link and trigger download
                    const a = document.createElement('a');
                    a.style.display = 'none';
                    a.href = blobUrl;
                    a.download = filename;
                    document.body.appendChild(a);
                    
                    // MOBILE FIX: Only show notification after download actually starts
                    // No premature notification - let the browser handle the download
                    a.click();
                    
                    // Cleanup after reasonable time (no notification)
                    setTimeout(() => {{
                        document.body.removeChild(a);
                        URL.revokeObjectURL(blobUrl);
                    }}, 2000);
                }} catch (error) {{
                    // Only show notification on actual errors
                    showNotification('Download failed!', 'error');
                    console.error('Download error:', error);
                }}
            }}
            
            // Restore last active zone on page load (default to lectures)
            window.addEventListener('load', () => {{
                const lastZone = safeStorage.getItem('lastActiveZone');
                const lastPrivateSection = safeStorage.getItem('lastPrivateSection');
                
                // Always default to lectures unless explicitly on private
                if (lastZone && lastZone === 'private') {{
                    // Don't auto-switch to private, keep lectures as default
                }}
                
                // Restore last private section if applicable
                if (lastPrivateSection && (lastPrivateSection === 'result-alerts' || lastPrivateSection === 'official-results')) {{
                    // Will be restored when private mode is activated by checkAttendanceSession
                }}

                // Restore remembered login values for the private-zone login form.
                applySavedLoginPreference();
                
                // Lectures is already active by default in HTML
            }});
            
            // Load files on page load
            async function loadFiles() {{
                try {{
                    console.log('📡 Fetching lectures from API...');
                    
                    // OFFLINE CHECK: Show cached data or friendly message
                    if (!navigator.onLine) {{
                        console.log('📴 Offline - attempting to load cached data');
                    }}
                    
                    const response = await fetch('/api/files');
                    console.log('✅ API response received:', response.status);
                    
                    // Handle offline or network errors gracefully
                    if (!response.ok) {{
                        throw new Error(`HTTP ${{response.status}}: ${{response.statusText}}`);
                    }}
                    
                    const data = await response.json();
                    console.log('📊 Data loaded:', Object.keys(data).length, 'semesters');
                    renderFiles(data);
                }} catch (error) {{
                    console.error('❌ Error loading files:', error);
                    
                    // Friendly offline message without panic
                    const errorMsg = !navigator.onLine 
                        ? 'You are offline. Connect to internet to load lectures.'
                        : error.message;
                    
                    document.getElementById('fileGrid').innerHTML = `
                        <div class="empty-state">
                            <i class="fas fa-${{!navigator.onLine ? 'wifi-slash' : 'exclamation-triangle'}}"></i>
                            <h3>${{!navigator.onLine ? 'No Internet Connection' : 'Error Loading Files'}}</h3>
                            <p>${{errorMsg}}</p>
                            <button onclick="loadFiles()" style="margin-top: 1rem; padding: 0.5rem 1rem; background: var(--accent); color: white; border: none; border-radius: 8px; cursor: pointer;">
                                <i class="fas fa-sync"></i> Retry
                            </button>
                        </div>
                    `;
                }}
            }}
            
            // Initialize - Load files immediately  
            console.log('🚀 Initializing dashboard...');
            
            // Make sure DOM is fully loaded
            if (document.readyState === 'loading') {{
                document.addEventListener('DOMContentLoaded', () => {{
                    console.log('📄 DOM loaded, calling loadFiles()...');
                    loadFiles();
                }});
            }} else {{
                // DOM already loaded
                console.log('📄 DOM already ready, calling loadFiles()...');
                loadFiles();
            }}
            
            // ===== AI SUMMARIZATION FUNCTIONS =====
            
            function refreshBodyModalState() {{
                const activeModal = document.querySelector('.modal.active');
                document.body.style.overflow = activeModal ? 'hidden' : 'auto';
            }}

            function openSummaryModal() {{
                document.getElementById('summaryModal').classList.add('active');
                refreshBodyModalState();
            }}
            
            function closeSummaryModal() {{
                document.getElementById('summaryModal').classList.remove('active');
                refreshBodyModalState();
            }}

            function openLogoutConfirmModal() {{
                const logoutModal = document.getElementById('logoutConfirmModal');
                if (!logoutModal) {{
                    logoutAttendance(true);
                    return;
                }}
                logoutModal.classList.add('active');
                refreshBodyModalState();
            }}

            function closeLogoutConfirmModal() {{
                const logoutModal = document.getElementById('logoutConfirmModal');
                if (!logoutModal) return;
                logoutModal.classList.remove('active');
                refreshBodyModalState();
            }}

            function confirmLogoutAttendance() {{
                closeLogoutConfirmModal();
                logoutAttendance(true);
            }}
            
            // Close modal when clicking outside
            document.getElementById('summaryModal').addEventListener('click', (e) => {{
                if (e.target.id === 'summaryModal') {{
                    closeSummaryModal();
                }}
            }});

            const logoutConfirmModal = document.getElementById('logoutConfirmModal');
            if (logoutConfirmModal) {{
                logoutConfirmModal.addEventListener('click', (e) => {{
                    if (e.target.id === 'logoutConfirmModal') {{
                        closeLogoutConfirmModal();
                    }}
                }});
            }}
            
            // Close modal with Escape key
            document.addEventListener('keydown', (e) => {{
                if (e.key === 'Escape') {{
                    if (logoutConfirmModal && logoutConfirmModal.classList.contains('active')) {{
                        closeLogoutConfirmModal();
                    }} else {{
                        closeSummaryModal();
                    }}
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
            // GLOBAL VARIABLES - MUST BE DECLARED FIRST
            // ===================================
            
            // ===================================
            // ATTENDANCE SESSION MANAGEMENT
            // ===================================
            
            // Session management - already declared at top
            // SESSION_DURATION already defined
            
            // Session helper functions
            function updateSessionTimestamp() {{
                var timestamp = Date.now();
                safeStorage.setItem('attendance_session_timestamp', timestamp.toString());
                console.log('Session timestamp updated:', new Date(timestamp).toLocaleString());
            }}
            
            function isSessionExpired() {{
                var timestampStr = safeStorage.getItem('attendance_session_timestamp');
                if (!timestampStr) return true;
                
                var timestamp = parseInt(timestampStr);
                var now = Date.now();
                var elapsed = now - timestamp;
                
                if (elapsed > SESSION_DURATION) {{
                    console.log('Session expired:', elapsed / (1000 * 60 * 60 * 24), 'days old');
                    return true;
                }}
                return false;
            }}

            function applySavedLoginPreference() {{
                var savedUsername = safeStorage.getItem('attendance_saved_username');
                var rememberEnabled = safeStorage.getItem('attendance_remember_enabled') === 'true';
                var usernameInput = document.getElementById('attendanceUsername');
                var rememberCheckbox = document.getElementById('rememberMe');

                if (usernameInput && savedUsername) {{
                    usernameInput.value = savedUsername;
                }}

                if (rememberCheckbox) {{
                    rememberCheckbox.checked = rememberEnabled && !!savedUsername;
                }}
            }}
            
            // PWA install prompt
            var deferredPrompt = null;
            
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
                    safeStorage.setItem('lastActiveZone', 'lectures');
                }} else if (zone === 'private') {{
                    document.getElementById('privateTab').classList.add('active');
                    document.getElementById('privateZone').classList.add('active');
                    safeStorage.setItem('lastActiveZone', 'private');

                    // Avoid flashing the login form only when an active private session is expected.
                    if (safeStorage.getItem('attendance_session_active') === 'true') {{
                        showPrivateRestoreState();
                    }}
                    
                    // Check if user has a saved session
                    checkAttendanceSession();
                }}
            }}

            function showPrivateRestoreState() {{
                document.getElementById('privateLoginArea').style.display = 'none';
                document.getElementById('privateDataArea').style.display = 'block';
                switchPrivateSection('attendance');
                document.getElementById('attendanceContent').innerHTML = `
                    <div class="loading">
                        <div class="spinner"></div>
                        <p style="color: var(--text-secondary)">Restoring your secure session...</p>
                    </div>
                `;
            }}
            
            // Switch between Attendance, Result Alerts, and Official Results within Private Mode
            function switchPrivateSection(section) {{
                // Update subtabs
                document.querySelectorAll('.private-subtab').forEach(tab => tab.classList.remove('active'));
                document.querySelectorAll('.private-section').forEach(content => content.classList.remove('active'));
                
                if (section === 'attendance') {{
                    document.getElementById('attendanceSubtab').classList.add('active');
                    document.getElementById('attendanceSection').classList.add('active');
                    safeStorage.setItem('lastPrivateSection', 'attendance');
                }} else if (section === 'result-alerts') {{
                    document.getElementById('resultAlertsSubtab').classList.add('active');
                    document.getElementById('resultAlertsSection').classList.add('active');
                    safeStorage.setItem('lastPrivateSection', 'result-alerts');
                    
                    // Load result alerts - use cache if available
                    if (attendanceSessionToken) {{
                        if (cachedResultAlerts) {{
                            // Instantly show cached data
                            renderResultsCards(cachedResultAlerts.results, cachedResultAlerts.totalCount);
                        }} else if (inFlightResultAlerts) {{
                            // Preload already running - show loading UI but don't duplicate request
                            document.getElementById('resultsContent').innerHTML = `
                                <div class="loading">
                                    <div class="spinner"></div>
                                    <p style="color: var(--text-secondary)">Loading result alerts...</p>
                                </div>
                            `;
                        }} else {{
                            // First load - fetch with loading spinner
                            fetchResultAlerts(false);
                        }}
                    }}
                }} else if (section === 'official-results') {{
                    document.getElementById('officialResultsSubtab').classList.add('active');
                    document.getElementById('officialResultsSection').classList.add('active');
                    safeStorage.setItem('lastPrivateSection', 'official-results');
                    
                    // Load official results - use cache if available
                    if (attendanceSessionToken) {{
                        if (cachedOfficialResults) {{
                            // Instantly show cached data
                            renderOfficialResults(cachedOfficialResults);
                        }} else if (inFlightOfficialResults) {{
                            // Preload already running - show loading UI but don't duplicate request
                            document.getElementById('officialResultsContent').innerHTML = `
                                <div class="loading">
                                    <div class="spinner"></div>
                                    <p style="color: var(--text-secondary)">Loading official results...</p>
                                </div>
                            `;
                        }} else {{
                            // First load - fetch with loading spinner
                            fetchOfficialResults(false);
                        }}
                    }}
                }}
            }}
            
            // ===================================
            // ATTENDANCE FUNCTIONS
            // ===================================
            
            async function checkAttendanceSession() {{
                // Cookie-first restore: rely on server-side session cookie as source of truth.
                if (!attendanceSessionToken) {{
                    if (safeStorage.getItem('attendance_session_active') === 'true') {{
                        attendanceSessionToken = 'cookie-session';
                        attendanceUsername = safeStorage.getItem('attendance_username') || safeStorage.getItem('attendance_saved_username');
                    }}
                }}

                // For token-based fallback sessions, keep client-side expiry check.
                if (attendanceSessionToken && attendanceSessionToken !== 'cookie-session' && isSessionExpired()) {{
                    console.log('Session expired, clearing...');
                    // Clear expired session
                    // Purge persisted private caches for this user
                    purgePersistedPrivateCaches(getPrivateOwnerKey());
                    attendanceSessionToken = null;
                    safeStorage.removeItem('attendance_session_active');
                    safeStorage.removeItem('attendance_session_timestamp');
                    safeStorage.removeItem('attendance_username');
                }}
                
                if (attendanceSessionToken) {{
                    // User has a valid session, try to load attendance data
                    updateSessionTimestamp(); // Refresh session
                    ensurePrivateCacheOwner();

                    // Rehydrate all private caches from localStorage so tabs are instant after refresh
                    rehydratePrivateCaches();

                    // If we already have cached attendance, paint instantly and keep data stable.
                    if (cachedAttendanceData && cachedAttendanceData.html) {{
                        document.getElementById('privateLoginArea').style.display = 'none';
                        document.getElementById('privateDataArea').style.display = 'block';
                        switchPrivateSection('attendance');
                        renderAttendanceCards(cachedAttendanceData.html, cachedAttendanceData.fullName || attendanceUsername);

                        if (cachedResultAlerts) {{
                            renderResultsCards(cachedResultAlerts.results, cachedResultAlerts.totalCount);
                        }}
                        if (cachedOfficialResults) {{
                            renderOfficialResults(cachedOfficialResults);
                        }}

                        if (!privateDataBootstrapped) {{
                            preloadPrivateData({{ skipAttendance: true, forceRefresh: false }});
                            privateDataBootstrapped = true;
                        }}
                    }} else {{
                        const prefetchState = await preloadPrivateDataForLogin({{ deferUiReveal: true, forceRefresh: false }});
                        if (attendanceSessionToken && prefetchState.attendanceReady) {{
                            document.getElementById('privateLoginArea').style.display = 'none';
                            document.getElementById('privateDataArea').style.display = 'block';
                            privateDataBootstrapped = true;

                            // Product requirement: always open Attendance on session restore.
                            switchPrivateSection('attendance');
                        }} else {{
                            // Cookie/session restore failed on server; return to explicit login state.
                            attendanceSessionToken = null;
                            safeStorage.removeItem('attendance_session_active');
                            safeStorage.removeItem('attendance_session_timestamp');
                        }}
                    }}

                    // Keep data fixed during active session (no periodic forced reloads).
                    stopAttendanceAutoRefresh();
                }} else {{
                    // Show login form
                    document.getElementById('privateLoginArea').style.display = 'block';
                    document.getElementById('privateDataArea').style.display = 'none';
                    applySavedLoginPreference();
                }}
            }}
            
            function startAttendanceAutoRefresh() {{
                // Clear any existing interval
                if (attendanceRefreshInterval) {{
                    clearInterval(attendanceRefreshInterval);
                }}

                // Intentionally disabled to keep private data stable until explicit logout.
                attendanceRefreshInterval = null;
            }}
            
            function stopAttendanceAutoRefresh() {{
                if (attendanceRefreshInterval) {{
                    clearInterval(attendanceRefreshInterval);
                    attendanceRefreshInterval = null;
                }}
            }}
            
            async function loginAttendance(event) {{
                event.preventDefault();
                
                var username = document.getElementById('attendanceUsername').value.trim();
                var password = document.getElementById('attendancePassword').value;
                var rememberMe = document.getElementById('rememberMe').checked;
                var submitBtn = document.getElementById('loginSubmitBtn');
                
                if (!username || !password) {{
                    showNotification('Please enter both username and password.', 'error');
                    return;
                }}
                
                // Show loading state
                submitBtn.disabled = true;
                submitBtn.classList.add('loading');
                submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i><span>Authenticating...</span>';
                
                try {{
                    var result = await apiFetchJson('/api/attendance/login', {{
                        method: 'POST',
                        body: JSON.stringify({{ username: username, password: password, remember_me: rememberMe }})
                    }}, 2, 90000);
                    
                    if (result.success) {{
                        // Save session token
                        attendanceSessionToken = result.session_token || 'cookie-session';
                        attendanceUsername = result.username;

                        // New authenticated identity: scope caches to this user
                        ensurePrivateCacheOwner();

                        // If this student has persisted caches from a previous session, rehydrate for instant tabs
                        rehydratePrivateCaches();
                        
                        // Set session timestamp (7 days expiration)
                        updateSessionTimestamp();
                        
                        // Security: store only username preference, never password.
                        if (rememberMe) {{
                            safeStorage.setItem('attendance_saved_username', username);
                            safeStorage.setItem('attendance_remember_enabled', 'true');
                            safeStorage.setItem('attendance_session_active', 'true');
                            safeStorage.setItem('attendance_username', result.username || username);
                        }} else {{
                            safeStorage.removeItem('attendance_saved_username');
                            safeStorage.removeItem('attendance_remember_enabled');
                            safeStorage.removeItem('attendance_session_active');
                            safeStorage.removeItem('attendance_username');
                        }}

                        // Fetch ALL private data during login loading, so tabs are instant after login.
                        submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i><span>Loading your data...</span>';

                        // Start private prefetch during login, but do not block authenticated entry on slow mobile networks.
                        const prefetchState = await preloadPrivateDataForLogin({{ deferUiReveal: true, forceRefresh: true }});
                        privateDataBootstrapped = true;

                        // Now reveal private mode UI (everything should be ready)
                        document.getElementById('privateLoginArea').style.display = 'none';
                        document.getElementById('privateDataArea').style.display = 'block';

                        // Product requirement: always open Attendance after login.
                        switchPrivateSection('attendance');

                        if (!prefetchState.attendanceReady) {{
                            document.getElementById('attendanceContent').innerHTML = `
                                <div class="empty-state">
                                    <i class="fas fa-exclamation-triangle"></i>
                                    <h3>Attendance Is Still Loading</h3>
                                    <p>Login succeeded. Tap retry to load attendance data.</p>
                                    <button onclick="loadAttendanceData(false, false)" style="margin-top: 1rem; padding: 0.6rem 1rem; background: var(--accent); color: #fff; border: none; border-radius: 10px; cursor: pointer;">
                                        <i class="fas fa-sync"></i> Retry Attendance
                                    </button>
                                </div>
                            `;
                        }}

                        if (!prefetchState.resultAlertsReady || !prefetchState.officialResultsReady) {{
                            console.warn('Some private sections are still loading in background; tab switch will auto-retry.');
                        }}
                        
                        // Keep private data fixed during active session.
                        stopAttendanceAutoRefresh();
                        
                        console.log('✅ Login successful - session valid for 7 days');
                    }} else {{
                        showNotification(`Login failed: ${{result.error}}`, 'error');

                        // Safety: ensure stale private caches aren't kept after failed login
                        clearPrivateCaches();
                        purgePersistedPrivateCaches(username);

                        // Reset button
                        submitBtn.disabled = false;
                        submitBtn.classList.remove('loading');
                        submitBtn.innerHTML = '<i class="fas fa-sign-in-alt"></i><span>Login Securely</span>';
                    }}
                }} catch (error) {{
                    showNotification(`Login error: ${{error.message}}`, 'error');

                    // Safety: ensure stale private caches aren't kept after failed login
                    clearPrivateCaches();
                    purgePersistedPrivateCaches(username);

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
            
            async function loadAttendanceData(silentRefresh = false, deferUiReveal = false) {{
                if (!attendanceSessionToken) {{
                    return false;
                }}

                ensurePrivateCacheOwner();

                // Deduplicate concurrent loads (preload + tab switches + auto-refresh)
                if (inFlightAttendance) {{
                    if (!silentRefresh && !cachedAttendanceData) {{
                        document.getElementById('attendanceContent').innerHTML = `
                            <div class="loading">
                                <div class="spinner"></div>
                                <p style="color: var(--text-secondary)">Loading attendance data...</p>
                            </div>
                        `;
                    }}
                    return inFlightAttendance;
                }}
                
                if (!deferUiReveal) {{
                    // Show private data area with loading (unless silent refresh)
                    document.getElementById('privateLoginArea').style.display = 'none';
                    document.getElementById('privateDataArea').style.display = 'block';
                }}
                
                if (!silentRefresh) {{
                    document.getElementById('attendanceContent').innerHTML = `
                        <div class="loading">
                            <div class="spinner"></div>
                            <p style="color: var(--text-secondary)">Loading attendance data...</p>
                        </div>
                    `;
                }}
                
                const requestToken = attendanceSessionToken;
                const requestOwnerKey = getPrivateOwnerKey();

                inFlightAttendance = (async () => {{
                    let loadedSuccessfully = false;
                    try {{
                        // Fetch attendance data first
                        const attendanceResult = await apiFetchJson('/api/attendance/data', {{}}, 2, 25000);
                    
                        // If user logged out / switched user while request was in-flight, ignore results
                        if (attendanceSessionToken !== requestToken || getPrivateOwnerKey() !== requestOwnerKey) {{
                            return;
                        }}

                        if (attendanceResult.success) {{
                        // Refresh session timestamp on successful data load
                        updateSessionTimestamp();
                        
                        // Try to fetch profile (but don't fail if it doesn't work)
                        let fullName = attendanceUsername;
                        
                        // First, check if we extracted name from attendance HTML
                        if (attendanceResult.extracted_name) {{
                            fullName = attendanceResult.extracted_name;
                        }} else {{
                            // Try to fetch from profile API
                            try {{
                                const profileResult = await apiFetchJson('/api/attendance/profile', {{}}, 1, 9000);
                                
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
                        
                            // Cache for instant future loads in this session
                            cachedAttendanceData = {{ html: attendanceResult.html, fullName: fullName }};
                            cachedAttendanceAt = Date.now();
                            persistPrivateCache('attendance', cachedAttendanceData);

                            // Parse HTML and create beautiful cards
                            await renderAttendanceCards(attendanceResult.html, fullName);
                                loadedSuccessfully = true;
                    }} else {{
                        // Session expired or error
                        if (attendanceResult.error && attendanceResult.error.toLowerCase().includes('expired')) {{
                            logoutAttendance(true);
                            showNotification('Session expired. Please login again.', 'error');
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
                        // If user logged out / switched user while request was in-flight, ignore UI updates
                        if (attendanceSessionToken !== requestToken || getPrivateOwnerKey() !== requestOwnerKey) {{
                            return;
                        }}

                        if (String(error && error.message || '').includes('HTTP 401')) {{
                            logoutAttendance(true);
                            showNotification('Your session has ended. Please login again.', 'error');
                            return false;
                        }}

                        document.getElementById('attendanceContent').innerHTML = `
                        <div class="empty-state">
                            <i class="fas fa-exclamation-triangle"></i>
                            <h3>Error Loading Attendance</h3>
                            <p>${{error.message}}</p>
                        </div>
                    `;
                    }}
                    return loadedSuccessfully;
                }})().finally(() => {{
                    inFlightAttendance = null;
                }});

                return inFlightAttendance;
            }}
            
            async function logoutAttendance(forceImmediate = false) {{
                if (!forceImmediate) {{
                    openLogoutConfirmModal();
                    return;
                }}

                closeLogoutConfirmModal();

                // Stop auto-refresh
                stopAttendanceAutoRefresh();

                // Purge persisted private caches for this student (must happen before we clear identity)
                purgePersistedPrivateCaches(getPrivateOwnerKey());
                
                if (attendanceSessionToken) {{
                    try {{
                        await fetch('/api/attendance/logout', {{
                            method: 'POST'
                        }});
                    }} catch (error) {{
                        console.error('Logout error:', error);
                    }}
                }}
                
                // Clear session and saved credentials
                attendanceSessionToken = null;
                attendanceUsername = null;
                safeStorage.removeItem('attendance_session_active');
                safeStorage.removeItem('attendance_username');
                safeStorage.removeItem('attendance_credentials');
                safeStorage.removeItem('attendance_session_timestamp');
                if (safeStorage.getItem('attendance_remember_enabled') !== 'true') {{
                    safeStorage.removeItem('attendance_saved_username');
                }}
                privateDataBootstrapped = false;
                
                // Clear all cached private data
                clearPrivateCaches();
                
                // Reset form
                document.getElementById('attendanceLoginForm').reset();
                applySavedLoginPreference();
                document.getElementById('loginSubmitBtn').disabled = false;
                document.getElementById('loginSubmitBtn').classList.remove('loading');
                document.getElementById('loginSubmitBtn').innerHTML = '<i class="fas fa-sign-in-alt"></i><span>Login Securely</span>';
                document.getElementById('loginSubmitBtn').innerHTML = '<i class="fas fa-sign-in-alt"></i><span>Login Securely</span>';
                
                // Show login area
                document.getElementById('privateLoginArea').style.display = 'block';
                document.getElementById('privateDataArea').style.display = 'none';
                
                // Switch back to lectures zone
                switchZone('lectures');
            }}
            
            // ===================================
            // RESULT ALERTS FUNCTIONS (Notification-based)
            // ===================================
            
            async function fetchResultAlerts(silentRefresh = false) {{
                if (!attendanceSessionToken) {{
                    return false;
                }}

                ensurePrivateCacheOwner();

                // Deduplicate concurrent loads
                if (inFlightResultAlerts) {{
                    if (!silentRefresh && !cachedResultAlerts) {{
                        document.getElementById('resultsContent').innerHTML = `
                            <div class="loading">
                                <div class="spinner"></div>
                                <p style="color: var(--text-secondary)">Loading result alerts from notifications...</p>
                            </div>
                        `;
                    }}
                    return inFlightResultAlerts;
                }}
                
                if (!silentRefresh) {{
                    document.getElementById('resultsContent').innerHTML = `
                        <div class="loading">
                            <div class="spinner"></div>
                            <p style="color: var(--text-secondary)">Loading result alerts from notifications...</p>
                        </div>
                    `;
                }}
                
                const requestToken = attendanceSessionToken;
                const requestOwnerKey = getPrivateOwnerKey();

                inFlightResultAlerts = (async () => {{
                    let loadedSuccessfully = false;
                    try {{
                        const result = await apiFetchJson('/api/results/data', {{}}, 2, 30000);
                    
                        // If user logged out / switched user while request was in-flight, ignore results
                        if (attendanceSessionToken !== requestToken || getPrivateOwnerKey() !== requestOwnerKey) {{
                            return;
                        }}

                        if (result.success) {{
                        // Refresh session timestamp on successful data load
                        updateSessionTimestamp();
                        
                        // Cache the data for instant future loads
                        cachedResultAlerts = {{
                            results: result.results || [],
                            totalCount: result.total_count || 0
                        }};
                        cachedResultAlertsAt = Date.now();
                        persistPrivateCache('result_alerts', cachedResultAlerts);
                        
                        // Render results cards
                        renderResultsCards(cachedResultAlerts.results, cachedResultAlerts.totalCount);
                        loadedSuccessfully = true;
                    }} else {{
                        // Session expired or error
                        if (result.error && result.error.toLowerCase().includes('expired')) {{
                            logoutAttendance(true);
                            showNotification('Session expired. Please login again.', 'error');
                        }} else {{
                            document.getElementById('resultsContent').innerHTML = `
                                <div class="empty-state">
                                    <i class="fas fa-exclamation-triangle"></i>
                                    <h3>Error Loading Result Alerts</h3>
                                    <p>${{result.error}}</p>
                                </div>
                            `;
                        }}
                        }}
                    }} catch (error) {{
                        // If user logged out / switched user while request was in-flight, ignore UI updates
                        if (attendanceSessionToken !== requestToken || getPrivateOwnerKey() !== requestOwnerKey) {{
                            return;
                        }}

                        if (String(error && error.message || '').includes('HTTP 401')) {{
                            logoutAttendance(true);
                            showNotification('Your session has ended. Please login again.', 'error');
                            return false;
                        }}

                        document.getElementById('resultsContent').innerHTML = `
                        <div class="empty-state">
                            <i class="fas fa-exclamation-triangle"></i>
                            <h3>Error Loading Results</h3>
                            <p>${{error.message}}</p>
                        </div>
                    `;
                    }}
                    return loadedSuccessfully;
                }})().finally(() => {{
                    inFlightResultAlerts = null;
                }});

                return inFlightResultAlerts;
            }}
            
            function renderResultsCards(results, totalCount) {{
                const container = document.getElementById('resultsContent');
                
                if (results.length === 0) {{
                    container.innerHTML = `
                        <div class="no-absences">
                            <i class="fas fa-bell-slash"></i>
                            <h3>No Results Found</h3>
                            <p>No result-related notifications found in your feed yet.</p>
                            <div class="login-note" style="margin-top: 1rem;">
                                <i class="fas fa-info-circle"></i>
                                <span>Results appear here when published by the college as notifications</span>
                            </div>
                        </div>
                    `;
                    return;
                }}
                
                // Build stats (kept for potential future use, but no
                // longer rendered as a separate summary row in the
                // Result Alerts section to keep the UI consistent with
                // the main Results view.
                const passedCount = results.filter(r => r.status === 'passed').length;
                const failedCount = results.filter(r => r.status === 'failed').length;
                const unknownCount = results.length - passedCount - failedCount;

                // Start without a top summary row so that Result Alerts
                // focuses on the per-semester breakdown only.
                let htmlContent = '';
                
                function getSemesterDisplay(result) {{
                    // Prefer backend canonical label when available.
                    if (result && result.semester_display) return result.semester_display;

                    const combined = `${{result?.semester || ''}} ${{result?.raw_text || ''}}`.toLowerCase();
                    const inCurrentYear = combined.includes('2025-2026') || combined.includes('25-26');
                    if (!inCurrentYear) return null;

                    const isFall = /(?:_f_|\bfall\b|\b1st\s+semester\b|\bfirst\s+semester\b)/i.test(combined);
                    const isSpring = /(?:_s_|\bspring\b|\b2nd\s+semester\b|\bsecond\s+semester\b)/i.test(combined);

                    if (isFall) return '2025-2026 Fall Semester';
                    if (isSpring) return '2025-2026 Spring Semester';
                    return null;
                }}

                // Group results by canonical semester display name.
                const resultsBySemester = {{}};
                results.forEach(result => {{
                    const displaySemester = getSemesterDisplay(result);
                    
                    // Skip results without valid semester
                    if (!displaySemester) {{
                        return;
                    }}
                    
                    if (!resultsBySemester[displaySemester]) {{
                        resultsBySemester[displaySemester] = [];
                    }}
                    resultsBySemester[displaySemester].push(result);
                }});
                
                // Check if no valid results after filtering
                if (Object.keys(resultsBySemester).length === 0) {{
                    container.innerHTML += `
                        <div class="no-absences" style="margin-top: 2rem;">
                            <i class="fas fa-info-circle"></i>
                            <h3>No Results Available</h3>
                            <p>Results will appear here once semester information is available.</p>
                        </div>
                    `;
                    return;
                }}
                
                // Keep fixed academic order.
                const sortedSemesters = Object.keys(resultsBySemester).sort((a, b) => {{
                    const order = {{
                        '2025-2026 Fall Semester': 1,
                        '2025-2026 Spring Semester': 2,
                    }};
                    return (order[a] || 99) - (order[b] || 99);
                }});
                
                // Render each semester section
                sortedSemesters.forEach((semesterDisplayName, semesterIdx) => {{
                    const semesterResults = resultsBySemester[semesterDisplayName];
                    
                    htmlContent += `
                        <div class="subject-section" style="margin: 0 1rem 1.5rem 1rem;">
                            <div class="subject-header" onclick="toggleResultsSemester(this)" style="background: linear-gradient(135deg, var(--primary) 0%, var(--secondary) 100%); cursor: pointer;">
                                <div class="subject-title" style="color: white; font-size: 1.1rem; font-weight: 700;">
                                    <i class="fas fa-graduation-cap" style="color: white;"></i>
                                    ${{semesterDisplayName}}
                                    <span class="file-count" style="background: rgba(255,255,255,0.2); color: white;">${{semesterResults.length}} result${{semesterResults.length > 1 ? 's' : ''}}</span>
                                </div>
                                <div class="collapse-btn">
                                    <i class="fas fa-chevron-down" style="color: white; transform: rotate(-90deg); transition: transform 0.3s ease;"></i>
                                </div>
                            </div>
                            <div class="semester-results-content" style="display: none; padding: 0; transition: all 0.3s ease;">
                                <div class="results-table-container">
                                    <table class="results-table">
                                        <thead>
                                            <tr>
                                                <th>No.</th>
                                                <th><i class="fas fa-book"></i> Subject</th>
                                                <th><i class="fas fa-clipboard-list"></i> Exam Type</th>
                                                <th><i class="fas fa-star"></i> Score</th>
                                                <th><i class="fas fa-calendar-alt"></i> Date</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                    `;
                    
                    // Build table rows for this semester (newest first - already sorted from backend)
                    // Reset numbering for each semester
                    let rowIndex = 1;
                    semesterResults.forEach((result) => {{
                        // Format date
                        let formattedDate = 'N/A';
                        if (result.date) {{
                            try {{
                                const dateObj = new Date(result.date);
                                if (!isNaN(dateObj.getTime())) {{
                                    formattedDate = dateObj.toLocaleDateString('en-US', {{
                                        year: 'numeric',
                                        month: 'short',
                                        day: 'numeric'
                                    }});
                                }}
                            }} catch (e) {{
                                formattedDate = result.date;
                            }}
                        }}
                        
                        htmlContent += `
                            <tr class="result-row">
                                <td class="row-number">${{rowIndex}}</td>
                                <td class="subject-cell">
                                    <strong>${{result.subject || '-'}}</strong>
                                </td>
                                <td>${{result.exam_type || '-'}}</td>
                                <td class="score-cell">
                                    <span class="score-badge">${{result.score || '-'}}</span>
                                </td>
                                <td style="color: var(--text-tertiary); font-size: 0.9rem;">${{formattedDate}}</td>
                            </tr>
                        `;
                        rowIndex++;
                    }});
                    
                    htmlContent += `
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        </div>
                    `;
                }});
                
                container.innerHTML = htmlContent;
            }}
            
            // Unified toggle function for all collapsible sections (Result Alerts)
            function toggleResultsSemester(header) {{
                const section = header.closest('.subject-section');
                const icon = header.querySelector('.collapse-btn i');
                
                // Smart detection: try multiple content selectors
                let content = section.querySelector('.semester-results-content');
                if (!content) {{
                    content = section.querySelector('.semester-results-table');
                }}
                if (!content) {{
                    content = section.querySelector('.subject-files');
                }}
                
                if (!content) return; // Safety check
                
                // Toggle with smooth animation
                if (content.style.display === 'none' || content.style.display === '') {{
                    content.style.display = 'block';
                    setTimeout(() => {{
                        icon.style.transform = 'rotate(0deg)';
                    }}, 10);
                }} else {{
                    icon.style.transform = 'rotate(-90deg)';
                    setTimeout(() => {{
                        content.style.display = 'none';
                    }}, 150); // Wait for rotation animation
                }}
            }}
            
            // ===================================
            // OFFICIAL RESULTS FUNCTIONS (StudentResult API)
            // ===================================
            
            async function fetchOfficialResults(silentRefresh = false) {{
                if (!attendanceSessionToken) {{
                    return false;
                }}

                ensurePrivateCacheOwner();

                // Deduplicate concurrent loads
                if (inFlightOfficialResults) {{
                    if (!silentRefresh && !cachedOfficialResults) {{
                        document.getElementById('officialResultsContent').innerHTML = `
                            <div class="loading">
                                <div class="spinner"></div>
                                <p style="color: var(--text-secondary)">Loading official results...</p>
                            </div>
                        `;
                    }}
                    return inFlightOfficialResults;
                }}
                
                if (!silentRefresh) {{
                    document.getElementById('officialResultsContent').innerHTML = `
                        <div class="loading">
                            <div class="spinner"></div>
                            <p style="color: var(--text-secondary)">Loading official results...</p>
                        </div>
                    `;
                }}
                
                const requestToken = attendanceSessionToken;
                const requestOwnerKey = getPrivateOwnerKey();

                inFlightOfficialResults = (async () => {{
                    let loadedSuccessfully = false;
                    try {{
                        const result = await apiFetchJson('/api/official-results/data', {{}}, 2, 30000);
                    
                        // If user logged out / switched user while request was in-flight, ignore results
                        if (attendanceSessionToken !== requestToken || getPrivateOwnerKey() !== requestOwnerKey) {{
                            return;
                        }}

                        if (result.success) {{
                        // Refresh session timestamp on successful data load
                        updateSessionTimestamp();
                        
                        // Cache the data for instant future loads
                        cachedOfficialResults = result.results || [];
                        cachedOfficialResultsAt = Date.now();
                        persistPrivateCache('official_results', cachedOfficialResults);
                        
                        // Render official results
                        renderOfficialResults(cachedOfficialResults);
                        loadedSuccessfully = true;
                    }} else {{
                        // Session expired or error
                        if (result.error && result.error.toLowerCase().includes('expired')) {{
                            logoutAttendance(true);
                            showNotification('Session expired. Please login again.', 'error');
                        }} else {{
                            // Keep showing last cached results if we have any,
                            // and only replace the UI with an error screen when
                            // there is no cached data yet (first load).
                            console.warn('Error loading official results:', result.error);
                            if (!cachedOfficialResults || cachedOfficialResults.length === 0) {{
                                document.getElementById('officialResultsContent').innerHTML = `
                                    <div class="empty-state">
                                        <i class="fas fa-exclamation-triangle"></i>
                                        <h3>Error Loading Results</h3>
                                        <p>${{result.error}}</p>
                                    </div>
                                `;
                            }}
                        }}
                        }}
                    }} catch (error) {{
                        // If user logged out / switched user while request was in-flight, ignore UI updates
                        if (attendanceSessionToken !== requestToken || getPrivateOwnerKey() !== requestOwnerKey) {{
                            return;
                        }}

                        if (String(error && error.message || '').includes('HTTP 401')) {{
                            logoutAttendance(true);
                            showNotification('Your session has ended. Please login again.', 'error');
                            return false;
                        }}

                        console.error('Network error while loading official results:', error);
                        // Same rule: only show error screen if we have no cached
                        // results yet; otherwise keep the last good data visible.
                        if (!cachedOfficialResults || cachedOfficialResults.length === 0) {{
                            document.getElementById('officialResultsContent').innerHTML = `
                                <div class="empty-state">
                                    <i class="fas fa-exclamation-triangle"></i>
                                    <h3>Error Loading Results</h3>
                                    <p>${{error.message}}</p>
                                </div>
                            `;
                        }}
                    }}
                    return loadedSuccessfully;
                }})().finally(() => {{
                    inFlightOfficialResults = null;
                }});

                return inFlightOfficialResults;
            }}
            
            function renderOfficialResults(results) {{
                const container = document.getElementById('officialResultsContent');
                
                if (!results || results.length === 0) {{
                    container.innerHTML = `
                        <div class="no-absences">
                            <i class="fas fa-clipboard-list"></i>
                            <h3>No Official Results Found</h3>
                            <p>Your official exam results will appear here once published by the college.</p>
                            <div class="login-note" style="margin-top: 1rem;">
                                <i class="fas fa-info-circle"></i>
                                <span>This section shows official results from the student portal system</span>
                            </div>
                        </div>
                    `;
                    return;
                }}
                
                // Group results by Semester only (like lectures section)
                let htmlContent = '';
                const resultsBySemester = {{}};
                // Keep ONLY final subject rows (defensive UI filter)
                const finalStatusTokens = [
                    'accept', 'excellent', 'verygood', 'very good', 'good', 'medium', 'weak',
                    'pass', 'fail', 'pending', 'not marked', 'not marked yet',
                    'ناجح', 'راسب', 'مقبول', 'جيد', 'جيد جدا', 'ممتاز', 'قيد الانتظار', 'غير مصحح'
                ];
                function _escapeRegex(text) {{
                    const re = new RegExp('[.*+?^$()|\\[\\]\\\\]', 'g');
                    return String(text).replace(re, '\\$&');
                }}

                const gradeTokenRe = new RegExp(finalStatusTokens.map(t => _escapeRegex(t)).join('|'), 'i');

                function _extractYear(label) {{
                    const m = String(label || '').match(/([0-9]{{4}}) *[-–] *([0-9]{{4}})/);
                    return m ? `${{m[1]}}-${{m[2]}}` : '';
                }}

                function _extractSemester(label) {{
                    const t = String(label || '').toLowerCase();
                    if (t.includes('fall')) return 'Fall Semester';
                    if (t.includes('spring')) return 'Spring Semester';
                    if (t.includes('summer')) return 'Summer Semester';
                    if (t.includes('1st semester') || t.includes('first semester') || String(label || '').includes('الفصل الأول') || String(label || '').includes('الفصل الاول')) return 'First Semester';
                    if (t.includes('2nd semester') || t.includes('second semester') || String(label || '').includes('الفصل الثاني')) return 'Second Semester';
                    return '';
                }}

                const filteredResults = (results || []).filter((r) => {{
                    const title = String(r.Title || r.title || r.SubjectName || r.subjectName || r.CourseTitle || r.courseTitle || r.Subject || r.subject || '').trim();
                    const status = String(r.Status || r.status || '').trim();
                    const total = String(r.TotalGrade || r.totalGrade || r.ContinuousSummary || r.continuousSummary || r.Points || r.points || '').trim();

                    if (!title) return false;
                    const titleLower = title.toLowerCase();
                    const statusLower = status.toLowerCase();

                    // Drop obvious non-subject lines
                    if (['total', 'sum', 'subtotal', 'overall', 'result'].includes(titleLower)) return false;
                    if (['total', 'sum', 'subtotal', 'overall', 'result', 'المجموع', 'مجموع', 'الكلي', 'كۆی', 'کۆی گشتی', 'جمع'].some(tok => titleLower.includes(tok))) return false;
                    // Drop if title itself is just a grade label (e.g., "Medium")
                    if (gradeTokenRe.test(title) && title.length <= 15) return false;

                    const assessmentLike = ['quiz', 'mid term', 'midterm', 'activity', 'act.', 'ass.', 'assignment', 'report', 'seminar', 'practical', 'presentation', 'final', 'hw', 'homework', 'home work', 'project', 'lab']
                        .some((tok) => titleLower.includes(tok));

                    const statusLooksFinal = status && gradeTokenRe.test(status);

                    if (assessmentLike && !statusLooksFinal) return false;
                    if (!statusLooksFinal && (!total || total === '-' || total === '0' || total === '0.0')) return false;
                    if (['mid term', 'midterm', 'act', 'ass', 'quiz', 'hw', 'homework', 'assignment', 'report', 'presentation', 'project', 'lab'].some(tok => statusLower.includes(tok))) return false;

                    return true;
                }});
                
                filteredResults.forEach((result) => {{
                    const academicYear = result.AcademicYear || result.academicYear || result.Year || result.year || '';
                    const semesterName = result.SemesterName || result.Semester || result.semester || 'Unknown Semester';
                    const semesterLabel = result.SemesterLabel || result.semesterLabel || '';

                    const yearFromLabel = _extractYear(semesterLabel);
                    const semFromLabel = _extractSemester(semesterLabel);
                    const year = academicYear || yearFromLabel;
                    // Prefer label-derived semester when available; upstream semesterName can be inconsistent.
                    const sem = semFromLabel || ((semesterName && semesterName !== 'Unknown Semester') ? semesterName : semesterName);

                    // STRICT: show ONLY "YYYY-YYYY <Semester>" sections.
                    // Never show year-only or "Result of..." groups.
                    if (!year) return;
                    if (!sem || sem === 'Unknown Semester') return;
                    const semesterKey = `${{year}} ${{sem}}`;
                    
                    if (!resultsBySemester[semesterKey]) {{
                        resultsBySemester[semesterKey] = [];
                    }}
                    
                    resultsBySemester[semesterKey].push(result);
                }});
                
                // Sort semesters
                const _order = ['Summer Semester', 'Spring Semester', 'Fall Semester', 'Second Semester', 'First Semester'];
                const sortedSemesters = Object.keys(resultsBySemester)
                    .sort((a, b) => {{
                        const ay = _extractYear(a) || '';
                        const by = _extractYear(b) || '';
                        if (ay && by && ay !== by) return by.localeCompare(ay);

                        const as = _extractSemester(a) || '';
                        const bs = _extractSemester(b) || '';
                        const ai = _order.indexOf(as);
                        const bi = _order.indexOf(bs);
                        if (ai !== -1 || bi !== -1) return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);

                        return a.localeCompare(b);
                    }});
                
                // Render each Semester (like lectures section)
                sortedSemesters.forEach((semesterKey) => {{
                    const semesterResults = resultsBySemester[semesterKey];
                    
                    htmlContent += `
                        <div class="subject-section" style="margin: 0 1rem 1.5rem 1rem;">
                            <div class="subject-header" onclick="toggleResultsSemester(this)" style="background: linear-gradient(135deg, var(--primary) 0%, var(--secondary) 100%); cursor: pointer;">
                                <div class="subject-title" style="color: white; font-weight: 700;">
                                    <i class="fas fa-calendar-alt" style="color: white;"></i>
                                    ${{semesterKey}}
                                    <span class="file-count" style="background: rgba(255,255,255,0.2); color: white;">${{semesterResults.length}} Subject${{semesterResults.length > 1 ? 's' : ''}}</span>
                                </div>
                                <div class="collapse-btn">
                                    <i class="fas fa-chevron-down" style="color: white; transform: rotate(-90deg); transition: transform 0.3s ease;"></i>
                                </div>
                            </div>
                            <div class="semester-results-table" style="display: none; padding: 0; overflow-x: auto;">
                                <table style="width: 100%; border-collapse: collapse; background: var(--bg-secondary);">
                                    <thead>
                                        <tr style="background: var(--surface); border-bottom: 2px solid var(--border);">
                                            <th style="padding: 1rem; text-align: left; color: var(--text-primary); font-weight: 700; font-size: 0.85rem; text-transform: uppercase;">
                                                <i class="fas fa-book" style="margin-right: 0.5rem; color: var(--accent);"></i>Title
                                            </th>
                                            <th style="padding: 1rem; text-align: center; color: var(--text-primary); font-weight: 700; font-size: 0.85rem; text-transform: uppercase; width: 200px;">
                                                Total Grade
                                            </th>
                                            <th style="padding: 1rem; text-align: center; color: var(--text-primary); font-weight: 700; font-size: 0.85rem; text-transform: uppercase; width: 180px;">
                                                <i class="fas fa-check-circle" style="margin-right: 0.5rem; color: var(--accent);"></i>Status
                                            </th>
                                        </tr>
                                    </thead>
                                    <tbody>
                    `;
                    
                    // Render each result row
                    semesterResults.forEach((result, index) => {{
                        // Simplified mapping: ONLY Title, Total Grade, Status
                        const title = result.Title || result.title || result.SubjectName || result.subjectName || result.CourseTitle || result.courseTitle || result.Subject || result.subject || 'Unknown Subject';
                        let totalGrade = result.TotalGrade || result.totalGrade || result.ContinuousSummary || result.continuousSummary || result.ContinuousTotal || result.continuousTotal || result.Points || result.points || '-';
                        totalGrade = (totalGrade != null && String(totalGrade).trim() !== '') ? String(totalGrade).trim() : '-';

                        let rawStatus = result.Status || result.status || '';
                        rawStatus = (rawStatus != null && String(rawStatus).trim() !== '') ? String(rawStatus).trim() : '';

                        const statusLower = rawStatus.toLowerCase();
                        
                        // Determine final status (Pass/Fail) based on status text
                        let statusColor = '#94a3b8';
                        let statusIcon = 'fa-clock';
                        let statusBg = 'rgba(148, 163, 184, 0.15)';
                        // IMPORTANT: display the real system status text when present
                        let statusDisplay = rawStatus || '-';

                        // Check for explicit status text first (match college system)
                        if (
                            statusLower.includes('pass') ||
                            statusLower.includes('accept') ||
                            statusLower.includes('excellent') ||
                            statusLower.includes('verygood') ||
                            statusLower.includes('very good') ||
                            statusLower.includes('good') ||
                            statusLower.includes('medium') ||
                            statusLower === 'ناجح'
                        ) {{
                            statusColor = '#10b981';
                            statusIcon = 'fa-check-circle';
                            statusBg = 'rgba(16, 185, 129, 0.15)';
                            // Keep system-provided label if present; otherwise fallback
                            statusDisplay = rawStatus || 'Pass';
                        }} else if (statusLower.includes('pending') || statusLower.includes('not marked') || statusLower === 'قيد الانتظار' || statusLower === 'لە چاوەڕوانیدا') {{
                            statusColor = '#94a3b8';
                            statusIcon = 'fa-clock';
                            statusBg = 'rgba(148, 163, 184, 0.15)';
                            statusDisplay = rawStatus || '-';
                        }} else if (statusLower.includes('fail') || statusLower === 'راسب') {{
                            statusColor = '#ef4444';
                            statusIcon = 'fa-times-circle';
                            statusBg = 'rgba(239, 68, 68, 0.15)';
                            statusDisplay = rawStatus || 'Fail';
                        }} else {{
                            // No guessing: keep rawStatus if present, else leave '-'
                            statusDisplay = statusDisplay;
                        }}
                        
                        htmlContent += `
                            <tr style="border-bottom: 1px solid var(--border); transition: background 0.2s;" onmouseover="this.style.background='var(--surface)'" onmouseout="this.style.background='transparent'">
                                <td style="padding: 1rem;">
                                    <div style="font-weight: 600; color: var(--text-primary); font-size: 0.95rem; line-height: 1.4;">${{title}}</div>
                                </td>
                                <td style="padding: 1rem; text-align: center;">
                                    <span style="display: inline-block; padding: 0.5rem 1rem; background: var(--bg-tertiary); color: var(--text-primary); border: 1px solid var(--border); border-radius: 10px; font-weight: 700; font-size: 0.95rem; min-width: 80px;">${{totalGrade}}</span>
                                </td>
                                <td style="padding: 1rem; text-align: center;">
                                    <span style="display: inline-flex; align-items: center; gap: 0.4rem; padding: 0.5rem 1rem; background: ${{statusBg}}; color: ${{statusColor}}; border-radius: 10px; font-weight: 600; font-size: 0.85rem;">
                                        <i class="fas ${{statusIcon}}"></i>${{statusDisplay}}
                                    </span>
                                </td>
                            </tr>
                        `;
                    }});
                    
                    htmlContent += `
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    `;
                }});
                
                container.innerHTML = htmlContent;
            }}
            
            // Legacy support for old function names
            function toggleSemesterSection(header) {{
                toggleResultsSemester(header);
            }}
            
            function toggleOfficialSemesterSection(header) {{
                toggleResultsSemester(header);
            }}
        </script>
        
        <!-- Mobile Touch Optimization -->
        <script>
            // Add touch event support for all interactive elements on mobile
            document.addEventListener('DOMContentLoaded', () => {{
                console.log('🚀 Initializing mobile optimizations...');
                
                // Hide splash screen smoothly after content loads
                const hideSplash = () => {{
                    const splashScreen = document.getElementById('splash-screen');
                    if (splashScreen) {{
                        splashScreen.style.opacity = '0';
                        setTimeout(() => {{
                            splashScreen.style.display = 'none';
                        }}, 300);
                    }}
                }};
                
                // Hide after minimum display time AND page ready
                Promise.all([
                    new Promise(resolve => setTimeout(resolve, 800)), // Minimum 800ms
                    document.fonts.ready // Wait for fonts
                ]).then(hideSplash);
                
                // Fix iOS tap delay (300ms)
                document.addEventListener('touchstart', function() {{}}, true);

                // Delegated touch feedback keeps interaction instant for current and future buttons.
                const quickTapSelector = 'button, .btn, .action-btn, .sync-btn, .admin-btn, .zone-tab, .private-subtab, .subject-header, .open-btn, .download-btn';
                const getQuickTapTarget = (target) => target && target.closest ? target.closest(quickTapSelector) : null;

                document.addEventListener('touchstart', (event) => {{
                    const tapTarget = getQuickTapTarget(event.target);
                    if (tapTarget) tapTarget.classList.add('tap-active');
                }}, {{ passive: true }});

                const clearTapState = (event) => {{
                    const tapTarget = getQuickTapTarget(event.target);
                    if (tapTarget) tapTarget.classList.remove('tap-active');
                }};

                document.addEventListener('touchend', clearTapState, {{ passive: true }});
                document.addEventListener('touchcancel', clearTapState, {{ passive: true }});
                
                // Prevent double-tap zoom on buttons
                let lastTouchEnd = 0;
                document.addEventListener('touchend', function(event) {{
                    const now = Date.now();
                    const target = getQuickTapTarget(event.target);
                    if (target && now - lastTouchEnd <= 300) {{
                        event.preventDefault();
                    }}
                    lastTouchEnd = now;
                }}, false);
                
                // Log initialization complete
                console.log('✅ Mobile optimizations active');
                console.log('📱 Device:', navigator.userAgent.includes('Mobile') ? 'Mobile' : 'Desktop');
                console.log('� User Agent:', navigator.userAgent);
                console.log('🔐 Attendance Token:', attendanceSessionToken ? 'Present' : 'None');
                console.log('👤 Attendance Username:', attendanceUsername ? attendanceUsername : 'None');
                
                // Debug localStorage on mobile
                try {{
                    var testKey = 'test_storage';
                    safeStorage.setItem(testKey, 'test_value');
                    var testRead = safeStorage.getItem(testKey);
                    console.log('📦 localStorage test:', testRead === 'test_value' ? 'Working' : 'Failed');
                    safeStorage.removeItem(testKey);
                }} catch (e) {{
                    console.error('❌ localStorage test failed:', e);
                }}
                
                // Always start in logged-out mode on page load.
                attendanceSessionToken = null;
                safeStorage.removeItem('attendance_session_active');
                safeStorage.removeItem('attendance_username');
                safeStorage.removeItem('attendance_session_timestamp');
                console.log('ℹ️ Fresh login required on each page load');
            }});
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
            window.addEventListener('beforeinstallprompt', (e) => {{
                console.log('💡 PWA install prompt available');
                e.preventDefault();
                deferredPrompt = e;
                
                // Check if device is mobile - don't show button on mobile
                var isMobile = window.innerWidth <= 768 || /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
                
                if (isMobile) {{
                    console.log('📱 Mobile device detected - install button hidden (use browser menu)');
                    return; // Don't show install button on mobile
                }}
                
                // Show custom install button (desktop only)
                const installBtn = document.getElementById('pwaInstallBtn');
                if (installBtn) {{
                    installBtn.style.display = 'flex';
                    installBtn.classList.add('pulse');
                    console.log('💻 Desktop detected - showing install button');
                    
                    // Remove any existing listeners
                    const newInstallBtn = installBtn.cloneNode(true);
                    installBtn.parentNode.replaceChild(newInstallBtn, installBtn);
                    
                    // Add click handler for desktop/mobile
                    newInstallBtn.addEventListener('click', async (evt) => {{
                        evt.preventDefault();
                        evt.stopPropagation();
                        
                        if (!deferredPrompt) {{
                            alert('App is already installed or install prompt is not available!');
                            return;
                        }}
                        
                        console.log('👆 Install button clicked');
                        newInstallBtn.disabled = true;
                        newInstallBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Installing...';
                        
                        try {{
                            deferredPrompt.prompt();
                            const {{ outcome }} = await deferredPrompt.userChoice;
                            console.log(`User response: ${{outcome}}`);
                            
                            if (outcome === 'accepted') {{
                                console.log('✅ User accepted installation');
                                newInstallBtn.innerHTML = '<i class="fas fa-check"></i> Installed!';
                            }} else {{
                                console.log('❌ User dismissed installation');
                                newInstallBtn.innerHTML = '<i class="fas fa-download"></i> Install App';
                                newInstallBtn.disabled = false;
                            }}
                            
                            deferredPrompt = null;
                            setTimeout(() => {{
                                newInstallBtn.style.display = 'none';
                            }}, 2000);
                        }} catch (error) {{
                            console.error('Install error:', error);
                            newInstallBtn.innerHTML = '<i class="fas fa-download"></i> Install App';
                            newInstallBtn.disabled = false;
                        }}
                    }});
                    
                    // Add touch handler for better mobile support
                    newInstallBtn.addEventListener('touchend', async (evt) => {{
                        evt.preventDefault();
                        newInstallBtn.click();
                    }});
                }}
            }});
            
            // Track successful install
            window.addEventListener('appinstalled', () => {{
                console.log('✅ PWA installed successfully!');
                deferredPrompt = null;
                const installBtn = document.getElementById('pwaInstallBtn');
                if (installBtn) {{
                    installBtn.style.display = 'none';
                }}
            }});
            
            // OFFLINE-FIRST: Network status monitoring (console only, no UI changes)
            // Why: Helps debug offline issues without disrupting user experience
            function updateOnlineStatus() {{
                const condition = navigator.onLine ? 'ONLINE' : 'OFFLINE';
                console.log(`[Network Status] ${{condition}} - App continues working with cached data`);
                
                // Store status for API calls to handle gracefully
                window.__networkStatus = navigator.onLine;
            }}
            
            // Initial status
            updateOnlineStatus();
            
            // Listen for status changes (non-blocking, no alerts/popups)
            window.addEventListener('online', () => {{
                updateOnlineStatus();
                console.log('[Network Status] Connection restored - API calls will use network');
            }});
            
            window.addEventListener('offline', () => {{
                updateOnlineStatus();
                console.log('[Network Status] Connection lost - App will serve cached content');
            }});
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
