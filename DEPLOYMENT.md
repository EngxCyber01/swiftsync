# Quick Deployment Guide

## ✅ System is Ready!

Your lecture sync system is fully functional with:
- 47 lectures from 2025-2026 downloaded
- 7 subjects organized
- Web dashboard working
- Database populated

## How to Run

### Windows (Local)

```powershell
cd "C:\Users\hillios\OneDrive\Desktop\lecture system"
& ".venv\Scripts\python.exe" main.py
```

Then open: **http://localhost:8000**

### Start as Background Job (Recommended)

```powershell
cd "C:\Users\hillios\OneDrive\Desktop\lecture system"
Start-Job -ScriptBlock { 
    Set-Location "C:\Users\hillios\OneDrive\Desktop\lecture system"
    & ".venv\Scripts\python.exe" main.py 
}
```

Check server is running:
```powershell
Invoke-WebRequest -Uri http://localhost:8000/health
```

Stop server:
```powershell
Get-Job | Stop-Job
Get-Job | Remove-Job
```

## Dashboard Features

### Subject Sections
- Click on any subject header to expand/collapse files
- Each section shows file count
- Files sorted alphabetically within subjects

### Search
- Use search box to filter lectures by name
- Searches across all subjects
- Real-time filtering

### Download
- Click "Download" button next to any file
- Files are downloaded directly to your browser

### Manual Sync
- Click "Sync Now" button to check for new lectures
- Shows notification when sync completes

## For Students

1. Share this URL with students: **http://YOUR-SERVER-IP:8000**
2. No login required - they can immediately see and download lectures
3. Lectures organized by subject for easy navigation

## File Locations

- **Lectures**: `lectures_storage/` (47 PDF/PPT/DOC files)
- **Database**: `data/lecture_sync.db` (tracks all downloads)
- **Credentials**: `.env` (keep secure!)

## Update Subjects

If portal structure changes or you need to re-fetch subject information:

```powershell
& ".venv\Scripts\python.exe" update_subjects.py
```

This will:
1. Authenticate to portal
2. Parse HTML for subject information
3. Update database with correct subjects
4. Show progress for each file mapped

## Troubleshooting

**Server won't start?**
- Check if port 8000 is already in use
- Try different port: Set `PORT=8080` in `.env`
- Restart PowerShell terminal

**No subjects showing?**
- Run: `python update_subjects.py`
- Restart server

**Need to re-download everything?**
- Delete `data/lecture_sync.db`
- Delete `lectures_storage/` folder
- Run: `python main.py`
- Click "Sync Now"

## Production Deployment Options

### Option 1: Windows Server
- Copy entire folder to server
- Install Python 3.10+
- Run: `python main.py`
- Configure Windows Firewall to allow port 8000

### Option 2: Cloud (Azure/AWS)
- Deploy as a VM or App Service
- Install dependencies
- Set environment variables
- Run with systemd or supervisor

### Option 3: Docker (Future)
- Create Dockerfile
- Build image
- Deploy to any cloud provider

---

**Current Status: ✅ FULLY WORKING**

The system is production-ready! All features work except automatic background sync (which is intentionally disabled). Students can access the dashboard, browse lectures by subject, and download files.
