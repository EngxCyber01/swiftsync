"""Migrate database to add subject and filename columns"""
import sqlite3
from pathlib import Path

DB_PATH = Path("data/lecture_sync.db")


def migrate_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check if columns exist
    cursor.execute("PRAGMA table_info(synced_items)")
    columns = [row[1] for row in cursor.fetchall()]
    
    print(f"Current columns: {columns}")
    
    # Add subject column if missing
    if 'subject' not in columns:
        print("Adding subject column...")
        cursor.execute("ALTER TABLE synced_items ADD COLUMN subject TEXT")
        conn.commit()
        print("✓ Added subject column")
    
    # Add filename column if missing
    if 'filename' not in columns:
        print("Adding filename column...")
        cursor.execute("ALTER TABLE synced_items ADD COLUMN filename TEXT")
        conn.commit()
        print("✓ Added filename column")
    
    conn.close()
    print("Database migration complete!")


if __name__ == "__main__":
    migrate_database()
