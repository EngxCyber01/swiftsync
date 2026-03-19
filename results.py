"""
Results Module for SwiftSync
Handles fetching and parsing result-related notifications from the real college system
Uses notification API as the source for student results
Saves results to database for persistence
"""

import asyncio
import os
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
    TARGET_ACADEMIC_YEAR_FULL = os.getenv("RESULTS_ACADEMIC_YEAR_FULL", "2025-2026")
    TARGET_ACADEMIC_YEAR_SHORT = os.getenv("RESULTS_ACADEMIC_YEAR_SHORT", "25-26")
    
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

    def _normalize_result_key(self, item: Dict[str, Any]) -> str:
        """Build a stable key used to collapse duplicate rows returned to the UI."""
        semester_display = str(item.get('semester_display', '') or '').strip().lower()
        subject = str(item.get('subject', '') or '').strip().lower()
        exam_type = str(item.get('exam_type', '') or '').strip().lower()
        score = str(item.get('score', '') or '').strip().lower()
        # Date can come as ISO or display-like string; keep date-part only to avoid time-zone duplicates.
        date_raw = str(item.get('date', '') or '').strip()
        date_norm = date_raw[:10] if len(date_raw) >= 10 else date_raw
        return f"{semester_display}|{subject}|{exam_type}|{score}|{date_norm}"

    def _dedupe_result_items(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove repeated rows while preserving first occurrence order."""
        seen = set()
        deduped = []
        for item in items:
            key = self._normalize_result_key(item)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def _belongs_to_target_year(self, semester: str, raw_text: str) -> bool:
        """Keep only notifications tied to the configured academic year."""
        combined = f"{semester or ''} {raw_text or ''}".lower()
        return (
            self.TARGET_ACADEMIC_YEAR_FULL.lower() in combined
            or self.TARGET_ACADEMIC_YEAR_SHORT.lower() in combined
        )

    def _to_semester_display(self, semester: str, raw_text: str) -> Optional[str]:
        """Map raw semester codes/text to a canonical display label."""
        combined = f"{semester or ''} {raw_text or ''}".lower()

        # Support portal codes like Software_F_25-26, Software_F25-26, Software_S_25-26, Software_S25-26
        is_fall = bool(re.search(r'(?:[_\-]f[_\-]?\d{2}-\d{2}|\bfall\b|\b1st\s+semester\b|\bfirst\s+semester\b)', combined))
        is_spring = bool(re.search(r'(?:[_\-]s[_\-]?\d{2}-\d{2}|\bspring\b|\b2nd\s+semester\b|\bsecond\s+semester\b)', combined))

        if is_fall:
            return f"{self.TARGET_ACADEMIC_YEAR_FULL} Fall Semester"
        if is_spring:
            return f"{self.TARGET_ACADEMIC_YEAR_FULL} Spring Semester"
        return None

    def _student_notification_id(self, student_id: str, notification_id: str) -> str:
        """Namespace notification ID per student to avoid cross-student collisions."""
        sid = (student_id or "").strip()
        nid = (notification_id or "").strip()
        return f"{sid}:{nid}" if sid and nid else nid
    
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
        
        # Extract semester/class info from portal patterns such as:
        # Software_S_25-26, Software_F_25-26, Software_S25-26, Software-F25-26
        semester_pattern = r'([A-Za-z]+)[_\-]([FS])[_\-]?(\d{2}-\d{2})'
        sem_match = re.search(semester_pattern, parse_text, re.IGNORECASE)
        if sem_match:
            result['semester'] = f"{sem_match.group(1)}_{sem_match.group(2).upper()}_{sem_match.group(3)}"
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
    
    async def _fetch_official_results_html(self, student_id: str, cookies: Dict) -> Optional[str]:
        """Fetch official results HTML page"""
        try:
            endpoint = f"{self.BASE_URL}/University/StudentResult/List?studentId={student_id}"
            def fetch():
                response = requests.get(
                    endpoint,
                    cookies=cookies,
                    timeout=self.REQUEST_TIMEOUT,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "Accept": "application/json, text/html, */*",
                        "Referer": f"{self.BASE_URL}/Home",
                    }
                )
                return response
            
            response = await asyncio.to_thread(fetch)
            if response.status_code == 200:
                return response.text
            return None
        except Exception as e:
            print(f"DEBUG: Error fetching official results: {e}")
            return None
    
    def _parse_official_results_html(self, html: str, student_id: str) -> List[Dict]:
        """
        Parse official results from HTML page
        Extracts Fall/Spring results that may not be in Notifications API
        """
        results = []
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # Look for result cards/items in the HTML
            # Typical structure: headers with semester info, then rows with results
            cards = soup.find_all('div', {'class': ['card', 'result-card', 'semester-card']})
            if not cards:
                # Alternative: look for tables
                tables = soup.find_all('table')
                if tables:
                    for table in tables:
                        rows = table.find_all('tr')
                        for row in rows[1:]:  # Skip header
                            cols = row.find_all('td')
                            if len(cols) >= 4:
                                subject = cols[0].text.strip()
                                exam_type = cols[1].text.strip() if len(cols) > 1 else ''
                                score = cols[2].text.strip() if len(cols) > 2 else ''
                                semester = cols[3].text.strip() if len(cols) > 3 else ''
                                
                                if subject and score:
                                    try:
                                        score_val = float(score.split('/')[0]) if score and '/' in score else float(score) if score else 0
                                    except:
                                        score_val = 0
                                    
                                    result_item = {
                                        'subject': subject,
                                        'exam_type': exam_type,
                                        'score': score,
                                        'semester': semester,
                                        'grade': '',
                                        'status': 'passed' if score_val >= 50 else 'failed'
                                    }
                                    results.append(result_item)
            
            return results
        except Exception as e:
            print(f"DEBUG: Error parsing official results HTML: {e}")
            return []
    
    async def _save_official_results(self, html: str, student_id: str, cookies: Dict) -> int:
        """
        Parse official results HTML and save to database if not already cached
        Returns count of newly saved results
        """
        saved_count = 0
        try:
            # Parse HTML (this is custom logic since HTML structure may vary)
            # For now, we'll extract any result text we can find
            soup = BeautifulSoup(html, 'html.parser')
            
            # Extract all text content and look for result patterns
            text_content = soup.get_text()
            
            # Look for Fall semester section
            fall_match = re.search(r'(Fall.*?Semester|result.*?25-26.*?Fall)', text_content, re.IGNORECASE | re.DOTALL)
            if fall_match:
                print(f"DEBUG: Found Fall semester section in official results")
                # Try to extract individual results
                result_pattern = r'([A-Za-z\s]+)\s+[-–]\s+([\d.]+)\s*(?:/10)?'
                matches = re.findall(result_pattern, fall_match.group(1))
                for subject, score in matches:
                    subject = subject.strip()
                    if subject and subject not in ['Fall Semester', 'Result', '2025-2026']:
                        notif_id = f"official_fall_{student_id}_{subject}_{score}"
                        scoped_id = self._student_notification_id(student_id, notif_id)
                        
                        if not result_exists(scoped_id, student_id):
                            parsed = {
                                'subject': subject,
                                'exam_type': 'Final',
                                'score': score,
                                'grade': '',
                                'semester': 'Software_F_25-26',
                                'raw_text': f'Your result of {subject} - Software_F_25-26 class is {score}',
                                'status': 'passed',
                                'exam_date': datetime.now().isoformat()
                            }
                            if save_result(student_id, scoped_id, parsed):
                                saved_count += 1
                                print(f"DEBUG: Saved official Fall result: {subject}")
            
            return saved_count
        except Exception as e:
            print(f"DEBUG: Error saving official results: {e}")
            return 0
    
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
            # First, get total page count from dedicated endpoint.
            pages_count_endpoint = f"{self.BASE_URL}/Notification/GetPagesCount"
            print(f"DEBUG: Fetching page count from: {pages_count_endpoint}")
            
            try:
                def fetch_page_count():
                    response = requests.get(
                        pages_count_endpoint,
                        cookies=cookies,
                        timeout=self.REQUEST_TIMEOUT,
                        headers={
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                            "Accept": "application/json, text/html, */*",
                        }
                    )
                    return response
                
                page_count_response = await asyncio.to_thread(fetch_page_count)
                total_pages = 1
                
                if page_count_response.status_code == 200:
                    try:
                        count_data = page_count_response.json()
                        if isinstance(count_data, dict):
                            total_pages = int(
                                count_data.get(
                                    'pageCount',
                                    count_data.get('totalPages', count_data.get('pages', count_data.get('count', 1)))
                                )
                            )
                        else:
                            total_pages = int(count_data)
                        if total_pages < 1:
                            total_pages = 1
                        print(f"DEBUG: Total pages from GetPagesCount: {total_pages}")
                    except:
                        print(f"DEBUG: Could not parse page count, using default 1")
            except Exception as e:
                total_pages = 1
                print(f"DEBUG: Could not fetch page count: {e}, using default 1")
            
            # Now fetch ALL pages of notifications with pagination
            all_notifications = []
            page_number = 1
            page_size = 50
            
            while page_number <= total_pages:
                # Add pagination parameters to endpoint
                paginated_endpoint = f"{self.NOTIFICATIONS_ENDPOINT}?PageNumber={page_number}&PageSize={page_size}"
                print(f"DEBUG: Fetching page {page_number}/{total_pages} from: {paginated_endpoint}")
                
                notifications = await self._fetch_notifications(paginated_endpoint, cookies)
                
                # If no notifications returned, we've reached the end
                if not notifications or len(notifications) == 0:
                    print(f"DEBUG: No more notifications on page {page_number}, stopping pagination")
                    break
                
                print(f"DEBUG: Page {page_number} returned {len(notifications)} notifications")
                
                # Log first few notification texts to see what we're getting
                for idx, notif in enumerate(notifications[:3]):
                    text = notif.get('text', '')
                    desc = notif.get('description', '')
                    print(f"  Notification {idx+1}: text='{text[:60]}...' desc='{desc[:60]}...'")
                
                all_notifications.extend(notifications)
                
                page_number += 1
            
            fetched_pages = page_number - 1 if page_number > 1 else 1
            print(f"DEBUG: Total notifications fetched across {fetched_pages} pages: {len(all_notifications)}")
            print(f"DEBUG: Analyzing notifications for result keywords...")

            
            # Process all fetched notifications
            if all_notifications:
                print(f"DEBUG: Processing {len(all_notifications)} notifications")
                result_count = 0
                non_result_count = 0
                
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
                        result_count += 1
                        print(f"  ✓ IS result-related (keyword match)")
                        
                        # Check if already saved for THIS student (avoid duplicates per student)
                        scoped_notification_id = self._student_notification_id(student_id, notification_id)
                        if not result_exists(scoped_notification_id, student_id):
                            print(f"  → New for student {student_id}, parsing and saving...")
                            # Parse the notification using description field
                            parsed = self._parse_notification_text(text, description)
                            parsed['raw_text'] = check_text
                            parsed['exam_date'] = date
                            
                            # Detect semester
                            is_fall = bool(re.search(r'(?:[_\-]f[_\-]?\d{2}-\d{2}|\bfall\b|\b1st\s+semester\b|\bfirst\s+semester\b)', check_text.lower()))
                            is_spring = bool(re.search(r'(?:[_\-]s[_\-]?\d{2}-\d{2}|\bspring\b|\b2nd\s+semester\b|\bsecond\s+semester\b)', check_text.lower()))
                            sem_label = 'FALL' if is_fall else ('SPRING' if is_spring else 'UNKNOWN')
                            print(f"    Semester detected: {sem_label}")

                            # Save all result notifications; year/semester filtering is applied at read time.
                            if save_result(student_id, scoped_notification_id, parsed):
                                new_results_saved += 1
                                print(f"  ✓ Saved result {new_results_saved}: {parsed.get('subject', 'Unknown')} - {parsed.get('exam_type', 'Unknown')} [{sem_label}]")
                            else:
                                print(f"  ✗ Failed to save notification {notification_id}")
                        else:
                            print(f"  → Already exists for student {student_id}")
                    else:
                        non_result_count += 1
                        print(f"  ✗ NOT result-related (no keyword match)")
                
                print(f"DEBUG: Processed summary: {result_count} result-related, {non_result_count} non-result")
            else:
                print(f"DEBUG: No notifications received from API")
            
            # Fetch results from database (this is our persistent source)
            print(f"DEBUG: Fetching stored results for student {student_id}")
            stored_results = get_student_results(student_id, limit=500)
            print(f"DEBUG: Found {len(stored_results)} stored results in database")
            
            # Format results for frontend
            result_items = []
            for stored in stored_results:
                raw_text = stored.get('raw_text', '')
                semester_raw = stored.get('semester', '')

                # Data-safety guard: only return current academic year for the authenticated student
                if not self._belongs_to_target_year(semester_raw, raw_text):
                    continue

                semester_display = self._to_semester_display(semester_raw, raw_text)
                if not semester_display:
                    continue

                result_item = {
                    'id': str(stored.get('notification_id', '')).split(':', 1)[-1],
                    'date': stored.get('exam_date', stored.get('created_at', '')),
                    'raw_text': raw_text,
                    'subject': stored.get('subject'),
                    'exam_type': stored.get('exam_type'),
                    'score': stored.get('score'),
                    'grade': stored.get('grade'),
                    'semester': semester_raw,
                    'semester_display': semester_display,
                    'status': stored.get('status'),
                }
                result_items.append(result_item)
            
            deduped_items = self._dedupe_result_items(result_items)
            return {
                'success': True,
                'results': deduped_items,
                'total_count': len(deduped_items),
                'new_results_saved': new_results_saved
            }
        
        except Exception as e:
            # If API fetch fails, still try to return stored results
            try:
                stored_results = get_student_results(student_id, limit=500)
                result_items = []
                for stored in stored_results:
                    raw_text = stored.get('raw_text', '')
                    semester_raw = stored.get('semester', '')

                    if not self._belongs_to_target_year(semester_raw, raw_text):
                        continue

                    semester_display = self._to_semester_display(semester_raw, raw_text)
                    if not semester_display:
                        continue

                    result_item = {
                        'id': str(stored.get('notification_id', '')).split(':', 1)[-1],
                        'date': stored.get('exam_date', stored.get('created_at', '')),
                        'raw_text': raw_text,
                        'subject': stored.get('subject'),
                        'exam_type': stored.get('exam_type'),
                        'score': stored.get('score'),
                        'grade': stored.get('grade'),
                        'semester': semester_raw,
                        'semester_display': semester_display,
                        'status': stored.get('status'),
                    }
                    result_items.append(result_item)
                
                deduped_items = self._dedupe_result_items(result_items)
                return {
                    'success': True,
                    'results': deduped_items,
                    'total_count': len(deduped_items),
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
