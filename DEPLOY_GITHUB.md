# 🚀 Deploy to GitHub & Cloud Platform

## 📋 Step 1: Initialize Git Repository

```powershell
# Navigate to your project
cd "C:\Users\hillios\OneDrive\Desktop\lecture system"

# Initialize git
git init

# Add all files
git add .

# Make first commit
git commit -m "Initial commit: IUMS Lecture Portal with dark theme"
```

## 🌐 Step 2: Create GitHub Repository

1. Go to **https://github.com/new**
2. Repository name: `iums-lecture-portal` (or your choice)
3. Description: `Automatic lecture sync portal from Awrosoft Hevra IUMS - Academic Year 2025/2026`
4. **Set to Private** (contains credentials)
5. **Do NOT initialize** with README, .gitignore, or license
6. Click **Create repository**

## 📤 Step 3: Push to GitHub

```powershell
# Add remote (replace YOUR_USERNAME with your GitHub username)
git remote add origin https://github.com/YOUR_USERNAME/iums-lecture-portal.git

# Push code
git branch -M main
git push -u origin main
```

## ☁️ Step 4: Deploy to Cloud Platform

### Option A: Railway.app (Recommended - Easiest)

1. **Create Account**: Go to **https://railway.app** → Sign up with GitHub
2. **New Project**: Click **"New Project"** → **"Deploy from GitHub repo"**
3. **Select Repository**: Choose `iums-lecture-portal`
4. **Environment Variables**: Click **"Variables"** tab and add:
   ```
   OIDC_CLIENT_ID=TEMP-IDS_SU
   OIDC_USERNAME=B02052324
   OIDC_PASSWORD=emadXoshnaw1$
   ```
5. **Deploy**: Railway auto-detects Python and deploys
6. **Get URL**: Click **"Settings"** → Copy your deployment URL (e.g., `https://iums-lecture-portal-production.up.railway.app`)

**Cost**: Free tier includes 500 hours/month + $5 credit

---

### Option B: Render.com (Good Alternative)

1. **Create Account**: Go to **https://render.com** → Sign up with GitHub
2. **New Web Service**: Dashboard → **"New"** → **"Web Service"**
3. **Connect Repository**: Select `iums-lecture-portal`
4. **Configure**:
   - **Name**: `iums-lecture-portal`
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host=0.0.0.0 --port=$PORT`
5. **Environment Variables**: Click **"Advanced"** → Add:
   ```
   OIDC_CLIENT_ID=TEMP-IDS_SU
   OIDC_USERNAME=B02052324
   OIDC_PASSWORD=emadXoshnaw1$
   ```
6. **Deploy**: Click **"Create Web Service"**
7. **Get URL**: Copy your `.onrender.com` URL

**Cost**: Free tier available (sleeps after 15 min inactivity)

---

### Option C: Heroku (Classic Choice)

1. **Create Account**: Go to **https://heroku.com** → Sign up
2. **Install Heroku CLI**: Download from https://devcenter.heroku.com/articles/heroku-cli
3. **Deploy**:
   ```powershell
   # Login
   heroku login
   
   # Create app
   heroku create iums-lecture-portal
   
   # Set environment variables
   heroku config:set OIDC_CLIENT_ID=TEMP-IDS_SU
   heroku config:set OIDC_USERNAME=B02052324
   heroku config:set OIDC_PASSWORD=emadXoshnaw1$
   
   # Deploy
   git push heroku main
   
   # Open app
   heroku open
   ```

**Cost**: Free tier discontinued, starts at $5/month for Eco dynos

---

## 🔒 Security Best Practices

### 1. Use Environment Variables (Don't Commit Credentials)

Create `.env` file (already in `.gitignore`):
```bash
OIDC_CLIENT_ID=TEMP-IDS_SU
OIDC_USERNAME=B02052324
OIDC_PASSWORD=emadXoshnaw1$
```

### 2. Update `.gitignore`

Already included:
```
.env
*.db
.venv/
lectures_storage/
__pycache__/
*.pyc
```

### 3. GitHub Repository Settings

- **Make repository PRIVATE** (Settings → Danger Zone → Change visibility)
- **Enable branch protection** for `main` branch
- **Disable force push** to prevent accidental data loss

---

## 🛠️ Deployment Files Checklist

✅ **Procfile** - Tells cloud platform how to start the app:
```
web: uvicorn main:app --host=0.0.0.0 --port=$PORT
```

✅ **runtime.txt** - Specifies Python version:
```
python-3.10.13
```

✅ **requirements.txt** - Lists all dependencies:
```
fastapi
uvicorn[standard]
python-multipart
beautifulsoup4
requests
python-dotenv
```

✅ **.gitignore** - Prevents committing sensitive files:
```
.env
*.db
.venv/
lectures_storage/
```

---

## 📱 Access Your Deployed Portal

Once deployed, your portal will be available at:
- **Railway**: `https://your-app.up.railway.app`
- **Render**: `https://your-app.onrender.com`
- **Heroku**: `https://your-app.herokuapp.com`

Share this URL with students! 🎓

---

## 🔄 Update Deployment

When you make changes locally:

```powershell
# Save changes
git add .
git commit -m "Updated design/features"
git push origin main
```

Cloud platforms auto-deploy on git push! 🚀

---

## 🐛 Troubleshooting

### Server Crashes on Startup
- Check environment variables are set correctly
- View logs: Railway/Render dashboard → "Logs" tab
- Heroku: `heroku logs --tail`

### Database Not Persisting
- Cloud platforms have ephemeral storage
- Use Railway's **Persistent Volumes** or external DB for production

### Authentication Fails
- Verify credentials in environment variables
- Check portal access from browser: https://tempapp-su.awrosoft.com

---

## 🎉 Success!

Your lecture portal is now:
- ✅ Live on the internet
- ✅ Accessible via public URL
- ✅ Automatically syncing lectures
- ✅ Beautiful dark theme design
- ✅ Mobile responsive
- ✅ No login required for students

**Share the URL with your classmates!** 🎓📚
