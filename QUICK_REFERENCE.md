# ðŸ“± SwiftSync - Quick Reference Card

## ðŸ”— Essential URLs

| Service | URL |
|---------|-----|
| **Main App** | https://swiftsync-013r.onrender.com |
| **Admin Portal** | https://swiftsync-013r.onrender.com/admin-portal?admin_key=your_secret_admin_key_here |
| **Health Check** | https://swiftsync-013r.onrender.com/health |

---

## ðŸ” Login Credentials

```
Username: B02052324
Password: your_portal_password_here
Admin Key: your_secret_admin_key_here
```

---

## ðŸ“± Install PWA on Mobile

### iPhone/iPad:
1. Open in **Safari**
2. Tap **Share** (ðŸ“¤)
3. **Add to Home Screen**

### Android:
1. Open in **Chrome**
2. Tap **Menu** (â‹®)
3. **Install App**

---

## ðŸš€ Deploy to Render

### 1. Push Code
```bash
git add .
git commit -m "Fixed deployment issues"
git push origin main
```

### 2. Render Environment Variables
```
PORTAL_USERNAME=B02052324
PORTAL_PASSWORD=your_portal_password_here
GEMINI_API_KEY=your_gemini_api_key_here
SECRET_ADMIN_KEY=your_secret_admin_key_here
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_telegram_chat_id_here
BASE_URL=https://swiftsync-013r.onrender.com
RENDER=true
```

### 3. Build Settings
```
Build Command: pip install -r requirements.txt
Start Command: uvicorn main:app --host 0.0.0.0 --port $PORT
```

---

## ðŸ§ª Quick Tests

### Test Health
```bash
curl https://swiftsync-013r.onrender.com/health
```

### Trigger Sync
```bash
curl -X POST https://swiftsync-013r.onrender.com/api/sync-now
```

### Test from Mobile
1. Open URL on phone
2. Login
3. Install PWA
4. Download lecture

---

## âœ… All Fixed Issues

| Issue | Status |
|-------|--------|
| Telegram duplicates on wake-up | âœ… Fixed |
| Mobile login not working | âœ… Fixed |
| PWA installation broken | âœ… Fixed |
| Admin dashboard fake data | âœ… Already real |
| Environment URLs hardcoded | âœ… Fixed |

---

## ðŸ¤– Telegram Bot Behavior

### âœ… CORRECT (After Fix)
- New lecture uploaded â†’ âœ‰ï¸ Notification sent
- Render wakes up â†’ â­ï¸ No notification
- Re-sync existing â†’ â­ï¸ No notification

### âŒ WRONG (Before Fix)
- New lecture uploaded â†’ âœ‰ï¸ Notification sent
- Render wakes up â†’ âœ‰ï¸ Duplicate sent
- Re-sync existing â†’ âœ‰ï¸ Duplicates sent

---

## ðŸ“Š System Status Check

### Dashboard Data Sources
- **Visitor Stats** â†’ Real database queries
- **Recent Activity** â†’ Live visitor logs
- **Blocked IPs** â†’ Actual blacklist
- **Threats** â†’ Real security events

### Database Tables
```sql
synced_items (id, filename, last_notified)  â† Prevents duplicates
visitor_logs (ip, timestamp, action)        â† Real tracking
blacklist (ip, reason, blocked_at)         â† IP blocking
threat_logs (ip, threat_type, details)     â† Security
```

---

## ðŸ”§ Troubleshooting

### Mobile Login Fails
- Clear browser cache
- Try incognito mode
- Verify credentials

### PWA Won't Install
- iOS: Use Safari (not Chrome)
- Android: Use Chrome
- Check HTTPS is working

### Telegram Duplicates
- Check `last_notified` column exists
- Wait 5 min after deployment
- Check Render logs

### Admin Shows No Data
- Visit main site first
- Access `/check-attendance`
- Wait for visitor activity

---

## ðŸ“ž Emergency Commands

### Restart Server (Render)
```
Dashboard â†’ Manual Deploy
```

### Clear Notification Cache
```bash
# SSH into Render (if enabled)
sqlite3 data/lecture_sync.db "UPDATE synced_items SET last_notified = NULL"
```

### Check Logs
```
Render Dashboard â†’ Logs Tab
```

---

## ðŸŽ¯ Success Indicators

âœ… Health endpoint returns OK  
âœ… Login works on mobile  
âœ… PWA installs successfully  
âœ… Admin shows visitor data  
âœ… Telegram sends 1 message per lecture  
âœ… No duplicates after wake-up  

---

**Quick Start:** `./deploy.bat` (Windows) or `./deploy.sh` (Linux/Mac)

**Full Guide:** See [DEPLOYMENT_FIXED.md](DEPLOYMENT_FIXED.md)

**Status:** âœ… **ALL SYSTEMS OPERATIONAL**

