"""
Migration script to update semester classification for Spring subjects
Fixes existing database records that were incorrectly classified as Fall Semester
"""
import sqlite3
from pathlib import Path

def migrate_to_spring():
    """Update semester classification for Spring subjects in the database"""
    db_path = Path(__file__).parent / "data" / "lecture_sync.db"
    
    if not db_path.exists():
        print("❌ Database not found at:", db_path)
        return
    
    spring_subjects = [
        'Numerical Analysis and Probability',
        'Data Communication',
        'Object Oriented Programming',
        'Software Design and Modelling with UML'
    ]
    
    try:
        with sqlite3.connect(db_path) as conn:
            # Update all spring subjects to Spring Semester
            for subject in spring_subjects:
                result = conn.execute(
                    "UPDATE synced_items SET semester = 'Spring Semester' WHERE subject = ? AND semester != 'Spring Semester'",
                    (subject,)
                )
                if result.rowcount > 0:
                    print(f"✅ Updated {result.rowcount} records for '{subject}' to Spring Semester")
            
            conn.commit()
            
            # Show current semester distribution
            cursor = conn.execute("""
                SELECT semester, COUNT(*) as count 
                FROM synced_items 
                WHERE semester IS NOT NULL 
                GROUP BY semester
            """)
            
            print("\n📊 Current semester distribution:")
            for row in cursor.fetchall():
                print(f"   {row[0]}: {row[1]} items")
                
    except Exception as e:
        print(f"❌ Error during migration: {e}")

if __name__ == "__main__":
    print("🔄 Starting semester migration...")
    migrate_to_spring()
    print("\n✅ Migration complete!")
