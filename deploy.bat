:: SwiftSync - Quick Deploy to Render (Windows)
@echo off
echo.
echo ========================================
echo    SwiftSync - Deploy to Render
echo ========================================
echo.
echo Pre-Deployment Checklist:
echo  [X] Fixed Telegram duplicate notifications
echo  [X] Fixed mobile login issues  
echo  [X] Fixed PWA installation
echo  [X] Admin dashboard using real data
echo  [X] Added CORS for mobile support
echo.
echo ========================================
echo    DEPLOYMENT STEPS
echo ========================================
echo.
echo 1. PUSH TO GITHUB:
echo    git add .
echo    git commit -m "Fixed all mobile and deployment issues"
echo    git push origin main
echo.
echo 2. RENDER DASHBOARD:
echo    Open: https://dashboard.render.com
echo.
echo 3. SET ENVIRONMENT VARIABLES:
echo    PORTAL_USERNAME=your_portal_username
echo    PORTAL_PASSWORD=your_portal_password
echo    GEMINI_API_KEY=your_gemini_api_key
echo    SECRET_ADMIN_KEY=your_secret_admin_key
echo    TELEGRAM_BOT_TOKEN=your_telegram_bot_token
echo    TELEGRAM_GROUP_ID=your_telegram_group_id
echo    TELEGRAM_CHAT_ID=your_telegram_chat_id_here
echo    BASE_URL=https://swiftsync-013r.onrender.com
echo    RENDER=true
echo.
echo 4. TRIGGER MANUAL DEPLOY
echo.
echo ========================================
echo    TESTING AFTER DEPLOYMENT
echo ========================================
echo.
echo Health Check:
echo    curl https://swiftsync-013r.onrender.com/health
echo.
echo Test Sync:
echo    curl -X POST https://swiftsync-013r.onrender.com/api/sync-now
echo.
echo Test on Mobile:
echo    1. Open on phone browser
echo    2. Try login
echo    3. Install PWA (Add to Home Screen)
echo    4. Download lectures
echo.
echo Admin Dashboard:
echo    https://swiftsync-013r.onrender.com/admin-portal?admin_key=YOUR_ADMIN_KEY
echo.
echo ========================================
echo    ALL SYSTEMS READY!
echo ========================================
echo.
pause

