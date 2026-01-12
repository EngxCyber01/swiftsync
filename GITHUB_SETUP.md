# 🚀 GitHub Deployment - Step by Step

## ✅ STEP 1: Check Your Files

Your project is ready! You have:
- ✅ `main.py` - Your app with dark theme
- ✅ `auth.py` - Authentication
- ✅ `sync.py` - Lecture sync
- ✅ `requirements.txt` - Dependencies
- ✅ `Procfile` - Deployment config
- ✅ `runtime.txt` - Python version
- ✅ `.gitignore` - Security (hides .env)

---

## 📦 STEP 2: Initialize Git (Run These Commands)

Open PowerShell in your project folder and run:

```powershell
# Go to your project
cd "C:\Users\hillios\OneDrive\Desktop\lecture system"

# Initialize Git
git init

# Add all files
git add .

# Create first commit
git commit -m "Initial commit: IUMS Lecture Portal 2025-2026"
```

---

## 🌐 STEP 3: Create GitHub Repository

1. **Open your browser**: Go to https://github.com/new

2. **Fill in details**:
   - **Repository name**: `iums-lecture-portal`
   - **Description**: `IUMS Lecture Portal 2025-2026 - Auto-sync from Awrosoft`
   - **Private**: ✅ **CHECK THIS** (your credentials are in code)
   - **Do NOT check**: "Add README" or "Add .gitignore"

3. **Click**: "Create repository"

---

## 📤 STEP 4: Push to GitHub

Copy the commands GitHub shows you, OR run these (replace YOUR_USERNAME):

```powershell
# Add GitHub as remote (REPLACE YOUR_USERNAME!)
git remote add origin https://github.com/YOUR_USERNAME/iums-lecture-portal.git

# Rename branch to main
git branch -M main

# Push to GitHub
git push -u origin main
```

**Note**: GitHub will ask for your username and password. Use a **Personal Access Token** instead of password.

### How to create token:
1. GitHub.com → Settings (your profile)
2. Developer settings → Personal access tokens → Tokens (classic)
3. Generate new token → Check "repo" → Generate
4. Copy the token and use it as password

---

## ☁️ STEP 5: Deploy to Railway.app (EASIEST!)

### 5.1: Sign Up
1. Go to: https://railway.app
2. Click "Start a New Project"
3. Sign in with GitHub

### 5.2: Deploy
1. Click "Deploy from GitHub repo"
2. Select `iums-lecture-portal`
3. Railway will start building

### 5.3: Add Environment Variables
1. Click your project → "Variables" tab
2. Click "Add Variable" for each:
   ```
   OIDC_CLIENT_ID = TEMP-IDS_SU
   OIDC_USERNAME = B02052324
   OIDC_PASSWORD = emadXoshnaw1$
   ```
3. Click "Deploy"

### 5.4: Get Your URL
1. Go to "Settings" tab
2. Scroll to "Domains"
3. Click "Generate Domain"
4. Copy your URL: `https://iums-lecture-portal-production.up.railway.app`

---

## 🎉 DONE!

Your portal is now live! Share the URL with students:
- **Local**: http://localhost:8000
- **Online**: https://your-app.up.railway.app

---

## 🔄 Update Your Deployment

When you make changes:

```powershell
cd "C:\Users\hillios\OneDrive\Desktop\lecture system"
git add .
git commit -m "Updated design"
git push
```

Railway auto-deploys on every push! 🚀

---

## ❓ Troubleshooting

**"Git not found"**:
- Install Git: https://git-scm.com/download/win
- Restart PowerShell

**"Authentication failed"**:
- Use Personal Access Token instead of password
- Get token from: https://github.com/settings/tokens

**"Railway build failed"**:
- Check "Logs" tab in Railway
- Verify environment variables are set

---

## 📞 Need Help?

1. Check Railway logs: Dashboard → Logs tab
2. Test locally first: `START_SERVER.bat`
3. Verify `.env` file has correct credentials
