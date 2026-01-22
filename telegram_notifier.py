"""
Telegram Bot Notifier for SwiftSync
Sends notifications to Telegram group when new lectures are uploaded
"""
import logging
import requests
from datetime import datetime
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
    instructor_name: Optional[str] = None,
    upload_date: Optional[str] = None,
    lecture_link: Optional[str] = None
) -> str:
    """
    Format a lecture notification message with nice design
    
    Args:
        lecture_title: The title/name of the lecture file
        course_name: The name of the course/subject
        instructor_name: Name of the instructor (optional)
        upload_date: Date of upload
        lecture_link: Optional link to access the lecture
    
    Returns:
        Formatted message string with Markdown formatting
    """
    # Format the date nicely
    if not upload_date:
        upload_date = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    
    # Build the message with emojis and formatting
    message_parts = [
        "📚 *New Lecture Uploaded!*",
        "",
    ]
    
    if course_name:
        message_parts.append(f"🎓 *Course:* {course_name}")
    
    message_parts.append(f"📖 *Lecture:* {lecture_title}")
    
    if instructor_name:
        message_parts.append(f"👨‍🏫 *Instructor:* {instructor_name}")
    
    message_parts.append(f"📅 *Date:* {upload_date}")
    message_parts.append("")
    message_parts.append("🚀 Stay focused and happy learning!")
    
    if lecture_link:
        message_parts.append(f"🔗 [Watch here]({lecture_link})")
    
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
        
        # Create a lecture link if base_url is provided
        lecture_link = None
        if base_url:
            # Construct the link to the file
            relative_path = str(file_path).replace("\\", "/")
            # Extract just the filename for the URL
            filename = file_path.name
            lecture_link = f"{base_url}/files/{filename}"
        
        # Format the message
        message = format_lecture_notification(
            lecture_title=lecture_title,
            course_name=subject or "General Studies",
            instructor_name=None,  # Can be enhanced later to extract instructor info
            upload_date=datetime.now().strftime("%B %d, %Y at %I:%M %p"),
            lecture_link=lecture_link
        )
        
        # Send the notification
        return send_telegram_message(message)
        
    except Exception as e:
        logger.exception(f"Error notifying about new lecture: {e}")
        return False


def notify_multiple_lectures(
    file_count: int,
    subject: Optional[str] = None,
    upload_date: Optional[str] = None
) -> bool:
    """
    Send a summary notification when multiple lectures are uploaded
    
    Args:
        file_count: Number of new lectures
        subject: Subject/course name if applicable
        upload_date: Actual upload date from the platform (not notification time)
    
    Returns:
        True if notification was sent successfully
    """
    try:
        subject_info = f" in *{subject}*" if subject else ""
        
        # Use provided upload date or current time
        date_str = upload_date if upload_date else datetime.now().strftime("%B %d, %Y at %I:%M %p")
        
        message = f"""📚 *Multiple New Lectures Uploaded!*

🎓 *Count:* {file_count} new lectures{subject_info}
📅 *Date:* {date_str}

🚀 Stay focused and happy learning!
💪 Keep up the great work!"""
        
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
