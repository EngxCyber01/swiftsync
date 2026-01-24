import sqlite3

# Fall semester subjects
fall_subjects = [
    'Combinatorics and Graph Theory',
    'Database Principles', 
    'Data Structures and Algorithms',
    'Mathematics III',
    'Software Engineering Principles',
    'Introduction to OOP'
]

# Spring semester subjects
spring_subjects = [
    'Numerical Analysis and Probability',
    'Data Communication',
    'Object Oriented Programming'
]

conn = sqlite3.connect('data/lecture_sync.db')
cursor = conn.cursor()

# Update Fall semester subjects
for subject in fall_subjects:
    cursor.execute('UPDATE synced_items SET semester = ? WHERE subject = ?', ('Fall Semester', subject))
    print(f'Updated {cursor.rowcount} records for {subject} -> Fall Semester')

# Update Spring semester subjects  
for subject in spring_subjects:
    cursor.execute('UPDATE synced_items SET semester = ? WHERE subject = ?', ('Spring Semester', subject))
    print(f'Updated {cursor.rowcount} records for {subject} -> Spring Semester')

conn.commit()
conn.close()
print('\n✓ Database updated with semester assignments')
