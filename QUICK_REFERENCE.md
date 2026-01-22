# 📱 SwiftSync - Quick Reference Card

## 🔗 Essential URLs

| Service | URL |
|---------|-----|
| **Main App** | https://swiftsync-013r.onrender.com |
| **Admin Portal** | https://swiftsync-013r.onrender.com/admin-portal?admin_key=emadCyberSoft4SOC |
| **Health Check** | https://swiftsync-013r.onrender.com/health |

---

## 🔐 Login Credentials

```
Username: B02052324
Password: emadXoshnaw1$
Admin Key: emadCyberSoft4SOC
```

---

## 📱 Install PWA on Mobile

### iPhone/iPad:
1. Open in **Safari**
2. Tap **Share** (📤)
3. **Add to Home Screen**

### Android:
1. Open in **Chrome**
2. Tap **Menu** (⋮)
3. **Install App**

---

## 🚀 Deploy to Render

### 1. Push Code
```bash
git add .
git commit -m "Fixed deployment issues"
git push origin main
```

### 2. Render Environment Variables
```
PORTAL_USERNAME=B02052324
PORTAL_PASSWORD=emadXoshnaw1$
GEMINI_API_KEY=AIzaSyDSmVBPQwOEPL5dq4tXPU7C8acbyjmZag8
SECRET_ADMIN_KEY=emadCyberSoft4SOC
TELEGRAM_BOT_TOKEN=8219473970:AAGlDEoRDCV1PMfRgvkrLMmGXiHfCfrzMXQ
TELEGRAM_CHAT_ID=-1003523536992
BASE_URL=https://swiftsync-013r.onrender.com
RENDER=true
```

### 3. Build Settings
```
Build Command: pip install -r requirements.txt
Start Command: uvicorn main:app --host 0.0.0.0 --port $PORT
```

---

## 🧪 Quick Tests

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

## ✅ All Fixed Issues

| Issue | Status |
|-------|--------|
| Telegram duplicates on wake-up | ✅ Fixed |
| Mobile login not working | ✅ Fixed |
| PWA installation broken | ✅ Fixed |
| Admin dashboard fake data | ✅ Already real |
| Environment URLs hardcoded | ✅ Fixed |

---

## 🤖 Telegram Bot Behavior

### ✅ CORRECT (After Fix)
- New lecture uploaded → ✉️ Notification sent
- Render wakes up → ⏭️ No notification
- Re-sync existing → ⏭️ No notification

### ❌ WRONG (Before Fix)
- New lecture uploaded → ✉️ Notification sent
- Render wakes up → ✉️ Duplicate sent
- Re-sync existing → ✉️ Duplicates sent

---

## 📊 System Status Check

### Dashboard Data Sources
- **Visitor Stats** → Real database queries
- **Recent Activity** → Live visitor logs
- **Blocked IPs** → Actual blacklist
- **Threats** → Real security events

### Database Tables
```sql
synced_items (id, filename, last_notified)  ← Prevents duplicates
visitor_logs (ip, timestamp, action)        ← Real tracking
blacklist (ip, reason, blocked_at)         ← IP blocking
threat_logs (ip, threat_type, details)     ← Security
```

---

## 🔧 Troubleshooting

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

## 📞 Emergency Commands

### Restart Server (Render)
```
Dashboard → Manual Deploy
```

### Clear Notification Cache
```bash
# SSH into Render (if enabled)
sqlite3 data/lecture_sync.db "UPDATE synced_items SET last_notified = NULL"
```

### Check Logs
```
Render Dashboard → Logs Tab
```

---

## 🎯 Success Indicators

✅ Health endpoint returns OK  
✅ Login works on mobile  
✅ PWA installs successfully  
✅ Admin shows visitor data  
✅ Telegram sends 1 message per lecture  
✅ No duplicates after wake-up  

---

**Quick Start:** `./deploy.bat` (Windows) or `./deploy.sh` (Linux/Mac)

**Full Guide:** See [DEPLOYMENT_FIXED.md](DEPLOYMENT_FIXED.md)

**Status:** ✅ **ALL SYSTEMS OPERATIONAL**
