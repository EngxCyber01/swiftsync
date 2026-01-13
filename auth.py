import os
import logging
from dataclasses import dataclass
from typing import Optional

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


@dataclass
class AuthConfig:
    """Configuration needed to authenticate against the IdentityServer4 instance."""

    login_url: str = "https://tempids-su.awrosoft.com/account/login"
    oidc_callback_url: str = "https://tempapp-su.awrosoft.com/erp-web-signin-oidc"
    username: str = os.getenv("PORTAL_USERNAME", "")
    password: str = os.getenv("PORTAL_PASSWORD", "")
    verify_ssl: bool = True


class AuthError(Exception):
    pass


class AuthClient:
    def __init__(self, config: Optional[AuthConfig] = None) -> None:
        self.config = config or AuthConfig()
        self.session: Optional[requests.Session] = None

    def _extract_request_verification_token(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        token_tag = soup.find("input", attrs={"name": "__RequestVerificationToken"})
        if not token_tag or not token_tag.get("value"):
            raise AuthError("Could not locate __RequestVerificationToken on the login page.")
        return token_tag["value"]

    def _extract_oidc_form_data(self, html: str) -> dict:
        """
        Extract hidden form fields from the OIDC redirect page (response_mode=form_post).
        This typically includes 'code', 'state', 'session_state', etc.
        """
        soup = BeautifulSoup(html, "html.parser")
        form = soup.find("form")
        if not form:
            raise AuthError("No OIDC callback form found in response.")

        form_data = {}
        for input_tag in form.find_all("input", attrs={"type": "hidden"}):
            name = input_tag.get("name")
            value = input_tag.get("value", "")
            if name:
                form_data[name] = value

        if not form_data:
            raise AuthError("OIDC form is empty. Cannot proceed with authentication.")
        return form_data

    def _is_authenticated(self, session: requests.Session) -> bool:
        # Check for any auth cookies from either domain
        has_identity_cookie = any(cookie.name in (".AspNetCore.Cookies", ".AspNetCore.Identity.Application") 
                                   for cookie in session.cookies)
        has_app_cookie = any("AspNetCore" in cookie.name and "tempapp-su.awrosoft.com" in cookie.domain 
                              for cookie in session.cookies)
        return has_identity_cookie or has_app_cookie or len(session.cookies) > 0

    def login(self) -> requests.Session:
        if not self.config.username or not self.config.password:
            raise AuthError("Missing credentials. Set PORTAL_USERNAME and PORTAL_PASSWORD in .env file.")

        session = requests.Session()
        session.verify = self.config.verify_ssl
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })

        # Step 1: Trigger OIDC flow from the app login page
        app_login_url = "https://tempapp-su.awrosoft.com/Account/Login"
        response = session.get(app_login_url, allow_redirects=True)
        
        # This should redirect to IdentityServer login with returnUrl
        if "tempids-su.awrosoft.com" not in response.url:
            raise AuthError("OIDC redirect did not happen. Check if app URL is correct.")

        # Step 2: Extract token from the current page
        token = self._extract_request_verification_token(response.text)

        # Step 3: POST credentials
        payload = {
            "Username": self.config.username,
            "Password": self.config.password,
            "RememberLogin": "false",  # The hidden field value
            "__RequestVerificationToken": token,
            "button": "login",  # The button value
        }

        auth_response = session.post(
            response.url,  # POST to the current URL (login with returnUrl)
            data=payload,
            allow_redirects=True,
        )

        # Step 4: Check if response contains OIDC form_post form
        if "text/html" in auth_response.headers.get("Content-Type", ""):
            try:
                form_data = self._extract_oidc_form_data(auth_response.text)
                if form_data:
                    logger.info("OIDC form fields: %s", list(form_data.keys()))
                    
                    # Check for authentication error
                    if 'error' in form_data:
                        error_desc = form_data.get('error_description', form_data['error'])
                        raise AuthError(f"OIDC authentication failed: {error_desc}")
                    
                    logger.info("Posting OIDC callback form to %s", self.config.oidc_callback_url)
                    # POST the OIDC callback form
                    callback_response = session.post(
                        self.config.oidc_callback_url,
                        data=form_data,
                        allow_redirects=True,
                    )
                    logger.info("Callback POST status: %d", callback_response.status_code)
                    logger.info("Callback completed. Final URL: %s, Status: %d", 
                               callback_response.url, callback_response.status_code)
                    logger.info("Cookies after callback: %d", len(session.cookies))
                    for cookie in session.cookies:
                        logger.info("  Cookie: %s = %s (domain=%s)", cookie.name, cookie.value[:20], cookie.domain)
            except AuthError as e:
                logger.warning("No OIDC form found: %s", e)
                raise  # Re-raise auth errors

        # Step 5: Check if we got the session cookie
        if not self._is_authenticated(session):
            raise AuthError(
                "Authentication failed. Check credentials (Username/Password in .env) "
                "or verify the OIDC flow is correct."
            )

        self.session = session
        return session

    def get_authenticated_session(self) -> requests.Session:
        if self.session and self._is_authenticated(self.session):
            return self.session
        return self.login()
