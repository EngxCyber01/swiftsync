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
    # Iraq timezone (UTC+3)
    iraq_tz = pytz.timezone('Asia/Baghdad')
    now = datetime.now(iraq_tz)

    # Keep date/time compact and readable for students
    date_formatted = now.strftime("%d/%m/%Y")
    time_formatted = now.strftime("%I:%M %p").lstrip("0")

    subject_name = course_name if course_name else lecture_title
    lecture_number_text = str(lecture_number) if lecture_number is not None else "-"
    system_link = lecture_link if lecture_link else "https://swiftsync-013r.onrender.com/"

    # Polished production format requested by user
    return (
        "📢 ئاگاداری نوێ\n\n"
        "لێکچەرێکی نوێ بۆ ئەم بابەتە زیادکرا:\n"
        f"📘 {subject_name}\n\n"
        f"🔹 لێکچەر: {lecture_number_text}\n"
        f"📅 {date_formatted}\n"
        f"🕒 {time_formatted}\n\n"
        "✅ لە سیستەمەکەدا ئامادەیە\n"
        "🔗 بۆ بینینی لێکچەرەکە:\n"
        f"{system_link}"
    )


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
    upload_date: Optional[str] = None,
    base_url: Optional[str] = None
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

        date_formatted = current_time.strftime("%d/%m/%Y")
        time_formatted = current_time.strftime("%I:%M %p").lstrip("0")

        # Use subject name if provided, otherwise use generic text
        subject_name = subject if subject else "بابەتی جیاواز"
        system_link = base_url if base_url else "https://swiftsync-013r.onrender.com/"

        message = (
            "📢 ئاگاداری نوێ\n\n"
            "چەند لێکچەرێکی نوێ بۆ ئەم بابەتە زیادکرا:\n"
            f"📘 {subject_name}\n\n"
            f"🔹 ژمارەی لێکچەرە نوێکان: {file_count}\n"
            f"📅 {date_formatted}\n"
            f"🕒 {time_formatted}\n\n"
            "✅ لە سیستەمەکەدا ئامادەیە\n"
            "🔗 بۆ بینینی لێکچەرەکان:\n"
            f"{system_link}"
        )

        return send_telegram_message(message, parse_mode=None)
        
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
