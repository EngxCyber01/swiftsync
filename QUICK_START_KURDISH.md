# ðŸš€ Quick Start Guide - SwiftSync v1.3.5 Kurdish Bot

## âœ… What Was Fixed

1. **Dashboard Loading** - Now properly displays all 55 lectures with subjects
2. **Telegram Bot** - Upgraded to Kurdish language with dynamic subject info
3. **Smart Notifications** - Groups lectures by subject, sends separate messages

---

## ðŸŽ¯ How to Run

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

## ðŸ“± What Happens Now

### When New Lectures Upload:

**Scenario:** 5 new lectures uploaded (3 in Database Design, 2 in Data Structures)

**Bot Sends 2 Messages:**

**Message 1 (Database Design):**
```
ðŸ“š Ù‡Ø§ÙˆÚ•ÛŽÛŒØ§Ù† Ù„ÛŽÚ©Ú†Û•Ø±ÛŒ Ù†ÙˆÛŽ Ø¯Ø§Ù†Ø¯Ø±Ø§ÙˆÛ•!
ðŸ“™ Ø¨Ø§Ø¨Û•Øª: Database Design
ðŸ”„ Ú˜Ù…Ø§Ø±Û•: Ù£ Ù„ÛŽÚ©Ú†Û•Ø±ÛŒ Ù†ÙˆÛŽ
ðŸ“† Ø¨Û•Ø±ÙˆØ§Ø±: Ù Ù¡/Ù Ù¢/Ù¢Ù Ù¢Ù¦
ðŸ•“ Ú©Ø§ØªÚ˜Ù…ÛŽØ±: Ù Ù¢:Ù¤Ù©
```

**Message 2 (Data Structures):**
```
ðŸ“š Ù‡Ø§ÙˆÚ•ÛŽÛŒØ§Ù† Ù„ÛŽÚ©Ú†Û•Ø±ÛŒ Ù†ÙˆÛŽ Ø¯Ø§Ù†Ø¯Ø±Ø§ÙˆÛ•!
ðŸ“™ Ø¨Ø§Ø¨Û•Øª: Data Structures and Algorithms
ðŸ”„ Ú˜Ù…Ø§Ø±Û•: Ù¢ Ù„ÛŽÚ©Ú†Û•Ø±ÛŒ Ù†ÙˆÛŽ
ðŸ“† Ø¨Û•Ø±ÙˆØ§Ø±: Ù Ù¡/Ù Ù¢/Ù¢Ù Ù¢Ù¦
ðŸ•“ Ú©Ø§ØªÚ˜Ù…ÛŽØ±: Ù Ù¢:Ù¤Ù©
```

---

## ðŸ” Dashboard Features

**Statistics Panel Shows:**
- ðŸ“„ Total Lectures: 55
- ðŸ’¾ Storage Used: ~XX MB
- ðŸ“š Subjects: 9

**Organized by:**
1. **Semester** (Fall/Spring)
2. **Subject** (Database Design, Data Structures, etc.)
3. **Files** (Individual lectures)

---

## ðŸ“Š Current Database Status

```
âœ… 55 lectures stored
âœ… 9 subjects tracked
âœ… 2 semesters (Fall + Spring)

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

## ðŸ› ï¸ Manual Sync

### Via Dashboard:
1. Open http://localhost:8000
2. Click **"Sync Now"** button
3. Bot sends Kurdish notifications for new lectures

### Via API:
```bash
curl -X POST http://localhost:8000/api/sync-now
```

---

## ðŸ“ Key Features

### âœ… Kurdish Bot Messages:
- Native language (Ù‡Ø§ÙˆÚ•ÛŽÛŒØ§Ù†)
- Kurdish numerals (Ù -Ù©)
- Iraq timezone (Asia/Baghdad)
- Dynamic subject names
- Grouped by subject

### âœ… Dashboard:
- Clean modern UI
- Semester organization
- Subject grouping
- Search functionality
- Download/Open buttons

### âœ… Smart Sync:
- Automatic subject detection
- No duplicate notifications
- Tracks upload dates
- Groups by semester

---

## ðŸŽ“ Subject Name Mapping

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

## ðŸŒ Timezone Info

**Bot Uses:** Asia/Baghdad (UTC+3)
**Format:** Kurdish numerals
**Example:** `Ù Ù¡/Ù Ù¢/Ù¢Ù Ù¢Ù¦` at `Ù Ù¢:Ù¤Ù©`

---

## âš™ï¸ Configuration

All settings in `.env` file:
- `TELEGRAM_BOT_TOKEN` - Already configured
- `TELEGRAM_GROUP_ID` - Already configured
- `BASE_URL` - Production URL
- `SYNC_INTERVAL_SECONDS` - Auto-sync interval (default: 3600)

---

## ðŸ§ª Testing Commands

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

## ðŸ“ž Telegram Bot Info

**Bot Token:** your_telegram_bot_token_here
**Group ID:** your_telegram_chat_id_here
**Status:** âœ… Active

---

## âœ… Verification Checklist

- [x] Dashboard loads with 55 lectures
- [x] Lectures organized by semester and subject
- [x] Bot sends Kurdish messages
- [x] Bot uses dynamic subject names
- [x] Bot groups by subject (separate messages)
- [x] Kurdish numerals in date/time
- [x] Iraq timezone (Asia/Baghdad)
- [x] No duplicate notifications

---

## ðŸŽ‰ Ready for Production!

**Version:** SwiftSync v1.3.5 Kurdish Edition
**Status:** âœ… All Systems Operational
**Updated:** February 01, 2026

**Key Improvements:**
1. âœ… Dashboard properly displays all data
2. âœ… Telegram bot uses Kurdish language
3. âœ… Smart grouping by subject
4. âœ… Accurate date/time/count
5. âœ… Kurdish numerals support

---

**Need Help?**
- Check `KURDISH_BOT_UPDATE_COMPLETE.md` for detailed changes
- Check `TELEGRAM_BOT_COMPARISON.md` for message examples
- Run `python test_telegram_kurdish.py` to test bot

ðŸš€ **Enjoy your upgraded SwiftSync!**

