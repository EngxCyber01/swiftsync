# 🔍 TROUBLESHOOTING GUIDE - Dashboard Not Loading

## ❓ Problem: Dashboard shows "-" for all stats

### ✅ Quick Fix Steps

1. **Open Browser Developer Tools**
   - Press `F12` in your browser
   - Go to **Console** tab
   - Look for any error messages (red text)

2. **Check What You See:**

   **✅ IF YOU SEE THESE LOGS (GOOD!):**
   ```
   🚀 Initializing dashboard...
   📡 Fetching lectures from API...
   ✅ API response received: 200
   📊 Data loaded: 2 semesters
   🎨 Rendering files...
   📚 Semesters found: (2) ["Fall Semester", "Spring Semester"]
   ```
   **→ Dashboard should load! If not, try hard refresh: `Ctrl + Shift + R`**

   **❌ IF YOU SEE CORS ERROR:**
   ```
   Access to fetch at 'http://localhost:8000/api/files' has been blocked by CORS policy
   ```
   **→ Server is not running. Start it:**
   ```powershell
   cd "C:\Users\hillios\OneDrive\Desktop\mm"
   python main.py
   ```

   **❌ IF YOU SEE NETWORK ERROR:**
   ```
   Failed to fetch
   net::ERR_CONNECTION_REFUSED
   ```
   **→ Server crashed or not started. Restart:**
   ```powershell
   # Kill any existing Python processes
   Get-Process python | Stop-Process -Force
   
   # Start server
   cd "C:\Users\hillios\OneDrive\Desktop\mm"
   python main.py
   ```

   **❌ IF YOU SEE 404 ERROR:**
   ```
   GET http://localhost:8000/api/files 404 (Not Found)
   ```
   **→ Wrong API endpoint or server issue. Check server logs**

   **❌ IF YOU SEE JSON PARSE ERROR:**
   ```
   Unexpected token < in JSON at position 0
   ```
   **→ Server returned HTML instead of JSON. Check if API endpoint exists**

3. **Verify Server is Running**
   ```powershell
   # Check if Python is running
   Get-Process python
   
   # Check if port 8000 is in use
   netstat -ano | findstr :8000
   ```

4. **Test API Directly**
   ```powershell
   # Test API endpoint
   Invoke-WebRequest -Uri "http://localhost:8000/api/files" -UseBasicParsing
   
   # Should return JSON with lecture data
   ```

5. **Hard Refresh Browser**
   - Windows: `Ctrl + Shift + R` or `Ctrl + F5`
   - Mac: `Cmd + Shift + R`
   - This clears cached JavaScript

6. **Clear Browser Cache**
   - Press `Ctrl + Shift + Delete`
   - Select "Cached images and files"
   - Click "Clear data"
   - Refresh page

## 🔧 Advanced Troubleshooting

### Check Database
```powershell
cd "C:\Users\hillios\OneDrive\Desktop\mm"
python -c "import sqlite3; conn = sqlite3.connect('data/lecture_sync.db'); cursor = conn.execute('SELECT COUNT(*) FROM synced_items'); print(f'Records: {cursor.fetchone()[0]}'); conn.close()"
```

### Check Files Directory
```powershell
Get-ChildItem .\lectures_storage\ | Measure-Object | Select-Object -ExpandProperty Count
```

### Manual API Test
```powershell
# Start server
python main.py

# In new PowerShell window:
$response = Invoke-WebRequest -Uri "http://localhost:8000/api/files" -UseBasicParsing
$response.Content | ConvertFrom-Json | ConvertTo-Json -Depth 3
```

### Check Server Logs
Look for these in the terminal where you ran `python main.py`:
```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     127.0.0.1:xxxxx - "GET /api/files HTTP/1.1" 200 OK
```

If you see:
```
INFO:     127.0.0.1:xxxxx - "GET /api/files HTTP/1.1" 500 Internal Server Error
```
**→ There's a Python error. Check the full error message above this line**

## 🆘 Still Not Working?

### Complete Reset

1. **Stop all Python processes**
   ```powershell
   Get-Process python | Stop-Process -Force
   ```

2. **Delete browser cache and restart browser**

3. **Start server fresh**
   ```powershell
   cd "C:\Users\hillios\OneDrive\Desktop\mm"
   python main.py
   ```

4. **Open browser in incognito mode**
   - Press `Ctrl + Shift + N` (Chrome/Edge)
   - Go to `http://localhost:8000`

5. **Check console (F12) for logs**

## 📞 Contact Support

If none of these work, provide:
1. Screenshot of browser console (F12 → Console tab)
2. Screenshot of terminal where server is running
3. Output of this command:
   ```powershell
   cd "C:\Users\hillios\OneDrive\Desktop\mm"
   python -c "import sqlite3; conn = sqlite3.connect('data/lecture_sync.db'); cursor = conn.execute('SELECT COUNT(*) FROM synced_items'); print(cursor.fetchone()[0])"
   ```
