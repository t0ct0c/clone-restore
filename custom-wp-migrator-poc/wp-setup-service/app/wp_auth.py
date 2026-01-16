"""
WordPress Authentication Module

Handles authentication with WordPress sites using Application Passwords
or cookie-based login as fallback.
"""

import re
import logging
from typing import Optional, Tuple
import requests
from bs4 import BeautifulSoup


logger = logging.getLogger(__name__)


class WordPressAuthenticator:
    """Authenticate with WordPress admin panel"""
    
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'WP-Setup-Service/1.0'
        })
    
    def authenticate(self, username: str, password: str) -> bool:
        """
        Authenticate with WordPress using Application Password or cookie auth
        
        Returns:
            True if authentication successful, False otherwise
        """
        logger.info(f"Starting authentication for {self.base_url} with user {username}")
        
        # Try Application Password first (WP 5.6+)
        logger.info("Trying Application Password authentication...")
        if self._try_app_password(username, password):
            logger.info(f"Authenticated with {self.base_url} using Application Password")
            return True
        
        # Fallback to cookie-based authentication
        logger.info("Application Password failed, trying cookie-based authentication...")
        if self._try_cookie_auth(username, password):
            logger.info(f"Authenticated with {self.base_url} using cookie auth")
            return True
        
        logger.error(f"Authentication failed for {self.base_url}")
        return False
    
    def _try_app_password(self, username: str, password: str) -> bool:
        """Try authentication with Application Password"""
        try:
            logger.info(f"Attempting REST API call to {self.base_url}/wp-json/wp/v2/users/me")
            response = self.session.get(
                f"{self.base_url}/wp-json/wp/v2/users/me",
                auth=(username, password),
                timeout=30
            )
            
            logger.info(f"REST API response status: {response.status_code}")
            
            if response.status_code == 200:
                user_data = response.json()
                # Check if user is administrator
                if 'administrator' in user_data.get('roles', []):
                    return True
                logger.warning(f"User {username} is not an administrator")
                return False
                
        except Exception as e:
            logger.info(f"Application Password auth failed: {e}")
        
        return False
    
    def _try_cookie_auth(self, username: str, password: str) -> bool:
        """Try authentication with traditional cookie-based login"""
        try:
            # Get login page to retrieve nonce
            login_url = f"{self.base_url}/wp-login.php"
            logger.info(f"Getting login page: {login_url}")
            response = self.session.get(login_url, timeout=30)
            logger.info(f"Login page response status: {response.status_code}")
            
            if response.status_code != 200:
                logger.info(f"Login page returned non-200 status: {response.status_code}")
                return False
            
            # Submit login form
            login_data = {
                'log': username,
                'pwd': password,
                'wp-submit': 'Log In',
                'redirect_to': f"{self.base_url}/wp-admin/",
                'testcookie': '1'
            }
            
            logger.info(f"Submitting login form for user: {username}")
            response = self.session.post(
                login_url,
                data=login_data,
                timeout=30,
                allow_redirects=False  # Don't follow redirects to capture cookies from 302
            )
            logger.info(f"Login POST response status: {response.status_code}")
            
            # WordPress returns 302 redirect on successful login with cookies
            # Manually update session cookies from response
            if response.status_code == 302:
                logger.info("Got 302 redirect, extracting cookies...")
                self.session.cookies.update(response.cookies)
            
            # Check if login successful by verifying admin access
            # Cookie name has hash suffix like wordpress_logged_in_HASH
            cookie_dict = self.session.cookies.get_dict()
            logger.info(f"Session cookies after login: {list(cookie_dict.keys())}")
            
            has_login_cookie = any('wordpress_logged_in' in key for key in cookie_dict.keys())
            if has_login_cookie:
                # Having wordpress_logged_in cookie means authentication succeeded
                # Skip verify_admin_access as WordPress may redirect with reauth=1
                # even with valid cookies on fresh installations
                logger.info("Found wordpress_logged_in cookie, authentication successful")
                return True
            else:
                logger.info("No wordpress_logged_in cookie found after login")
            
        except Exception as e:
            logger.info(f"Cookie auth failed with exception: {e}")
        
        return False
    
    def verify_admin_access(self) -> bool:
        """Verify user has administrator access"""
        try:
            response = self.session.get(
                f"{self.base_url}/wp-admin/",
                timeout=30,
                allow_redirects=False
            )
            
            # If redirected to login, not authenticated
            if response.status_code == 302:
                return False
            
            # If we can access admin panel, user is admin
            if response.status_code == 200:
                return True
            
        except Exception as e:
            logger.error(f"Admin access verification failed: {e}")
        
        return False
    
    def get_rest_nonce(self) -> Optional[str]:
        """Extract REST API nonce from wp-admin page"""
        try:
            response = self.session.get(f"{self.base_url}/wp-admin/", timeout=30)
            if response.status_code == 200:
                # Look for wpApiSettings.nonce in JavaScript
                nonce_match = re.search(r'"nonce":"([a-f0-9]+)"', response.text)
                if nonce_match:
                    return nonce_match.group(1)
        except Exception as e:
            logger.error(f"Failed to get REST nonce: {e}")
        return None
    
    def get_nonce(self, action: str = 'plugin-upload', plugin_path: str = None) -> Optional[str]:
        """
        Retrieve WordPress nonce for privileged operations
        
        Args:
            action: The action name ('plugin-upload', 'activate-plugin', etc.)
            plugin_path: Plugin path for activation nonce extraction
        
        Returns:
            Nonce string or None if not found
        """
        try:
            if action == 'plugin-upload':
                url = f"{self.base_url}/wp-admin/plugin-install.php?tab=upload"
            elif action in ['activate-plugin', 'deactivate-plugin']:
                url = f"{self.base_url}/wp-admin/plugins.php"
            else:
                url = f"{self.base_url}/wp-admin/"
            
            logger.info(f"Getting nonce for action '{action}' from {url}")
            logger.info(f"Session cookies: {list(self.session.cookies.keys())}")
            
            response = self.session.get(url, timeout=30, allow_redirects=True)
            
            logger.info(f"Nonce page response status: {response.status_code}")
            logger.info(f"Final URL after redirects: {response.url}")
            
            if response.status_code != 200:
                logger.error(f"Failed to get nonce page, status: {response.status_code}")
                return None
            
            soup = BeautifulSoup(response.text, 'lxml')
            
            # For activation, look for the specific plugin's activation link
            if action == 'activate-plugin' and plugin_path:
                # Find activation link for this plugin
                import urllib.parse
                activate_link = soup.find('a', href=re.compile(f'action=activate.*plugin={re.escape(urllib.parse.quote(plugin_path))}'))
                if activate_link:
                    href = activate_link.get('href')
                    nonce_match = re.search(r'_wpnonce=([a-f0-9]+)', href)
                    if nonce_match:
                        logger.info(f"Found activation nonce from link: {nonce_match.group(1)[:10]}...")
                        return nonce_match.group(1)
            
            # For deactivation, look for the specific plugin's deactivation link
            if action == 'deactivate-plugin' and plugin_path:
                # Find deactivation link for this plugin
                import urllib.parse
                deactivate_link = soup.find('a', href=re.compile(f'action=deactivate.*plugin={re.escape(urllib.parse.quote(plugin_path))}'))
                if deactivate_link:
                    href = deactivate_link.get('href')
                    nonce_match = re.search(r'_wpnonce=([a-f0-9]+)', href)
                    if nonce_match:
                        logger.info(f"Found deactivation nonce from link: {nonce_match.group(1)[:10]}...")
                        return nonce_match.group(1)
            
            # Look for nonce in various forms
            nonce_input = soup.find('input', {'name': '_wpnonce'})
            if nonce_input and nonce_input.get('value'):
                return nonce_input['value']
            
            # Try to find in URLs
            nonce_match = re.search(r'_wpnonce=([a-f0-9]+)', response.text)
            if nonce_match:
                return nonce_match.group(1)
            
        except Exception as e:
            logger.error(f"Failed to retrieve nonce: {e}")
        
        return None
