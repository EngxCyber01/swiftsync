"""
Attendance Module for SwiftSync
Handles secure authentication and attendance data retrieval
Uses in-memory session cache for performance
"""

import asyncio
import time
import secrets
import requests
from bs4 import BeautifulSoup
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import pytz
from auth import AuthClient, AuthConfig
from student_info import get_student_info

class SessionManager:
    """Fast in-memory session management with TTL"""
    
    def __init__(self, session_ttl_minutes: int = 30):
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.session_ttl = timedelta(minutes=session_ttl_minutes)
        
    def create_session(self, student_id: str, cookies: Dict, username: str) -> str:
        """Create a new session and return session token"""
        session_token = secrets.token_urlsafe(32)
        iraq_tz = pytz.timezone('Asia/Baghdad')
        self.sessions[session_token] = {
            'student_id': student_id,
            'cookies': cookies,
            'username': username,
            'created_at': datetime.now(iraq_tz),
            'last_accessed': datetime.now(iraq_tz)
        }
        return session_token
    
    def get_session(self, session_token: str) -> Optional[Dict[str, Any]]:
        """Get session data if valid, None if expired or not found"""
        if session_token not in self.sessions:
            return None
        
        session = self.sessions[session_token]
        iraq_tz = pytz.timezone('Asia/Baghdad')
        
        # Check if expired
        if datetime.now(iraq_tz) - session['created_at'] > self.session_ttl:
            del self.sessions[session_token]
            return None
        
        # Update last accessed
        session['last_accessed'] = datetime.now(iraq_tz)
        return session
    
    def delete_session(self, session_token: str) -> bool:
        """Delete a session"""
        if session_token in self.sessions:
            del self.sessions[session_token]
            return True
        return False
    
    def cleanup_expired_sessions(self):
        """Remove expired sessions (called periodically)"""
        iraq_tz = pytz.timezone('Asia/Baghdad')
        now = datetime.now(iraq_tz)
        expired_tokens = [
            token for token, session in self.sessions.items()
            if now - session['created_at'] > self.session_ttl
        ]
        for token in expired_tokens:
            del self.sessions[token]


class AttendanceService:
    """High-performance attendance data retrieval"""
    
    BASE_URL = "https://tempapp-su.awrosoft.com"
    ATTENDANCE_ENDPOINT = f"{BASE_URL}/University/ClassAttendance/GetAbsencesList"
    PROFILE_ENDPOINT = f"{BASE_URL}/Portal/GetCurrentStudentInfo"
    DETAILS_ENDPOINT = f"{BASE_URL}/University/ClassAttendance/GetStudentAbsenceDetails"
    REQUEST_TIMEOUT = 15  # seconds
    
    def __init__(self):
        self.session_manager = SessionManager(session_ttl_minutes=30)
    
    async def authenticate_user(self, username: str, password: str) -> Dict[str, Any]:
        """
        Authenticate user and create session
        Returns: {success: bool, session_token: str, error: str, student_id: str}
        """
        try:
            # Validate inputs
            if not username or not password:
                return {
                    'success': False,
                    'error': 'Username and password are required'
                }
            
            # Create a new auth client for this user
            auth_config = AuthConfig()
            auth_config.username = username
            auth_config.password = password
            auth_client = AuthClient(auth_config)
            
            # Authenticate using existing auth.py
            try:
                result = await asyncio.to_thread(auth_client.login)
            except ValueError as ve:
                # Catch credential validation errors
                return {
                    'success': False,
                    'error': 'Portal credentials not configured. Please contact administrator.'
                }
            except Exception as auth_exc:
                # Catch authentication failures
                error_msg = str(auth_exc)
                if 'credentials' in error_msg.lower() or 'username' in error_msg.lower():
                    return {
                        'success': False,
                        'error': 'Invalid credentials. Please check your username and password.'
                    }
                return {
                    'success': False,
                    'error': f'Authentication failed: {error_msg}'
                }
            
            if not auth_client.session:
                return {
                    'success': False,
                    'error': 'Authentication failed. Please check your credentials.'
                }
            
            # Extract student ID and cookies
            student_id = username  # Student ID is the username
            cookies = dict(auth_client.session.cookies)
            
            # Create session token
            session_token = self.session_manager.create_session(
                student_id=student_id,
                cookies=cookies,
                username=username
            )
            
            return {
                'success': True,
                'session_token': session_token,
                'student_id': student_id,
                'username': username
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': f'Login error: {str(e)}'
            }
    
    async def get_student_profile(self, session_token: str) -> Dict[str, Any]:
        """
        Get student profile from portal API
        Returns: {success: bool, first_name: str, middle_name: str, last_name: str}
        """
        session = self.session_manager.get_session(session_token)
        if not session:
            return {'success': False, 'error': 'Session expired'}
        
        student_id = session['student_id']
        cookies = session['cookies']
        
        try:
            # Fetch from REAL portal endpoint
            def fetch_profile():
                url = f"{self.BASE_URL}/University/Student/GetCurrentStudentInfo"
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                }
                response = requests.get(
                    url,
                    cookies=cookies,
                    headers=headers,
                    timeout=self.REQUEST_TIMEOUT
                )
                return response
            
            response = await asyncio.to_thread(fetch_profile)
            
            if response.status_code == 200:
                # Parse HTML to extract student name
                soup = BeautifulSoup(response.text, 'html.parser')
                table = soup.find('table')
                
                if table:
                    rows = table.find_all('tr')
                    if len(rows) > 0:
                        # First row contains full name
                        first_cell = rows[0].find('td')
                        if first_cell:
                            full_name = first_cell.get_text(strip=True)
                            
                            # Split name into parts
                            name_parts = full_name.split()
                            
                            if len(name_parts) >= 3:
                                return {
                                    'success': True,
                                    'first_name': name_parts[0],
                                    'middle_name': ' '.join(name_parts[1:-1]),
                                    'last_name': name_parts[-1]
                                }
                            elif len(name_parts) == 2:
                                return {
                                    'success': True,
                                    'first_name': name_parts[0],
                                    'middle_name': '',
                                    'last_name': name_parts[1]
                                }
                            elif len(name_parts) == 1:
                                return {
                                    'success': True,
                                    'first_name': name_parts[0],
                                    'middle_name': '',
                                    'last_name': ''
                                }
            
            # Fallback to local mapping if API fails
            info = get_student_info(student_id)
            return {
                'success': True,
                'first_name': info.get('first_name', ''),
                'middle_name': info.get('middle_name', ''),
                'last_name': info.get('last_name', '')
            }
            
        except Exception as e:
            # Fallback to local mapping on error
            info = get_student_info(student_id)
            return {
                'success': True,
                'first_name': info.get('first_name', ''),
                'middle_name': info.get('middle_name', ''),
                'last_name': info.get('last_name', '')
            }
    
    async def get_absence_details(self, session_token: str, student_class_id: str, class_id: str) -> Dict[str, Any]:
        """
        Fetch absence details (dates/times) for specific module
        Returns: {success: bool, details: List[str]}
        """
        session = self.session_manager.get_session(session_token)
        if not session:
            return {'success': False, 'error': 'Session expired'}
        
        cookies = session['cookies']
        
        try:
            def fetch_details():
                # API endpoint only requires studentClassId parameter
                url = f"{self.DETAILS_ENDPOINT}?studentClassId={student_class_id}"
                print(f"Fetching absence details from: {url}")
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Referer": f"{self.BASE_URL}/University/ClassAttendance/GetAbsencesList",
                }
                response = requests.get(url, cookies=cookies, headers=headers, timeout=self.REQUEST_TIMEOUT)
                print(f"Absence details response status: {response.status_code}")
                print(f"Response content length: {len(response.text)}")
                return response
            
            response = await asyncio.to_thread(fetch_details)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                details = []
                
                # Find the table with absence details
                table = soup.find('table')
                if table:
                    rows = table.find_all('tr')[1:]  # Skip header
                    print(f"Found {len(rows)} absence detail rows")
                    for row in rows:
                        cells = row.find_all('td')
                        if len(cells) >= 2:
                            date = cells[0].get_text(strip=True)
                            time = cells[1].get_text(strip=True)
                            if date and time:
                                details.append(f"{date} at {time}")
                                print(f"Parsed absence: {date} at {time}")
                else:
                    print("No table found in absence details response")
                
                return {'success': True, 'details': details}
            else:
                print(f"Error fetching absence details: Status {response.status_code}")
                return {'success': False, 'error': f'Status {response.status_code}'}
        
        except Exception as e:
            print(f"Exception fetching absence details: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    async def get_attendance(self, session_token: str) -> Dict[str, Any]:
        """
        Fetch attendance data using cached session
        Returns: {success: bool, html: str, error: str}
        """
        # Validate session
        session = self.session_manager.get_session(session_token)
        if not session:
            return {
                'success': False,
                'error': 'Session expired or invalid. Please login again.'
            }
        
        student_id = session['student_id']
        cookies = session['cookies']
        
        try:
            # Fast async HTTP request using requests library with asyncio.to_thread
            def fetch_attendance():
                url = f"{self.ATTENDANCE_ENDPOINT}?studentId={student_id}"
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Referer": f"{self.BASE_URL}/Home",
                }
                response = requests.get(
                    url,
                    cookies=cookies,
                    headers=headers,
                    timeout=self.REQUEST_TIMEOUT
                )
                return response
            
            response = await asyncio.to_thread(fetch_attendance)
            
            if response.status_code == 200:
                html_content = response.text
                
                # Try to extract student name from HTML
                student_name = None
                try:
                    soup = BeautifulSoup(html_content, 'html.parser')
                    
                    # Look for common patterns where student name might appear
                    # Pattern 1: Look for labels or divs containing "Student Name", "Name", etc.
                    name_patterns = [
                        'student name', 'student:', 'name:', 'الطالب:', 'اسم الطالب:',
                        'full name', 'اسم'
                    ]
                    
                    for pattern in name_patterns:
                        # Search in all text content
                        for element in soup.find_all(['label', 'span', 'div', 'td', 'th', 'p']):
                            text = element.get_text(strip=True).lower()
                            if pattern in text:
                                # Try to get the value from next sibling or same element
                                next_elem = element.find_next_sibling()
                                if next_elem:
                                    potential_name = next_elem.get_text(strip=True)
                                    if potential_name and len(potential_name) > 3 and not potential_name.startswith('B'):
                                        student_name = potential_name
                                        break
                                # Or check if the name is in the same element after the pattern
                                elif ':' in element.get_text():
                                    parts = element.get_text().split(':', 1)
                                    if len(parts) > 1:
                                        potential_name = parts[1].strip()
                                        if potential_name and len(potential_name) > 3:
                                            student_name = potential_name
                                            break
                        if student_name:
                            break
                    
                    # Pattern 2: Look in page title or header
                    if not student_name:
                        title = soup.find('title')
                        if title:
                            title_text = title.get_text()
                            # Extract name if format is like "Attendance - Student Name"
                            if '-' in title_text:
                                parts = title_text.split('-')
                                for part in parts:
                                    part = part.strip()
                                    if len(part) > 3 and not part.lower() in ['attendance', 'portal', 'home']:
                                        student_name = part
                                        break
                    
                except Exception as e:
                    # If parsing fails, just continue without name
                    pass
                
                return {
                    'success': True,
                    'html': html_content,
                    'student_id': student_id,
                    'username': session['username'],
                    'extracted_name': student_name
                }
            elif response.status_code == 401:
                # Session expired on server side
                self.session_manager.delete_session(session_token)
                return {
                    'success': False,
                    'error': 'Session expired. Please login again.'
                }
            elif response.status_code == 403:
                return {
                    'success': False,
                    'error': 'Access forbidden. Session may not be fully established. Please try again.'
                }
            else:
                return {
                    'success': False,
                    'error': f'Server returned status {response.status_code}'
                }
                        
        except requests.Timeout:
            return {
                'success': False,
                'error': 'Request timed out. Please try again.'
            }
        except Exception as e:
            return {
                'success': False,
                'error': f'Error fetching attendance: {str(e)}'
            }
    
    def logout(self, session_token: str) -> bool:
        """Logout user by deleting session"""
        return self.session_manager.delete_session(session_token)
    
    def cleanup_sessions(self):
        """Cleanup expired sessions"""
        self.session_manager.cleanup_expired_sessions()


# Global instance
attendance_service = AttendanceService()
