# 🔄 Sync Now Feature Explanation

## What is "Sync Now"?

**Sync Now** is a button that manually triggers the lecture download process. It's like pressing "Refresh" but specifically for checking if teachers uploaded new lectures.

## What It Does:

1. **Connects to Portal** - Uses your credentials (B02052324) to log into the Awrosoft IUMS portal
2. **Checks for New Lectures** - Scans the 2025-2026 year section for any lecture files
3. **Compares with Database** - Checks which files are already downloaded
4. **Downloads New Files** - Only downloads lectures that aren't in your system yet
5. **Updates Dashboard** - Refreshes the page to show newly downloaded files

## When to Use It:

✅ **Teacher just uploaded a new lecture** - Click "Sync Now" to get it immediately
✅ **Morning check** - Start your day by syncing to see if there are new materials
✅ **Before class** - Make sure you have the latest lecture notes
✅ **Testing the system** - Verify authentication is working
✅ **After system restart** - Check if portal has new content

## How It Works (Technical):

```
User clicks "Sync Now"
    ↓
System authenticates to portal (gets 6 cookies)
    ↓
Fetches HTML page with all 2025-2026 lectures
    ↓
Parses HTML to extract file IDs by subject
    ↓
For each file ID:
    - Check if already in database
    - If new → Download file
    - Save to lectures_storage/
    - Add to database with subject info
    ↓
Return count of new files downloaded
    ↓
Dashboard shows "Downloaded X new files"
```

## Current Status:

⚠️ **Background sync is DISABLED** - This means:
- System does NOT automatically check for new lectures
- You MUST click "Sync Now" to get updates
- This is intentional to prevent server crashes

✅ **Manual sync works perfectly** - Click the button anytime!

## Example Scenarios:

### Scenario 1: Teacher uploads new lecture
- Teacher: Uploads "Data Structures Lect10.pdf" at 9:00 AM
- Student: Opens dashboard at 9:30 AM
- Student: Clicks "Sync Now" button
- System: Connects, finds 1 new file, downloads it
- Result: "✅ Downloaded 1 new file" notification appears

### Scenario 2: No new content
- Student: Clicks "Sync Now"
- System: Connects, checks all files
- Result: "✅ Already up to date (0 new files)"

### Scenario 3: Multiple new lectures
- Teacher: Uploads 5 new PDFs over the weekend
- Student: Opens Monday, clicks "Sync Now"
- System: Downloads all 5 files
- Result: Dashboard now shows 52 total files (was 47)

## Benefits:

✅ **On-Demand** - You control when to check
✅ **Fast** - Takes only 10-30 seconds
✅ **Reliable** - Direct connection to portal
✅ **Visual Feedback** - Shows progress and results
✅ **No Duplicates** - Never downloads same file twice

## API Usage (For Developers):

```powershell
# Trigger sync via API
Invoke-WebRequest -Uri http://localhost:8000/api/sync-now -Method POST
```

```javascript
// Trigger sync from JavaScript
fetch('/api/sync-now', { method: 'POST' })
    .then(res => res.json())
    .then(data => {
        console.log(`Downloaded ${data.files.length} new files`);
    });
```

---

**Summary**: "Sync Now" = "Check portal for new lectures and download them"
