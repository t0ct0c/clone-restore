"""
WordPress Options Management Module

Handles retrieving and setting WordPress options programmatically.
"""

import re
from loguru import logger
import time
from typing import Optional
from bs4 import BeautifulSoup
import requests





class WordPressOptionsFetcher:
    """Retrieve and manage WordPress options"""
    
    def __init__(self, session: requests.Session, base_url: str):
        self.session = session
        self.base_url = base_url.rstrip('/')
    
    def get_migrator_api_key(self, max_retries: int = 3, retry_delay: float = 2.0) -> Optional[str]:
        """
        Retrieve Custom WP Migrator API key with retry mechanism
        
        Args:
            max_retries: Maximum number of retry attempts
            retry_delay: Delay between retries in seconds
        
        Returns:
            API key string (32 chars) or None if not found
        """
        for attempt in range(max_retries + 1):
            try:
                if attempt > 0:
                    logger.info(f"Retrying API key retrieval (attempt {attempt + 1}/{max_retries + 1})...")
                    time.sleep(retry_delay)
                
                response = self.session.get(
                    f"{self.base_url}/wp-admin/options-general.php?page=custom-migrator-settings",
                    timeout=30
                )
                
                if response.status_code == 200:
                    # Look for API key input field
                    match = re.search(r'name="custom_migrator_api_key"\s+value="([a-zA-Z0-9]{32})"', response.text)
                    if match:
                        api_key = match.group(1)
                        logger.info(f"Retrieved API key via HTML scraping (attempt {attempt + 1})")
                        return api_key
                    
                    # Alternative: look in readonly field
                    soup = BeautifulSoup(response.text, 'lxml')
                    api_key_input = soup.find('input', {'name': 'custom_migrator_api_key'})
                    if api_key_input and api_key_input.get('value'):
                        api_key = api_key_input['value']
                        if len(api_key) == 32:
                            logger.info(f"Retrieved API key via BeautifulSoup (attempt {attempt + 1})")
                            return api_key
                    
                    if attempt < max_retries:
                        logger.warning(f"API key field found but value is empty or invalid (attempt {attempt + 1}), retrying...")
                    else:
                        logger.warning("API key field found but value is empty or invalid (final attempt)")
                else:
                    logger.warning(f"Settings page returned status {response.status_code}")
                    
            except Exception as e:
                if attempt < max_retries:
                    logger.warning(f"Failed to retrieve API key (attempt {attempt + 1}): {e}, retrying...")
                else:
                    logger.error(f"Failed to retrieve API key (final attempt): {e}")
        
        return None
    
    def enable_import(self, nonce: Optional[str] = None) -> bool:
        """
        Enable 'Allow Import' setting for target sites
        
        Args:
            nonce: WordPress nonce for options update
        
        Returns:
            True if setting enabled successfully
        """
        try:
            # Get nonce from settings page if not provided
            if not nonce:
                response = self.session.get(
                    f"{self.base_url}/wp-admin/options-general.php?page=custom-migrator-settings",
                    timeout=30
                )
                
                if response.status_code == 200:
                    match = re.search(r'_wpnonce"\s+value="([a-f0-9]+)"', response.text)
                    if match:
                        nonce = match.group(1)
            
            if not nonce:
                logger.error("Could not retrieve nonce for options update")
                return False
            
            # Submit form to enable import
            data = {
                'option_page': 'custom_migrator_settings',
                'action': 'update',
                'custom_migrator_allow_import': '1',
                '_wpnonce': nonce,
                '_wp_http_referer': '/wp-admin/options-general.php?page=custom-migrator-settings',
                'submit': 'Save Changes'
            }
            
            logger.info("Enabling 'Allow Import' setting...")
            
            response = self.session.post(
                f"{self.base_url}/wp-admin/options.php",
                data=data,
                timeout=30,
                allow_redirects=True
            )
            
            if response.status_code == 200:
                # Check if settings saved successfully
                if 'Settings saved' in response.text or 'updated successfully' in response.text.lower():
                    logger.info("'Allow Import' enabled successfully")
                    return True
            
            logger.warning(f"Enable import request returned status {response.status_code}")
            return False
            
        except Exception as e:
            logger.error(f"Failed to enable import: {e}")
            return False
    
    def verify_import_enabled(self) -> bool:
        """
        Verify 'Allow Import' setting is enabled
        
        Returns:
            True if import is enabled
        """
        try:
            response = self.session.get(
                f"{self.base_url}/wp-admin/options-general.php?page=custom-migrator-settings",
                timeout=30
            )
            
            if response.status_code == 200:
                # Check if checkbox is checked
                if 'name="custom_migrator_allow_import"' in response.text:
                    if 'checked' in response.text or 'value="1"' in response.text:
                        return True
            
        except Exception as e:
            logger.debug(f"Failed to verify import setting: {e}")
        
        return False
