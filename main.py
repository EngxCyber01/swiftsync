import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from auth import AuthClient, AuthConfig, AuthError
from sync import DOWNLOAD_DIR, SYNC_INTERVAL_SECONDS, sync_once

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="SwiftSync - Lecture Sync Dashboard by SSCreative")
auth_client = AuthClient(AuthConfig())

# Ensure the lectures_storage directory exists before mounting
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/files", StaticFiles(directory=DOWNLOAD_DIR, html=False), name="files")


async def sync_worker() -> None:
    """Background worker that syncs lectures periodically"""
    # Wait a bit before starting to let the server fully start
    await asyncio.sleep(5)
    
    while True:
        try:
            added, _ = await asyncio.to_thread(sync_once, auth_client)
            if added:
                logger.info("Synced %s new file(s).", added)
        except AuthError as exc:
            logger.warning("Authentication error in sync worker: %s. Will retry with re-authentication.", exc)
            try:
                await asyncio.to_thread(auth_client.login)
            except Exception as login_exc:  # noqa: BLE001
                logger.exception("Failed to re-authenticate: %s", login_exc)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Sync worker failed: %s", exc)
        
        await asyncio.sleep(SYNC_INTERVAL_SECONDS)


@app.on_event("startup")
async def start_background_sync() -> None:
    # Kick off the background sync loop
    # Temporarily disabled to debug crash
    # asyncio.create_task(sync_worker())
    pass


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@app.post("/api/sync-now")
async def manual_sync() -> JSONResponse:
    """Trigger immediate sync (for testing)"""
    try:
        added, files = await asyncio.to_thread(sync_once, auth_client)
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


@app.get("/api/files")
async def list_files() -> JSONResponse:
    """List all files grouped by subject"""
    import sqlite3
    from pathlib import Path
    
    files_by_subject = {}
    
    # Try to get subject information from database
    db_path = Path(__file__).parent / "data" / "lecture_sync.db"
    if db_path.exists():
        try:
            with sqlite3.connect(db_path) as conn:
                cursor = conn.execute("SELECT filename, subject FROM synced_items WHERE filename IS NOT NULL")
                db_subjects = {row[0]: row[1] for row in cursor.fetchall()}
        except Exception as e:
            logger.error("Error reading subjects from database: %s", e)
            db_subjects = {}
    else:
        db_subjects = {}
    
    # List all files
    if DOWNLOAD_DIR.exists():
        for path in sorted(DOWNLOAD_DIR.iterdir()):
            if path.is_file():
                stat = path.stat()
                subject = db_subjects.get(path.name) or "Other"
                
                file_info = {
                    "name": path.name,
                    "size_bytes": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "url": f"/files/{path.name}",
                }
                
                if subject not in files_by_subject:
                    files_by_subject[subject] = []
                files_by_subject[subject].append(file_info)
    
    return JSONResponse(files_by_subject)


@app.get("/")
async def dashboard() -> HTMLResponse:
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>SwiftSync • 2025/2026</title>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;900&display=swap" rel="stylesheet">
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            
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
            }}
            
            .logo {{
                display: flex;
                align-items: center;
                gap: 1rem;
            }}
            
            .logo-icon {{
                width: 50px;
                height: 50px;
                background: linear-gradient(135deg, var(--accent), var(--success));
                border-radius: 15px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 1.5rem;
                box-shadow: 0 0 30px var(--accent-glow);
                animation: glow 3s ease-in-out infinite;
            }}
            
            @keyframes glow {{
                0%, 100% {{ box-shadow: 0 0 20px var(--accent-glow); }}
                50% {{ box-shadow: 0 0 40px var(--accent-glow), 0 0 60px rgba(0, 255, 136, 0.2); }}
            }}
            
            .logo-text h1 {{
                font-size: 1.5rem;
                font-weight: 900;
                background: linear-gradient(135deg, var(--accent), var(--success));
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                background-clip: text;
                letter-spacing: -0.02em;
            }}
            
            .logo-text p {{
                font-size: 0.75rem;
                color: var(--text-tertiary);
                text-transform: uppercase;
                letter-spacing: 0.1em;
                font-weight: 600;
            }}
            
            .year-badge {{
                padding: 0.5rem 1.25rem;
                background: var(--glass);
                border: 1px solid var(--border);
                border-radius: 50px;
                font-size: 0.85rem;
                font-weight: 600;
                color: var(--accent);
                backdrop-filter: blur(10px);
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
            }}
            
            .subject-files {{
                padding: 1.5rem;
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
            
            /* Responsive */
            @media (max-width: 768px) {{
                .container {{ padding: 1.5rem 1rem; }}
                .nav {{ flex-direction: column; gap: 1rem; }}
                .stats {{ grid-template-columns: 1fr; }}
                .toolbar {{ flex-direction: column; align-items: stretch; }}
                .search-box {{ min-width: 100%; }}
                .file-item {{ flex-direction: column; align-items: flex-start; }}
                .file-size, .download-btn {{ width: 100%; justify-content: center; }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <!-- Navigation -->
            <nav class="nav">
                <div class="logo">
                    <div class="logo-icon">
                        <i class="fas fa-graduation-cap"></i>
                    </div>
                    <div class="logo-text">
                        <h1>SwiftSync</h1>
                        <p>SSCreative</p>
                    </div>
                </div>
                <div class="year-badge">
                    <i class="fas fa-calendar-alt"></i> 2025-2026
                </div>
            </nav>
            
            <!-- Stats Grid -->
            <div class="stats">
                <div class="stat-card" style="animation: fadeIn 0.5s ease 0.1s both">
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
                <div class="stat-card" style="animation: fadeIn 0.5s ease 0.2s both">
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
                <div class="stat-card" style="animation: fadeIn 0.5s ease 0.3s both">
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
        </div>
        
        <script>
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
            
            function renderFiles(data) {{
                allFilesData = data;
                const fileGrid = document.getElementById('fileGrid');
                const subjects = Object.keys(data);
                
                if (subjects.length === 0) {{
                    fileGrid.innerHTML = `
                        <div class="empty-state">
                            <i class="fas fa-inbox"></i>
                            <h3>No Lectures Yet</h3>
                            <p>Click "Sync Now" to fetch the latest lectures from the portal</p>
                        </div>
                    `;
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
                                        <a href="${{file.url}}" class="download-btn" download>
                                            <i class="fas fa-download"></i>
                                            <span>Download</span>
                                        </a>
                                    </div>
                                `).join('')}}
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
                
                if (files.style.display === 'none') {{
                    files.style.display = 'block';
                    icon.style.transform = 'rotate(0deg)';
                }} else {{
                    files.style.display = 'none';
                    icon.style.transform = 'rotate(-90deg)';
                }}
            }}
            
            // Search functionality
            document.getElementById('searchInput').addEventListener('input', (e) => {{
                const query = e.target.value.toLowerCase();
                if (!query) {{
                    renderFiles(allFilesData);
                    return;
                }}
                
                const filtered = {{}};
                Object.keys(allFilesData).forEach(subject => {{
                    const matchingFiles = allFilesData[subject].filter(file => 
                        file.name.toLowerCase().includes(query) ||
                        subject.toLowerCase().includes(query)
                    );
                    if (matchingFiles.length > 0) {{
                        filtered[subject] = matchingFiles;
                    }}
                }});
                
                renderFiles(filtered);
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
                    console.error('Error loading files:', error);
                    document.getElementById('fileGrid').innerHTML = `
                        <div class="empty-state">
                            <i class="fas fa-exclamation-triangle"></i>
                            <h3>Error Loading Files</h3>
                            <p>${{error.message}}</p>
                        </div>
                    `;
                }}
            }}
            
            // Initialize
            loadFiles();
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
