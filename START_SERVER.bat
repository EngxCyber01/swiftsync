@echo off
echo ================================
echo   IUMS Lecture Portal Server
echo   Starting with NEW DARK THEME...
echo ================================
echo.

cd /d "%~dp0"
call .venv\Scripts\activate.bat
python -m uvicorn main:app --host 0.0.0.0 --port 8000

pause
