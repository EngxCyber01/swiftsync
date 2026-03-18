# 🚀 Quick Start Guide - SwiftSync v1.3.5 Kurdish Bot

## ✅ What Was Fixed

1. **Dashboard Loading** - Now properly displays all 55 lectures with subjects
2. **Telegram Bot** - Upgraded to Kurdish language with dynamic subject info
3. **Smart Notifications** - Groups lectures by subject, sends separate messages

---

## 🎯 How to Run

### Start the Server:
```bash
cd "C:\Users\hillios\OneDrive\Desktop\mm"
python main.py
```

**Access dashboard:** http://localhost:8000

### Test Telegram Bot:
```bash
python test_telegram_kurdish.py
```

---

## 📱 What Happens Now

### When New Lectures Upload:

**Scenario:** 5 new lectures uploaded (3 in Database Design, 2 in Data Structures)

**Bot Sends 2 Messages:**

**Message 1 (Database Design):**
```
📚 هاوڕێیان لێکچەری نوێ داندراوە!
📙 بابەت: Database Design
🔄 ژمارە: ٣ لێکچەری نوێ
📆 بەروار: ٠١/٠٢/٢٠٢٦
🕓 کاتژمێر: ٠٢:٤٩
```

**Message 2 (Data Structures):**
```
📚 هاوڕێیان لێکچەری نوێ داندراوە!
📙 بابەت: Data Structures and Algorithms
🔄 ژمارە: ٢ لێکچەری نوێ
📆 بەروار: ٠١/٠٢/٢٠٢٦
🕓 کاتژمێر: ٠٢:٤٩
```

---

## 🔍 Dashboard Features

**Statistics Panel Shows:**
- 📄 Total Lectures: 55
- 💾 Storage Used: ~XX MB
- 📚 Subjects: 9

**Organized by:**
1. **Semester** (Fall/Spring)
2. **Subject** (Database Design, Data Structures, etc.)
3. **Files** (Individual lectures)

---

## 📊 Current Database Status

```
✅ 55 lectures stored
✅ 9 subjects tracked
✅ 2 semesters (Fall + Spring)

Subjects Include:
- Data Structures and Algorithms (17 files)
- Software Engineering Principles (7 files)
- Combinatorics and Graph Theory (7 files)
- Object Oriented Programming (8 files)
- Mathematics III (4 files)
- Data Communication (2 files)
- Numerical Analysis and Probability (6 files)
- Introduction to OOP (2 files)
- Software Design and Modelling (1 file)
```

---

## 🛠️ Manual Sync

### Via Dashboard:
1. Open http://localhost:8000
2. Click **"Sync Now"** button
3. Bot sends Kurdish notifications for new lectures

### Via API:
```bash
curl -X POST http://localhost:8000/api/sync-now
```

---

## 📝 Key Features

### ✅ Kurdish Bot Messages:
- Native language (هاوڕێیان)
- Kurdish numerals (٠-٩)
- Iraq timezone (Asia/Baghdad)
- Dynamic subject names
- Grouped by subject

### ✅ Dashboard:
- Clean modern UI
- Semester organization
- Subject grouping
- Search functionality
- Download/Open buttons

### ✅ Smart Sync:
- Automatic subject detection
- No duplicate notifications
- Tracks upload dates
- Groups by semester

---

## 🎓 Subject Name Mapping

Bot automatically detects and uses exact subject names from portal:

| Kurdish Bot Will Show |
|-----------------------|
| Database Design |
| Data Structures and Algorithms |
| Object Oriented Programming |
| Software Engineering Principles |
| Combinatorics and Graph Theory |
| Mathematics III |
| Data Communication |
| Numerical Analysis and Probability |
| Software Design and Modelling with UML |

---

## 🌍 Timezone Info

**Bot Uses:** Asia/Baghdad (UTC+3)
**Format:** Kurdish numerals
**Example:** `٠١/٠٢/٢٠٢٦` at `٠٢:٤٩`

---

## ⚙️ Configuration

All settings in `.env` file:
- `TELEGRAM_BOT_TOKEN` - Already configured
- `TELEGRAM_GROUP_ID` - Already configured
- `BASE_URL` - Production URL
- `SYNC_INTERVAL_SECONDS` - Auto-sync interval (default: 3600)

---

## 🧪 Testing Commands

### Test Telegram Bot:
```bash
python test_telegram_kurdish.py
```

### Test Sync:
```bash
python test_sync.py
```

### Test Database:
```bash
python -c "import sqlite3; conn = sqlite3.connect('data/lecture_sync.db'); cursor = conn.execute('SELECT COUNT(*), COUNT(DISTINCT subject) FROM synced_items'); print(f'Files: {cursor.fetchone()}'); conn.close()"
```

---

## 📞 Telegram Bot Info

**Bot Token:** 8219473970:AAGlDEoRDCV1PMfRgvkrLMmGXiHfCfrzMXQ
**Group ID:** -1003523536992
**Status:** ✅ Active

---

## ✅ Verification Checklist

- [x] Dashboard loads with 55 lectures
- [x] Lectures organized by semester and subject
- [x] Bot sends Kurdish messages
- [x] Bot uses dynamic subject names
- [x] Bot groups by subject (separate messages)
- [x] Kurdish numerals in date/time
- [x] Iraq timezone (Asia/Baghdad)
- [x] No duplicate notifications

---

## 🎉 Ready for Production!

**Version:** SwiftSync v1.3.5 Kurdish Edition
**Status:** ✅ All Systems Operational
**Updated:** February 01, 2026

**Key Improvements:**
1. ✅ Dashboard properly displays all data
2. ✅ Telegram bot uses Kurdish language
3. ✅ Smart grouping by subject
4. ✅ Accurate date/time/count
5. ✅ Kurdish numerals support

---

**Need Help?**
- Check `KURDISH_BOT_UPDATE_COMPLETE.md` for detailed changes
- Check `TELEGRAM_BOT_COMPARISON.md` for message examples
- Run `python test_telegram_kurdish.py` to test bot

🚀 **Enjoy your upgraded SwiftSync!**
