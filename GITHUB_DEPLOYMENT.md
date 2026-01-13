# GitHub Deployment Guide

## 🚀 Deploy to GitHub Pages

### Step 1: Create GitHub Repository

```bash
cd "C:\Users\hillios\OneDrive\Desktop\lecture system"

# Initialize Git (if not already)
git init

# Create .gitignore
echo "*.pyc
__pycache__/
.venv/
*.db
.env
lectures_storage/
*.html
portal_html.html" > .gitignore

# Add all files
git add .
git commit -m "Initial commit: IUMS Lecture Portal"

# Create repo on GitHub, then:
git remote add origin https://github.com/YOUR_USERNAME/iums-lectures.git
git branch -M main
git push -u origin main
```

### Step 2: Deploy Options

#### Option A: GitHub Pages (Static Site)
**Not recommended** - Your portal is dynamic (requires Python backend)

#### Option B: Heroku (Free Tier)
1. Create `Procfile`:
```
web: uvicorn main:app --host=0.0.0.0 --port=$PORT
```

2. Create `requirements.txt`:
```bash
pip freeze > requirements.txt
```

3. Deploy:
```bash
heroku create iums-lectures
git push heroku main
```

#### Option C: Render.com (Free)
1. Create account at render.com
2. New Web Service → Connect GitHub repo
3. Settings:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Add environment variables from `.env`
5. Deploy!

#### Option D: Railway.app (Recommended ⭐)
1. Visit railway.app
2. "Deploy from GitHub"
3. Select your repo
4. Railway auto-detects Python
5. Add environment variables
6. Deploy → Get public URL

### Step 3: Environment Variables

Add these to your deployment platform:

```
PORTAL_USERNAME=B02052324
PORTAL_PASSWORD=emadXoshnaw1$
APP_BASE_URL=https://tempapp-su.awrosoft.com
AUTH_BASE_URL=https://tempids-su.awrosoft.com
```

### Step 4: Update Code for Production

Add to `main.py`:
```python
# Get port from environment
port = int(os.getenv("PORT", "8000"))

# For production deployment
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=port)
```

## 📦 Files Needed for GitHub

Create these files in your project:

### 1. `.gitignore`
```
*.pyc
__pycache__/
.venv/
*.db
.env
lectures_storage/
portal_html.html
debug_html.py
test_*.py
migrate_db.py
update_subjects.py
```

### 2. `requirements.txt`
```
fastapi==0.104.1
uvicorn==0.24.0
requests==2.31.0
beautifulsoup4==4.12.2
python-dotenv==1.0.0
```

### 3. `runtime.txt` (for Heroku)
```
python-3.10.0
```

### 4. `Procfile` (for Heroku)
```
web: uvicorn main:app --host=0.0.0.0 --port=$PORT
```

### 5. `README.md` (for GitHub)
```markdown
# IUMS Lecture Portal 🎓

Automated lecture synchronization system for Awrosoft Hevra IUMS.

## Features
- 🔄 Auto-sync with portal
- 📚 Subject organization
- 🔍 Search functionality
- 📱 Responsive design
- 💾 Duplicate prevention

## Tech Stack
- FastAPI
- BeautifulSoup4
- SQLite
- HTML/CSS/JS

## Setup
\```bash
pip install -r requirements.txt
python main.py
\```

## Deploy
See GITHUB_DEPLOYMENT.md
```

## 🎯 Quick Deploy Commands

### Railway.app (Easiest)
```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# Initialize
railway init

# Deploy
railway up
```

### Render.com
Just connect GitHub repo in dashboard!

### Heroku
```bash
heroku login
heroku create iums-lectures
git push heroku main
heroku open
```

## ⚠️ Important Notes

1. **Database**: Use environment variable for DB path
2. **File Storage**: Consider cloud storage (S3/Azure) for production
3. **Credentials**: NEVER commit `.env` file
4. **CORS**: May need to enable for external access
5. **Rate Limiting**: Portal may block frequent requests

## 🔒 Security

### Protect Credentials
```python
# Use environment variables
import os
USERNAME = os.getenv('PORTAL_USERNAME')
PASSWORD = os.getenv('PORTAL_PASSWORD')
```

### Add Authentication (Optional)
```python
from fastapi.security import HTTPBasic, HTTPBasicCredentials

security = HTTPBasic()

@app.get("/")
async def dashboard(credentials: HTTPBasicCredentials = Depends(security)):
    # Add password check
    if credentials.username != "admin":
        raise HTTPException(status_code=401)
    # ... rest of code
```

## 📊 Recommended: Railway.app

**Why Railway?**
- ✅ Free tier generous
- ✅ Auto-deploys from GitHub
- ✅ Built-in database support
- ✅ Easy environment variables
- ✅ Custom domains
- ✅ Automatic HTTPS

**Steps:**
1. Go to railway.app
2. Sign in with GitHub
3. "New Project" → "Deploy from GitHub"
4. Select `iums-lectures` repo
5. Add environment variables
6. Click "Deploy"
7. Get public URL: `your-app.railway.app`

**Done! ✨**

## 🌐 Custom Domain (Optional)

1. Buy domain (Namecheap, GoDaddy)
2. Add CNAME record: `lectures.yourdomain.com` → `your-app.railway.app`
3. Configure in Railway settings
4. Enable HTTPS (automatic)

## 📝 Post-Deployment

After deploying:

1. **Test Sync**
   ```
   curl -X POST https://your-app.railway.app/api/sync-now
   ```

2. **Check Health**
   ```
   curl https://your-app.railway.app/health
   ```

3. **View Dashboard**
   ```
   https://your-app.railway.app
   ```

## 🎉 You're Live!

Share with students:
```
📚 IUMS Lectures Portal
🔗 https://your-app.railway.app

✨ All 2025-2026 lectures
✨ Organized by subject
✨ No login required
```

---

**Need help?** Check Railway.app docs or Render.com guides!
