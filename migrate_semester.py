"""
Database migration to add semester field
"""
import sqlite3
from pathlib import Path

DB_PATH = Path("data") / "lecture_sync.db"

def migrate_add_semester():
    """Add semester column to synced_items table"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        # Add semester column if it doesn't exist
        try:
            cursor.execute("ALTER TABLE synced_items ADD COLUMN semester TEXT DEFAULT 'Spring 2025/2026'")
            print("✅ Added semester column to database")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                print("✓ Semester column already exists")
            else:
                raise
        
        conn.commit()
        print("✅ Migration completed successfully")

if __name__ == "__main__":
    migrate_add_semester()
