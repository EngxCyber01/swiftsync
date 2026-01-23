"""
Migration script to add upload_date column to existing synced_items table
and populate it with the file's current modified time as a fallback.
"""
import sqlite3
from pathlib import Path
from datetime import datetime
import pytz

DB_PATH = Path("data") / "lecture_sync.db"
DOWNLOAD_DIR = Path("lectures_storage")

def migrate_upload_dates():
    """Add upload_date column and populate it with file modified times"""
    
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}")
        return
    
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        # Check if upload_date column already exists
        cursor.execute("PRAGMA table_info(synced_items)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if "upload_date" in columns:
            print("✓ upload_date column already exists")
        else:
            print("Adding upload_date column...")
            cursor.execute("ALTER TABLE synced_items ADD COLUMN upload_date TEXT")
            conn.commit()
            print("✓ upload_date column added")
        
        # Update records that don't have upload_date
        cursor.execute("SELECT id, filename, downloaded_at FROM synced_items WHERE upload_date IS NULL")
        records = cursor.fetchall()
        
        if not records:
            print("✓ All records already have upload dates")
            return
        
        print(f"Updating {len(records)} records...")
        
        for item_id, filename, downloaded_at in records:
            upload_date = None
            
            # Try to get file modified time
            if filename and DOWNLOAD_DIR.exists():
                file_path = DOWNLOAD_DIR / filename
                if file_path.exists():
                    stat = file_path.stat()
                    upload_date = datetime.fromtimestamp(stat.st_mtime).isoformat()
                    print(f"  - {filename}: Using file modified time {upload_date}")
            
            # Fallback to downloaded_at if available
            if not upload_date and downloaded_at:
                upload_date = downloaded_at
                print(f"  - {filename or item_id}: Using downloaded_at {upload_date}")
            
            # Last resort: use current time (Iraq timezone)
            if not upload_date:
                upload_date = datetime.now(pytz.timezone('Asia/Baghdad')).isoformat()
                print(f"  - {filename or item_id}: Using current time {upload_date}")
            
            cursor.execute("UPDATE synced_items SET upload_date = ? WHERE id = ?", (upload_date, item_id))
        
        conn.commit()
        print(f"✓ Successfully updated {len(records)} records")

if __name__ == "__main__":
    print("Starting migration...")
    migrate_upload_dates()
    print("\n✓ Migration complete!")
    print("\nFrom now on:")
    print("  - New lectures will store the server's Last-Modified date as upload_date")
    print("  - Re-syncing won't change the upload_date (it stays constant)")
    print("  - Your system will show the original upload date from the portal")
