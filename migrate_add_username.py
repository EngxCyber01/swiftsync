"""
Database migration: Add username column to visitor_logs table
Run this before deploying to update existing databases
"""
import sqlite3
from pathlib import Path

DB_PATH = Path("data") / "lecture_sync.db"

def migrate_add_username_column():
    """Add username column to visitor_logs if it doesn't exist"""
    print("🔄 Starting database migration...")
    
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        # Check if username column already exists
        cursor.execute("PRAGMA table_info(visitor_logs)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'username' not in columns:
            print("✅ Adding 'username' column to visitor_logs table...")
            cursor.execute("""
                ALTER TABLE visitor_logs ADD COLUMN username TEXT
            """)
            conn.commit()
            print("✅ Migration completed successfully!")
        else:
            print("✅ Username column already exists, no migration needed.")
    
    print("\n📊 Database updated successfully!")
    print("   - Real IP addresses will now be captured")
    print("   - Student/usernames will be logged")
    print("   - Admin portal will show student info\n")

if __name__ == "__main__":
    migrate_add_username_column()
