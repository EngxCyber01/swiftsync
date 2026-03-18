"""
Telegram Bot Notifier for SwiftSync
Sends notifications to Telegram group when new lectures are uploaded
"""
import logging
import requests
from datetime import datetime
import pytz
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# Telegram Configuration
TELEGRAM_BOT_TOKEN = "8219473970:AAGlDEoRDCV1PMfRgvkrLMmGXiHfCfrzMXQ"
TELEGRAM_GROUP_ID = "-1003523536992"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def send_telegram_message(message: str, parse_mode: str = "Markdown") -> bool:
    """
    Send a message to the Telegram group
    
    Args:
        message: The formatted message to send
        parse_mode: Either 'Markdown' or 'HTML' for formatting
    
    Returns:
        True if message was sent successfully, False otherwise
    """
    try:
        url = f"{TELEGRAM_API_URL}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_GROUP_ID,
            "text": message,
            "parse_mode": parse_mode,
            "disable_web_page_preview": False
        }
        
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        
        logger.info("Telegram notification sent successfully")
        return True
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send Telegram notification: {e}")
        return False
    except Exception as e:
        logger.exception(f"Unexpected error sending Telegram notification: {e}")
        return False


def format_lecture_notification(
    lecture_title: str,
    course_name: Optional[str] = None,
    lecture_number: Optional[int] = None,
    upload_date: Optional[str] = None,
    lecture_link: Optional[str] = None
) -> str:
    """
    Format a lecture notification message with Kurdish design
    
    Args:
        lecture_title: The title/name of the lecture file
        course_name: The name of the course/subject
        lecture_number: Lecture number (optional)
        upload_date: Date of upload
        lecture_link: Optional link to access the lecture
    
    Returns:
        Formatted message string with Kurdish text
    """
    # Format the date nicely (Iraq timezone: Asia/Baghdad UTC+3)
    iraq_tz = pytz.timezone('Asia/Baghdad')
    current_time = datetime.now(iraq_tz)
    
    # Format date (dd/mm/yyyy) and time (12-hour format with AM/PM)
    date_formatted = current_time.strftime("%d/%m/%Y")
    time_formatted = current_time.strftime("%I:%M %p")
    
    # Build the clean, professional message
    message_parts = [
        "📢 ئاگاداری نوێ",
        "",
        "لێکچەری نوێ بۆ ئەم بابەتە زیادکرا:",
    ]
    
    # Add subject name with emoji
    if course_name:
        message_parts.append(f"📘 {course_name}")
    else:
        message_parts.append(f"📘 {lecture_title}")
    
    message_parts.append("")
    
    # Add lecture number if available
    if lecture_number:
        message_parts.append(f"🔹 لێکچەر: {lecture_number}")
    
    # Add date and time on separate lines
    message_parts.append(f"📅 {date_formatted}")
    message_parts.append(f"🕒 {time_formatted}")
    
    message_parts.append("")
    message_parts.append("✅ لە سیستەمەکەدا ئامادەیە")
    
    # Add link at the end
    if lecture_link:
        message_parts.append("🔗 بۆ بینینی لێکچەرەکە:")
        message_parts.append(lecture_link)
    
    return "\n".join(message_parts)


def notify_new_lecture(
    file_path: Path,
    subject: Optional[str] = None,
    base_url: Optional[str] = None
) -> bool:
    """
    Send notification about a newly downloaded lecture
    
    Args:
        file_path: Path to the downloaded lecture file
        subject: Subject/course name
        base_url: Base URL of the application for generating links
    
    Returns:
        True if notification was sent successfully
    """
    try:
        # Extract filename and create a clean title
        lecture_title = file_path.stem.replace("_", " ").replace("-", " ")
        
        # Try to extract lecture number from filename (e.g., "lecture 7", "L7", "7", etc.)
        import re
        lecture_number = None
        
        # Try different patterns to extract lecture number
        patterns = [
            r'lecture[_\-\s]*(\d+)',  # "lecture 7", "lecture_7", "lecture-7"
            r'l[_\-\s]*(\d+)',        # "l7", "l_7", "l-7", "L7"
            r'lec[_\-\s]*(\d+)',      # "lec7", "lec_7"
            r'^(\d+)',                # Starting with number
            r'[_\-\s](\d+)$',         # Ending with number
        ]
        
        filename_lower = file_path.stem.lower()
        for pattern in patterns:
            match = re.search(pattern, filename_lower)
            if match:
                lecture_number = int(match.group(1))
                break
        
        # Create system link (main dashboard URL)
        system_link = base_url if base_url else "https://swiftsync-013r.onrender.com/"
        
        # Format the message
        message = format_lecture_notification(
            lecture_title=lecture_title,
            course_name=subject,
            lecture_number=lecture_number,
            upload_date=datetime.now(pytz.timezone('Asia/Baghdad')).strftime("%B %d, %Y at %I:%M %p"),
            lecture_link=system_link
        )
        
        # Send the notification (use HTML parse mode for better link rendering)
        return send_telegram_message(message, parse_mode=None)
        
    except Exception as e:
        logger.exception(f"Error notifying about new lecture: {e}")
        return False


def notify_multiple_lectures(
    file_count: int,
    subject: Optional[str] = None,
    upload_date: Optional[str] = None
) -> bool:
    """
    Send a summary notification when multiple lectures are uploaded (Kurdish version)
    
    Args:
        file_count: Number of new lectures
        subject: Subject/course name if applicable
        upload_date: Actual upload date from the platform (not notification time)
    
    Returns:
        True if notification was sent successfully
    """
    try:
        # Get Iraq timezone (Asia/Baghdad UTC+3)
        iraq_tz = pytz.timezone('Asia/Baghdad')
        current_time = datetime.now(iraq_tz)
        
        # Format date and time in Kurdish numerals
        date_formatted = current_time.strftime("%d/%m/%Y").replace('0', '٠').replace('1', '١').replace('2', '٢').replace('3', '٣').replace('4', '٤').replace('5', '٥').replace('6', '٦').replace('7', '٧').replace('8', '٨').replace('9', '٩')
        time_formatted = current_time.strftime("%I:%M").replace('0', '٠').replace('1', '١').replace('2', '٢').replace('3', '٣').replace('4', '٤').replace('5', '٥').replace('6', '٦').replace('7', '٧').replace('8', '٨').replace('9', '٩')
        count_formatted = str(file_count).replace('0', '٠').replace('1', '١').replace('2', '٢').replace('3', '٣').replace('4', '٤').replace('5', '٥').replace('6', '٦').replace('7', '٧').replace('8', '٨').replace('9', '٩')
        
        # Use subject name if provided, otherwise use generic text
        subject_name = subject if subject else "بابەتی جیاواز"
        
        message = f"""📚 لێکچەری نوێ داندراوە!
📙 بابەت: {subject_name}
🔄 ژمارە: {count_formatted} لێکچەری نوێ
📆 بەروار: {date_formatted}
🕓 کاتژمێر: {time_formatted}"""
        
        return send_telegram_message(message)
        
    except Exception as e:
        logger.exception(f"Error notifying about multiple lectures: {e}")
        return False


def test_telegram_connection() -> bool:
    """
    Test if the Telegram bot can send messages
    
    Returns:
        True if connection is working
    """
    try:
        message = "✅ *SwiftSync Telegram Bot is Connected!*\n\nBot is ready to send lecture notifications."
        return send_telegram_message(message)
    except Exception as e:
        logger.exception(f"Telegram connection test failed: {e}")
        return False


if __name__ == "__main__":
    # Test the notification system
    logging.basicConfig(level=logging.INFO)
    print("Testing Telegram notification...")
    
    if test_telegram_connection():
        print("✅ Telegram bot is working!")
    else:
        print("❌ Telegram bot test failed")
