# Lecture Sync System - Startup Script
# Run this to start the lecture sync system

Write-Host "🚀 Starting Lecture Sync System..." -ForegroundColor Cyan
Write-Host ""

# Check if .env is configured
if (!(Test-Path ".env")) {
    Write-Host "❌ .env file not found!" -ForegroundColor Red
    Write-Host "📝 Creating .env from template..." -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
    Write-Host ""
    Write-Host "⚠️  Please edit .env file and add your credentials:" -ForegroundColor Yellow
    Write-Host "   1. Open .env in notepad" -ForegroundColor White
    Write-Host "   2. Replace 'your-email@example.com' with your portal username" -ForegroundColor White
    Write-Host "   3. Replace 'your-password-here' with your portal password" -ForegroundColor White
    Write-Host "   4. Save and run this script again" -ForegroundColor White
    Write-Host ""
    notepad .env
    exit 1
}

# Check if venv exists
if (!(Test-Path ".venv")) {
    Write-Host "📦 Creating virtual environment..." -ForegroundColor Yellow
    py -m venv .venv
    Write-Host "✅ Virtual environment created" -ForegroundColor Green
}

# Activate venv and run
Write-Host "🔧 Starting server..." -ForegroundColor Cyan
Write-Host ""
Write-Host "📊 Dashboard will be available at: http://localhost:8000" -ForegroundColor Green
Write-Host "🛑 Press CTRL+C to stop the server" -ForegroundColor Yellow
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

& ".\.venv\Scripts\python.exe" main.py
