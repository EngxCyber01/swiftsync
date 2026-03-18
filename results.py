"""
Results Module for SwiftSync
Handles fetching and parsing result-related notifications from the real college system
Uses notification API as the source for student results
Saves results to database for persistence
"""

import asyncio
import requests
from bs4 import BeautifulSoup
from typing import Optional, Dict, Any, List
import re
from datetime import datetime

# Import database functions for result storage
from database import save_result, get_student_results, result_exists


class ResultsService:
    """Service for fetching and parsing result notifications"""
    
    BASE_URL = "https://tempapp-su.awrosoft.com"
    NOTIFICATIONS_ENDPOINT = f"{BASE_URL}/Notification/ListRows"
    # Alternative endpoints to try if main one doesn't work
    ALT_ENDPOINTS = [
        f"{BASE_URL}/Notifications/GetNotifications",
        f"{BASE_URL}/Portal/GetNotifications",
        f"{BASE_URL}/University/Notifications/GetList",
    ]
    REQUEST_TIMEOUT = 15  # seconds
    
    # Keywords that indicate result-related notifications
    RESULT_KEYWORDS = [
        'result', 'نتيجة', 'نەتیجە',
        'exam', 'ئەڵاڵەسا', 'امتحان',
        'mark', 'نمرة', 'نمره',
        'grade', 'پلە', 'درجة',
        'score', 'خالد', 'ئەڵسا',
        'pass', 'ناجح', 'سەرکەوتوو',
        'fail', 'راسب', 'شکستخواردوو',
        'semester result', 'final result',
        'نەتیجەی وەرزی', 'نتيجة الفصل',
        'degree', 'پلە', 'دەرەجە'
    ]
    
    def __init__(self):
        pass
    
    def _is_result_notification(self, notification_text: str) -> bool:
        """
        Check if notification text is result-related
        Uses flexible keyword matching to avoid missing results
        """
        if not notification_text:
            return False
        
        text_lower = notification_text.lower()
        
        # Check if any result keyword appears in the notification
        for keyword in self.RESULT_KEYWORDS:
            if keyword.lower() in text_lower:
                print(f"DEBUG: Found result keyword '{keyword}' in notification")
                return True
        
        print(f"DEBUG: No result keywords found in notification")
        return False
    
    def _parse_notification_text(self, text: str, description: str = '') -> Dict[str, Any]:
        """
        Parse notification text to extract structured result data
        Format: "Your result of quiz2 of Computer Architecture - Software_S_25-26 class is 3.5"
        """
        result = {
            'raw_text': text,
            'subject': None,
            'exam_type': None,
            'score': None,
            'grade': None,
            'semester': None,
            'status': None
        }
        
        # Use description field which has complete information
        parse_text = description if description else text
        
        if not parse_text:
            return result
        
        print(f"DEBUG: Parsing from description: {parse_text}")
        
        # College format: "Your result of [Exam] of [Subject] - [Semester] class is [Score]"
        # Example: "Your result of quiz2 of Computer Architecture - Software_S_25-26 class is 3.5"
        full_pattern = r'Your result of\s+(.+?)\s+of\s+(.+?)\s+-\s+(.+?)\s+class is\s+([\d.]+)'
        match = re.search(full_pattern, parse_text, re.IGNORECASE)
        
        if match:
            result['exam_type'] = match.group(1).strip()
            result['subject'] = match.group(2).strip()
            result['semester'] = match.group(3).strip()
            result['score'] = match.group(4).strip()
            print(f"DEBUG: ✓ Parsed - Exam: {result['exam_type']}, Subject: {result['subject']}, Score: {result['score']}, Semester: {result['semester']}")
        else:
            # Fallback: Try simpler pattern without semester
            # "Your result of [Exam] of [Subject] ... class is [Score]"
            simple_pattern = r'Your result of\s+(.+?)\s+of\s+(.+?)\s+.*?class is\s+([\d.]+)'
            match = re.search(simple_pattern, parse_text, re.IGNORECASE)
            if match:
                result['exam_type'] = match.group(1).strip()
                result['subject'] = match.group(2).strip()
                result['score'] = match.group(3).strip()
                print(f"DEBUG: ✓ Parsed (simple) - Exam: {result['exam_type']}, Subject: {result['subject']}, Score: {result['score']}")
            else:
                print(f"DEBUG: ✗ Failed to parse, trying fallback patterns...")
        
        # Extract score from "class is X" pattern
        score_pattern = r'class\s+is\s+(\d+(?:\.\d+)?)'
        score_match = re.search(score_pattern, text, re.IGNORECASE)
        if score_match:
            result['score'] = score_match.group(1)
            print(f"DEBUG: Found score from 'class is': {result['score']}")
        
        # Also try other score patterns
        if not result['score']:
            # Look for standalone numbers that might be scores
            score_patterns = [
                r'(?:score|mark|grade|result)[:\s]+(\d+(?:\.\d+)?)',
                r'(\d+(?:\.\d+)?)\s*/\s*(\d+)',
                r'(\d+(?:\.\d+)?)\s+(?:out of|من)\s+(\d+)',
            ]
            for pattern in score_patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    groups = match.groups()
                    if len(groups) == 2:
                        result['score'] = f"{groups[0]}/{groups[1]}"
                    else:
                        result['score'] = groups[0]
                    print(f"DEBUG: Found score: {result['score']}")
                    break
        
        # Extract grade (A, B, C, etc.)
        grade_patterns = [
            r'\bgrade[:\s]+([A-F][+-]?)\b',
            r'\b([A-F][+-]?)\s+grade\b',
            r'\b([A-F][+-]?)\b(?=\s|$)',
        ]
        for pattern in grade_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                result['grade'] = match.group(1).upper()
                print(f"DEBUG: Found grade: {result['grade']}")
                break
        
        # Extract semester/class info from "Software_S_25-26" pattern
        semester_pattern = r'(Software|Hardware|[A-Za-z]+)_[A-Z]_\d{2}-\d{2}'
        sem_match = re.search(semester_pattern, text)
        if sem_match:
            result['semester'] = sem_match.group(0)
            print(f"DEBUG: Found semester/class: {result['semester']}")
        
        # Try to extract stage/year number
        if not result['semester']:
            stage_patterns = [
                r'(?:stage|year|level|class)\s*[:\s]*(\d+)',
                r'(first|second|third|fourth)\s*(?:stage|year)',
                r'(\d)(?:st|nd|rd|th)\s*(?:stage|year)',
            ]
            for pattern in stage_patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    result['semester'] = match.group(1)
                    print(f"DEBUG: Found stage: {result['semester']}")
                    break
        
        # Determine status based on score
        if result['score']:
            try:
                # Try to parse score as number
                score_val = float(result['score'].split('/')[0] if '/' in result['score'] else result['score'])
                # Assume passing is >= 50 or >= 5 (depending on scale)
                if score_val >= 50 or (score_val >= 5 and score_val <= 10):
                    result['status'] = 'passed'
                    print(f"DEBUG: Status: passed (score >= threshold)")
                else:
                    result['status'] = 'failed'
                    print(f"DEBUG: Status: failed (score < threshold)")
            except:
                pass
        
        # Check for explicit pass/fail words
        if re.search(r'\b(pass|passed|success|successful|ناجح|سەرکەوتوو)\b', text, re.IGNORECASE):
            result['status'] = 'passed'
            print(f"DEBUG: Status: passed (found keyword)")
        elif re.search(r'\b(fail|failed|unsuccessful|راسب|شکستخواردوو)\b', text, re.IGNORECASE):
            result['status'] = 'failed'
            print(f"DEBUG: Status: failed (found keyword)")
        
        print(f"DEBUG: Final parsed result: subject={result['subject']}, exam={result['exam_type']}, score={result['score']}, grade={result['grade']}")
        return result
    
    async def get_results(self, session_token: str, session_manager) -> Dict[str, Any]:
        """
        Fetch results from notification API and save to database
        Returns stored results from database for persistence
        
        Args:
            session_token: Valid session token from attendance login
            session_manager: SessionManager instance from attendance.py
        
        Returns:
            {
                success: bool,
                results: List[Dict],  # List of parsed result items from database
                error: str,
                new_results_saved: int  # Count of new results saved in this fetch
            }
        """
        # Validate session
        session = session_manager.get_session(session_token)
        if not session:
            return {
                'success': False,
                'error': 'Session expired or invalid. Please login again.',
                'results': []
            }
        
        cookies = session['cookies']
        student_id = session.get('student_id', '')
        
        new_results_saved = 0
        
        try:
            # Fetch ALL pages of notifications with pagination
            all_notifications = []
            page_number = 1
            page_size = 10  # Default page size from API
            
            while True:
                # Add pagination parameters to endpoint
                paginated_endpoint = f"{self.NOTIFICATIONS_ENDPOINT}?PageNumber={page_number}&PageSize={page_size}"
                print(f"DEBUG: Fetching page {page_number} from: {paginated_endpoint}")
                
                notifications = await self._fetch_notifications(paginated_endpoint, cookies)
                
                # If no notifications returned, we've reached the end
                if not notifications or len(notifications) == 0:
                    print(f"DEBUG: No more notifications on page {page_number}, stopping pagination")
                    break
                
                print(f"DEBUG: Page {page_number} returned {len(notifications)} notifications")
                all_notifications.extend(notifications)
                
                # If we got less than page_size, we're on the last page
                if len(notifications) < page_size:
                    print(f"DEBUG: Last page reached (got {len(notifications)} < {page_size})")
                    break
                
                page_number += 1
                
                # Safety limit to prevent infinite loops
                if page_number > 100:
                    print(f"DEBUG: Safety limit reached at page 100, stopping")
                    break
            
            print(f"DEBUG: Total notifications fetched across {page_number} pages: {len(all_notifications)}")
            
            # Process all fetched notifications
            if all_notifications:
                print(f"DEBUG: Processing {len(all_notifications)} notifications")
                # Filter and save result-related notifications
                for notification in all_notifications:
                    text = notification.get('text', '')
                    description = notification.get('description', '')
                    notification_id = str(notification.get('id', ''))
                    date = notification.get('date', '')
                    
                    if not notification_id or not text:
                        continue
                    
                    # Check if result-related (check both text and description)
                    check_text = f"{text} {description}"
                    print(f"DEBUG: Checking notification {notification_id}: '{text[:50]}...'")
                    if self._is_result_notification(check_text):
                        print(f"DEBUG: ✓ Notification {notification_id} is result-related")
                        # Check if already saved for THIS student (avoid duplicates per student)
                        if not result_exists(notification_id, student_id):
                            print(f"DEBUG: Notification {notification_id} is new for student {student_id}, parsing and saving...")
                            # Parse the notification using description field
                            parsed = self._parse_notification_text(text, description)
                            parsed['raw_text'] = check_text
                            parsed['exam_date'] = date
                            
                            # Only save if semester is valid (not empty/unknown)
                            if parsed.get('semester') and parsed['semester'].strip():
                                # Save to database
                                if save_result(student_id, notification_id, parsed):
                                    new_results_saved += 1
                                    print(f"DEBUG: ✓ Saved result {new_results_saved}: {parsed.get('subject', 'Unknown')} - {parsed.get('exam_type', 'Unknown')}")
                                else:
                                    print(f"DEBUG: ✗ Failed to save notification {notification_id}")
                            else:
                                print(f"DEBUG: ✗ Skipping result {notification_id} - no valid semester found")
                        else:
                            print(f"DEBUG: Notification {notification_id} already exists for student {student_id}")
                    else:
                        print(f"DEBUG: ✗ Notification {notification_id} is NOT result-related")
            else:
                print(f"DEBUG: No notifications received from API")
            
            # Fetch results from database (this is our persistent source)
            print(f"DEBUG: Fetching stored results for student {student_id}")
            stored_results = get_student_results(student_id, limit=100)
            print(f"DEBUG: Found {len(stored_results)} stored results in database")
            
            # Format results for frontend
            result_items = []
            for stored in stored_results:
                result_item = {
                    'id': stored.get('notification_id', ''),
                    'date': stored.get('exam_date', stored.get('created_at', '')),
                    'raw_text': stored.get('raw_text', ''),
                    'subject': stored.get('subject'),
                    'exam_type': stored.get('exam_type'),
                    'score': stored.get('score'),
                    'grade': stored.get('grade'),
                    'semester': stored.get('semester'),
                    'status': stored.get('status'),
                }
                result_items.append(result_item)
            
            return {
                'success': True,
                'results': result_items,
                'total_count': len(result_items),
                'new_results_saved': new_results_saved
            }
        
        except Exception as e:
            # If API fetch fails, still try to return stored results
            try:
                stored_results = get_student_results(student_id, limit=100)
                result_items = []
                for stored in stored_results:
                    result_item = {
                        'id': stored.get('notification_id', ''),
                        'date': stored.get('exam_date', stored.get('created_at', '')),
                        'raw_text': stored.get('raw_text', ''),
                        'subject': stored.get('subject'),
                        'exam_type': stored.get('exam_type'),
                        'score': stored.get('score'),
                        'grade': stored.get('grade'),
                        'semester': stored.get('semester'),
                        'status': stored.get('status'),
                    }
                    result_items.append(result_item)
                
                return {
                    'success': True,
                    'results': result_items,
                    'total_count': len(result_items),
                    'warning': f'Using stored results. API error: {str(e)}',
                    'new_results_saved': 0
                }
            except Exception as db_error:
                return {
                    'success': False,
                    'error': f'Error: {str(e)}. Database error: {str(db_error)}',
                    'results': []
                }
    
    async def _fetch_notifications(self, endpoint: str, cookies: Dict) -> Optional[List[Dict]]:
        """
        Fetch notifications from a specific endpoint
        Returns list of notifications or None if failed
        """
        try:
            def fetch():
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "application/json, text/html, */*",
                    "Referer": f"{self.BASE_URL}/Home",
                }
                response = requests.get(
                    endpoint,
                    cookies=cookies,
                    headers=headers,
                    timeout=self.REQUEST_TIMEOUT
                )
                return response
            
            response = await asyncio.to_thread(fetch)
            
            if response.status_code != 200:
                return None
            
            # Try to parse as JSON first
            try:
                data = response.json()
                # Handle different response formats
                if isinstance(data, list):
                    return self._normalize_notifications(data)
                elif isinstance(data, dict):
                    # Check common keys
                    for key in ['data', 'notifications', 'items', 'results']:
                        if key in data and isinstance(data[key], list):
                            return self._normalize_notifications(data[key])
                    return []
                else:
                    return []
            except ValueError:
                # Response is HTML, parse it
                return self._parse_html_notifications(response.text)
        
        except Exception as e:
            print(f"Error fetching from {endpoint}: {str(e)}")
            return None
    
    def _normalize_notifications(self, notifications: List) -> List[Dict]:
        """
        Normalize notification format from API
        Handles different JSON structures
        College format uses 'title' field for main notification text
        """
        normalized = []
        
        print(f"DEBUG: Normalizing {len(notifications)} notifications")
        
        for idx, item in enumerate(notifications):
            if isinstance(item, dict):
                # Print raw item for debugging
                print(f"DEBUG: Raw notification {idx}: {item}")
                
                # Try to extract common fields
                title = item.get('title') or item.get('Title') or item.get('subject') or item.get('Subject') or ''
                description = item.get('description') or item.get('Description') or item.get('body') or item.get('Body') or item.get('text') or item.get('content') or ''
                
                # Use title for display, but pass description separately for parsing
                notification = {
                    'id': item.get('id') or item.get('notificationId') or item.get('_id') or item.get('ID') or str(idx),
                    'text': title,  # Use title for identification
                    'description': description,  # Full description for parsing
                    'date': item.get('sendDate') or item.get('sentDate') or item.get('date') or item.get('createdAt') or item.get('Date') or '',
                    'title': title,
                }
                
                if notification['text']:  # Only add if there's actual content
                    print(f"DEBUG: Normalized notification {idx}: text='{notification['text'][:80]}...', date={notification['date']}")
                    normalized.append(notification)
                else:
                    print(f"DEBUG: Skipping notification {idx} - no text content")
            elif isinstance(item, str):
                # Simple string notification
                normalized.append({
                    'id': str(hash(item)),
                    'text': item,
                    'date': '',
                    'title': ''
                })
        
        print(f"DEBUG: Normalized to {len(normalized)} notifications with content")
        return normalized
    
    def _parse_html_notifications(self, html: str) -> List[Dict]:
        """
        Parse notifications from HTML response
        Handles various HTML structures
        """
        notifications = []
        
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # Try common notification container patterns
            notification_containers = (
                soup.find_all('div', class_=re.compile(r'notification', re.I)) or
                soup.find_all('li', class_=re.compile(r'notification', re.I)) or
                soup.find_all('tr', class_=re.compile(r'notification', re.I))
            )
            
            for container in notification_containers:
                text = container.get_text(strip=True)
                
                # Try to extract date
                date_element = container.find(class_=re.compile(r'date|time', re.I))
                date = date_element.get_text(strip=True) if date_element else ''
                
                # Try to extract ID
                notification_id = container.get('data-id') or container.get('id', '')
                
                if text:
                    notifications.append({
                        'id': notification_id or str(hash(text)),
                        'text': text,
                        'date': date,
                        'title': ''
                    })
            
            # If no notifications found with specific classes, try table rows
            if not notifications:
                table = soup.find('table')
                if table:
                    rows = table.find_all('tr')[1:]  # Skip header
                    for i, row in enumerate(rows):
                        cells = row.find_all('td')
                        if cells:
                            text = ' '.join(cell.get_text(strip=True) for cell in cells)
                            if text:
                                notifications.append({
                                    'id': str(i),
                                    'text': text,
                                    'date': cells[0].get_text(strip=True) if cells else '',
                                    'title': ''
                                })
        
        except Exception as e:
            print(f"Error parsing HTML notifications: {str(e)}")
        
        return notifications


# Global instance (similar to attendance_service)
results_service = ResultsService()
