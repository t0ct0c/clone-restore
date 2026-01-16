"""
WordPress Plugin Installation Module

Handles uploading and activating WordPress plugins programmatically.
"""

import logging
import os
from typing import Optional
from bs4 import BeautifulSoup
import requests
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError


logger = logging.getLogger(__name__)


class WordPressPluginInstaller:
    """Install and activate WordPress plugins"""
    
    def __init__(self, session: requests.Session, base_url: str):
        self.session = session
        self.base_url = base_url.rstrip('/')
    
    def is_plugin_installed(self, plugin_slug: str) -> bool:
        """
        Check if plugin is already installed
        
        Args:
            plugin_slug: Plugin directory name (e.g., 'custom-migrator')
        
        Returns:
            True if plugin is installed
        """
        # Try REST API first
        try:
            response = self.session.get(
                f"{self.base_url}/wp-json/wp/v2/plugins",
                timeout=30
            )
            
            if response.status_code == 200:
                plugins = response.json()
                for plugin in plugins:
                    if plugin_slug in plugin.get('plugin', ''):
                        logger.info(f"Plugin {plugin_slug} found via REST API")
                        return True
        except Exception as e:
            logger.debug(f"REST API check failed: {e}")
        
        # Fallback: screen-scrape plugins page
        try:
            response = self.session.get(
                f"{self.base_url}/wp-admin/plugins.php",
                timeout=30
            )
            
            if response.status_code == 200:
                if plugin_slug in response.text:
                    logger.info(f"Plugin {plugin_slug} found via HTML scraping")
                    return True
        except Exception as e:
            logger.debug(f"HTML scraping check failed: {e}")
        
        return False
    
    def upload_plugin(self, plugin_zip_path: str, nonce: str) -> bool:
        """
        Upload plugin ZIP file via admin panel
        
        Args:
            plugin_zip_path: Path to plugin ZIP file
            nonce: WordPress nonce for plugin upload
        
        Returns:
            True if upload successful
        """
        if not os.path.exists(plugin_zip_path):
            logger.error(f"Plugin ZIP not found: {plugin_zip_path}")
            return False
        
        try:
            with open(plugin_zip_path, 'rb') as f:
                files = {
                    'pluginzip': ('plugin.zip', f, 'application/zip')
                }
                data = {
                    '_wpnonce': nonce,
                    'install-plugin-submit': 'Install Now'
                }
                
                logger.info(f"Uploading plugin from {plugin_zip_path}...")
                
                response = self.session.post(
                    f"{self.base_url}/wp-admin/update.php?action=upload-plugin",
                    files=files,
                    data=data,
                    timeout=120
                )
                
                if response.status_code == 200:
                    # Check for success messages
                    if ('Plugin installed successfully' in response.text or
                        'successfully installed' in response.text.lower()):
                        logger.info("Plugin uploaded successfully")
                        return True
                    
                    # Check for errors
                    if 'error' in response.text.lower():
                        soup = BeautifulSoup(response.text, 'lxml')
                        error_msg = soup.find('div', class_='error')
                        if error_msg:
                            logger.error(f"Plugin upload error: {error_msg.get_text(strip=True)}")
                        else:
                            logger.error("Plugin upload failed with unknown error")
                        return False
                
                logger.error(f"Plugin upload failed with status {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Plugin upload exception: {e}")
            return False
    
    async def activate_plugin(self, plugin_path: str, nonce: str, rest_nonce: str = None, username: str = None, password: str = None) -> tuple[bool, str]:
        """
        Activate installed plugin
        
        Args:
            plugin_path: Plugin path (e.g., 'custom-migrator/custom-migrator.php')
            nonce: WordPress nonce for plugin activation
            rest_nonce: REST API nonce (optional)
            username: WordPress username for browser-based activation
            password: WordPress password for browser-based activation
        
        Returns:
            Tuple of (success: bool, api_key: str or None)
        """
        try:
            logger.info(f"Activating plugin {plugin_path}...")
            
            # Try browser-based activation first if credentials provided
            if username and password:
                try:
                    logger.info("Attempting activation via browser...")
                    result = await self._activate_with_browser(plugin_path, username, password)
                    if result[0]:  # If activation successful
                        return result  # Return (True, api_key)
                    logger.warning("Browser activation failed, trying API methods...")
                except Exception as e:
                    logger.warning(f"Browser activation failed: {e}, trying API methods...")
            
            # Try REST API if we have the nonce
            if rest_nonce:
                try:
                    logger.info("Attempting activation via REST API...")
                    rest_response = self.session.put(
                        f"{self.base_url}/wp-json/wp/v2/plugins/{plugin_path.replace('/', '%2F')}",
                        json={'status': 'active'},
                        headers={'X-WP-Nonce': rest_nonce},
                        timeout=60
                    )
                    
                    if rest_response.status_code == 200:
                        logger.info(f"Plugin {plugin_path} activated via REST API")
                        return (True, None)  # API key will be retrieved separately
                    else:
                        logger.warning(f"REST API activation failed with status {rest_response.status_code}, trying traditional method...")
                except Exception as e:
                    logger.warning(f"REST API activation failed: {e}, trying traditional method...")
            
            # Fallback to traditional GET request
            import urllib.parse
            params = {
                'action': 'activate',
                'plugin': plugin_path,
                '_wpnonce': nonce
            }
            
            activation_url = f"{self.base_url}/wp-admin/plugins.php?{urllib.parse.urlencode(params)}"
            logger.info(f"Activation URL: {activation_url}")
            
            headers = {
                'Referer': f"{self.base_url}/wp-admin/plugins.php"
            }
            
            response = self.session.get(
                activation_url,
                headers=headers,
                timeout=60,
                allow_redirects=True
            )
            
            logger.info(f"Activation response status: {response.status_code}")
            
            if response.status_code == 200:
                # Check for success
                if ('Plugin activated' in response.text or
                    'activated successfully' in response.text.lower()):
                    logger.info(f"Plugin {plugin_path} activated successfully")
                    return (True, None)  # API key will be retrieved separately
                
                # Check if already active
                if 'Plugin is already active' in response.text:
                    logger.info(f"Plugin {plugin_path} is already active")
                    return (True, None)
                
                # Check for errors
                if 'error' in response.text.lower():
                    soup = BeautifulSoup(response.text, 'lxml')
                    error_msg = soup.find('div', class_='error')
                    if error_msg:
                        logger.error(f"Activation error: {error_msg.get_text(strip=True)}")
                    else:
                        logger.error(f"Unknown activation error in response")
                    return (False, None)
            
            logger.error(f"Plugin activation failed with status {response.status_code}")
            return (False, None)
            
        except Exception as e:
            logger.error(f"Plugin activation exception: {e}")
            return (False, None)
    
    async def deactivate_plugin(self, plugin_path: str, nonce: str, username: str = None, password: str = None) -> bool:
        """
        Deactivate plugin
        
        Args:
            plugin_path: Plugin path (e.g., 'custom-migrator/custom-migrator.php')
            nonce: WordPress nonce for plugin deactivation
            username: WordPress username for browser-based deactivation
            password: WordPress password for browser-based deactivation
        
        Returns:
            True if deactivation successful
        """
        try:
            logger.info(f"Deactivating plugin {plugin_path}...")
            
            # Try browser-based deactivation first if credentials provided
            if username and password:
                try:
                    logger.info("Attempting deactivation via browser...")
                    if await self._deactivate_with_browser(plugin_path, username, password):
                        return True
                    logger.warning("Browser deactivation failed, trying traditional method...")
                except Exception as e:
                    logger.warning(f"Browser deactivation failed: {e}, trying traditional method...")
            
            # Fallback to traditional GET request
            import urllib.parse
            params = {
                'action': 'deactivate',
                'plugin': plugin_path,
                '_wpnonce': nonce
            }
            
            deactivation_url = f"{self.base_url}/wp-admin/plugins.php?{urllib.parse.urlencode(params)}"
            
            headers = {
                'Referer': f"{self.base_url}/wp-admin/plugins.php"
            }
            
            response = self.session.get(
                deactivation_url,
                headers=headers,
                timeout=60,
                allow_redirects=True
            )
            
            logger.info(f"Deactivation response status: {response.status_code}")
            
            if response.status_code == 200:
                if 'Plugin deactivated' in response.text or 'deactivated successfully' in response.text.lower():
                    logger.info(f"Plugin {plugin_path} deactivated successfully")
                    return True
                # Check if already inactive
                if 'Plugin is not active' in response.text or 'inactive' in response.text.lower():
                    logger.info(f"Plugin {plugin_path} is already inactive")
                    return True
            
            logger.error(f"Plugin deactivation failed with status {response.status_code}")
            return False
            
        except Exception as e:
            logger.error(f"Plugin deactivation exception: {e}")
            return False
    
    async def _deactivate_with_browser(self, plugin_path: str, username: str, password: str) -> bool:
        """
        Deactivate plugin using headless browser
        
        Args:
            plugin_path: Plugin path (e.g., 'custom-migrator/custom-migrator.php')
            username: WordPress admin username
            password: WordPress admin password
        
        Returns:
            True if deactivation successful
        """
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context()
                page = await context.new_page()
                
                # Login
                logger.info(f"Browser: Navigating to login page...")
                await page.goto(f"{self.base_url}/wp-login.php", timeout=30000)
                await page.fill('#user_login', username)
                await page.fill('#user_pass', password)
                await page.click('#wp-submit')
                await page.wait_for_load_state('networkidle', timeout=30000)
                
                # Go to plugins page
                logger.info(f"Browser: Navigating to plugins page...")
                await page.goto(f"{self.base_url}/wp-admin/plugins.php", timeout=30000)
                await page.wait_for_load_state('networkidle', timeout=10000)
                
                # Find and click the deactivate link
                plugin_slug = plugin_path.split('/')[0]
                logger.info(f"Browser: Looking for plugin '{plugin_slug}' deactivate link...")
                
                deactivate_link = page.locator(f"a[href*='action=deactivate'][href*='{plugin_slug}']").first
                
                if await deactivate_link.count() > 0:
                    logger.info(f"Browser: Clicking deactivate link...")
                    await deactivate_link.click()
                    await page.wait_for_load_state('networkidle', timeout=30000)
                    
                    page_content = await page.content()
                    if 'Plugin deactivated' in page_content or 'activate' in page_content.lower():
                        logger.info("Browser: Plugin deactivated successfully")
                        await browser.close()
                        return True
                else:
                    logger.warning(f"Browser: Could not find deactivate link for {plugin_slug}")
                
                await browser.close()
                return False
                
        except PlaywrightTimeoutError as e:
            logger.error(f"Browser deactivation timeout: {e}")
            return False
        except Exception as e:
            logger.error(f"Browser deactivation exception: {e}")
            return False
    
    def check_plugin_status(self, plugin_slug: str) -> str:
        """
        Check plugin status (active/inactive/not-installed)
        
        Args:
            plugin_slug: Plugin slug to check
        
        Returns:
            Status string: 'active', 'inactive', or 'not-installed'
        """
        # Try REST API first
        try:
            response = self.session.get(
                f"{self.base_url}/wp-json/wp/v2/plugins",
                timeout=30
            )
            
            if response.status_code == 200:
                plugins = response.json()
                for plugin in plugins:
                    if plugin_slug in plugin.get('plugin', ''):
                        return 'active' if plugin.get('status') == 'active' else 'inactive'
        except Exception as e:
            logger.debug(f"REST API status check failed: {e}")
        
        # Fallback: check via HTML
        if self.is_plugin_installed(plugin_slug):
            # Check if in active plugins section
            try:
                response = self.session.get(
                    f"{self.base_url}/wp-admin/plugins.php",
                    timeout=30
                )
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'lxml')
                    active_row = soup.find('tr', class_='active')
                    if active_row and plugin_slug in str(active_row):
                        return 'active'
                    return 'inactive'
            except Exception:
                pass
            return 'inactive'
        
        return 'not-installed'
    
    async def _activate_with_browser(self, plugin_path: str, username: str, password: str) -> tuple[bool, str]:
        """
        Activate plugin using headless browser and extract API key
        
        Args:
            plugin_path: Plugin path (e.g., 'custom-migrator/custom-migrator.php')
            username: WordPress admin username
            password: WordPress admin password
        
        Returns:
            Tuple of (success: bool, api_key: str or None)
        """
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context()
                page = await context.new_page()
                
                # Login
                logger.info(f"Browser: Navigating to login page...")
                await page.goto(f"{self.base_url}/wp-login.php", timeout=30000)
                await page.fill('#user_login', username)
                await page.fill('#user_pass', password)
                await page.click('#wp-submit')
                
                # Wait for redirect to admin
                await page.wait_for_load_state('networkidle', timeout=30000)
                
                # Go to plugins page
                logger.info(f"Browser: Navigating to plugins page...")
                await page.goto(f"{self.base_url}/wp-admin/plugins.php", timeout=30000)
                await page.wait_for_load_state('networkidle', timeout=10000)
                
                # Find and click the activate link for our plugin
                plugin_slug = plugin_path.split('/')[0]
                logger.info(f"Browser: Looking for plugin '{plugin_slug}' activation link...")
                
                # Debug: Log page content to understand structure
                page_content = await page.content()
                if plugin_slug in page_content:
                    logger.info(f"Browser: Plugin '{plugin_slug}' found in page content")
                else:
                    logger.warning(f"Browser: Plugin '{plugin_slug}' not found in page content")
                
                # Try multiple selectors to find the activate link
                selectors = [
                    f"tr[data-slug='{plugin_slug}'] .activate a",
                    f"tr:has-text('{plugin_slug}') .activate a", 
                    f"a[href*='action=activate'][href*='{plugin_slug}']",
                    f"a[href*='action=activate'][href*='{plugin_path.replace('/', '%2F')}']",
                    "a:has-text('Activate'):visible"
                ]
                
                activate_link = None
                for selector in selectors:
                    try:
                        locator = page.locator(selector).first
                        if await locator.count() > 0:
                            logger.info(f"Browser: Found activate link using selector: {selector}")
                            activate_link = locator
                            break
                    except Exception as e:
                        logger.debug(f"Browser: Selector '{selector}' failed: {e}")
                
                if activate_link:
                    logger.info(f"Browser: Clicking activate link...")
                    await activate_link.click()
                    await page.wait_for_load_state('networkidle', timeout=30000)
                    
                    # Check if activation was successful
                    page_content = await page.content()
                    if 'Plugin activated' in page_content or 'deactivate' in page_content.lower():
                        logger.info("Browser: Plugin activated successfully")
                        
                        # Navigate to settings page to extract API key
                        logger.info("Browser: Navigating to plugin settings to extract API key...")
                        await page.goto(f"{self.base_url}/wp-admin/options-general.php?page=custom-migrator-settings", timeout=30000)
                        await page.wait_for_load_state('networkidle', timeout=10000)
                        
                        # Wait a moment for API key to be generated
                        await page.wait_for_timeout(2000)
                        
                        # Extract API key from input field
                        try:
                            api_key_input = page.locator('input[name="custom_migrator_api_key"]')
                            api_key = await api_key_input.get_attribute('value')
                            
                            if api_key and len(api_key) == 32:
                                logger.info(f"Browser: Successfully extracted API key: {api_key[:10]}...")
                                await browser.close()
                                return (True, api_key)
                            else:
                                logger.warning(f"Browser: API key field found but value invalid: {api_key}")
                                await browser.close()
                                return (True, None)  # Activation succeeded but no API key
                        except Exception as e:
                            logger.warning(f"Browser: Failed to extract API key: {e}")
                            await browser.close()
                            return (True, None)  # Activation succeeded but couldn't get API key
                    else:
                        logger.error("Browser: Activation link clicked but no success message found")
                        logger.debug(f"Browser: Page content after click: {page_content[:500]}...")
                else:
                    logger.error(f"Browser: Could not find activate link for {plugin_slug}")
                    # Debug: List all activate links found
                    all_activate_links = await page.locator("a:has-text('Activate')").all()
                    logger.debug(f"Browser: Found {len(all_activate_links)} activate links on page")
                
                await browser.close()
                return (False, None)
                
        except PlaywrightTimeoutError as e:
            logger.error(f"Browser activation timeout: {e}")
            return (False, None)
        except Exception as e:
            logger.error(f"Browser activation exception: {e}")
            return (False, None)
