@echo off
echo.
echo ========================================
echo   SwiftSync - Quick Test Commands
echo ========================================
echo.
echo Testing your deployed application...
echo.
echo ========================================
echo   1. HEALTH CHECK
echo ========================================
curl -s https://swiftsync-013r.onrender.com/health
echo.
echo.
echo ========================================
echo   2. TEST SYNC (Manual Trigger)
echo ========================================
curl -s -X POST https://swiftsync-013r.onrender.com/api/sync-now
echo.
echo.
echo ========================================
echo   3. PERFORMANCE TEST
echo ========================================
echo Testing response time...
powershell -Command "Measure-Command { Invoke-WebRequest -Uri 'https://swiftsync-013r.onrender.com/health' -UseBasicParsing } | Select-Object TotalMilliseconds"
echo.
echo ========================================
echo   4. OPEN IN BROWSER
echo ========================================
echo Opening SwiftSync in your browser...
start https://swiftsync-013r.onrender.com
echo.
echo ========================================
echo   5. OPEN ADMIN DASHBOARD
echo ========================================
echo Opening Admin Portal...
start https://swiftsync-013r.onrender.com/admin-portal?admin_key=emadCyberSoft4SOC
echo.
echo ========================================
echo   NEXT STEPS
echo ========================================
echo.
echo Test on Mobile:
echo   1. Open: https://swiftsync-013r.onrender.com
echo   2. Test button sensitivity (should be INSTANT!)
echo   3. Try PWA installation
echo   4. Test offline mode
echo.
echo Check Render Dashboard:
echo   https://dashboard.render.com
echo.
echo ========================================
echo   ALL TESTS COMPLETE!
echo ========================================
echo.
pause
