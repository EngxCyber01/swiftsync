# 🚀 Deploy SwiftSync to Render.com (Easy Method)

## Why Render.com?
- ✅ **No CLI needed** - everything in the browser
- ✅ **Auto-deploys** from GitHub on every push
- ✅ **Free tier** available
- ✅ **Simple setup** - takes 5 minutes

---

## 📋 Step-by-Step Deployment

### 1. Sign Up / Login to Render
1. Go to: https://render.com
2. Click **"Get Started"** or **"Sign In"**
3. Sign up with GitHub (recommended) or email

### 2. Create a New Web Service
1. Click **"New +"** button (top right)
2. Select **"Web Service"**
3. Click **"Connect GitHub"** if not already connected
4. Find and select your repository: **`EngxCyber01/swiftsync`**
5. Click **"Connect"**

### 3. Configure the Service
Fill in these settings:

**Basic Settings:**
- **Name:** `swiftsync` (or any name you like)
- **Region:** Choose closest to you
- **Branch:** `main`
- **Root Directory:** (leave blank)
- **Runtime:** `Python 3`

**Build & Deploy:**
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`

**Instance Type:**
- Select **"Free"** (or upgrade later if needed)

### 4. Add Environment Variables
Click **"Advanced"** → **"Add Environment Variable"**

Add these variables:
```
OIDC_USERNAME = your_username
OIDC_PASSWORD = your_password
```

*(Optional: Add production credentials later)*

### 5. Deploy!
1. Click **"Create Web Service"**
2. Render will automatically:
   - Clone your repo
   - Install dependencies
   - Start your app
3. Watch the logs - deployment takes 2-3 minutes

### 6. Access Your App
Once deployed, Render gives you a URL like:
```
https://swiftsync.onrender.com
```

Click it to see your SwiftSync dashboard live! 🎉

---

## 🔄 Auto-Deploy
Every time you push to GitHub, Render automatically redeploys. No manual steps needed!

---

## 🐛 Troubleshooting

**If deployment fails:**
1. Check the **Logs** tab in Render dashboard
2. Common issues:
   - Missing environment variables
   - Wrong start command
   - Python version mismatch

**Need help?** The logs will show exactly what went wrong.

---

## 📊 Next Steps
- Add your production OIDC credentials in Environment Variables
- Set up a custom domain (in Render settings)
- Monitor logs and performance in Render dashboard

---

**Your app is now live and will auto-update on every git push!** 🚀
