"""
Test Telegram notification with Kurdish messages
"""
import logging
from telegram_notifier import notify_multiple_lectures, notify_new_lecture
from pathlib import Path

logging.basicConfig(level=logging.INFO)

print("🧪 Testing Telegram Kurdish Notifications\n")

# Test 1: Multiple lectures in a specific subject
print("Test 1: Multiple lectures notification (Database Design)")
result1 = notify_multiple_lectures(
    file_count=5,
    subject="Database Design"
)
print(f"Result: {'✅ Success' if result1 else '❌ Failed'}\n")

# Test 2: Multiple lectures in another subject
print("Test 2: Multiple lectures notification (Data Structures)")
result2 = notify_multiple_lectures(
    file_count=3,
    subject="Data Structures and Algorithms"
)
print(f"Result: {'✅ Success' if result2 else '❌ Failed'}\n")

# Test 3: Single lecture notification
print("Test 3: Single lecture notification")
test_file = Path("lectures_storage/test_lecture.pdf")
result3 = notify_new_lecture(
    file_path=test_file,
    subject="Object Oriented Programming",
    base_url="https://swiftsync-013r.onrender.com"
)
print(f"Result: {'✅ Success' if result3 else '❌ Failed'}\n")

print("✅ All tests completed! Check your Telegram group for messages.")
