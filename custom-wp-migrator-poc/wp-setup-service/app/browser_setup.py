"""
Browser-based WordPress setup using Playwright for target instances
"""

import logging
import os
import asyncio
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from typing import Optional

logger = logging.getLogger(__name__)

# Try to find the plugin zip in common locations
DEFAULT_ZIP_PATH = os.getenv('PLUGIN_ZIP_PATH', '/app/plugin.zip')
if not os.path.exists(DEFAULT_ZIP_PATH):
    if os.path.exists('/app/custom-migrator.zip'):
        DEFAULT_ZIP_PATH = '/app/custom-migrator.zip'
    elif os.path.exists('./plugin.zip'):
        DEFAULT_ZIP_PATH = './plugin.zip'

PLUGIN_ZIP_PATH = DEFAULT_ZIP_PATH


async def setup_target_with_browser(url: str, username: str, password: str) -> dict:
    """
    Setup target WordPress using browser automation
    
    This is more reliable for fresh WordPress instances that have stricter
    security checks and may not work well with cookie-based HTTP requests.
    
    Args:
        url: WordPress site URL
        username: Admin username
        password: Admin password
    
    Returns:
        Dict with setup results including API key
    """
    logger.info(f"Starting browser-based setup for {url}")
    url = url.rstrip('/')
    
    browser = None
    try:
        async with async_playwright() as p:
            # Launch browser in headless mode with more "real" browser characteristics
            browser = await p.chromium.launch(
                headless=True,
                args=['--disable-blink-features=AutomationControlled']
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
                viewport={'width': 1280, 'height': 800}
            )
            page = await context.new_page()
            
            # Step 1: Login
            logger.info(f"Logging in to {url}")
            await page.goto(f"{url}/wp-login.php", timeout=30000)
            
            # Fill login form
            await page.wait_for_selector('input[name="log"]', timeout=10000)
            await page.fill('input[name="log"]', username)
            await page.fill('input[name="pwd"]', password)
            
            # Submit and wait for navigation
            logger.info("Submitting login form")
            async with page.expect_navigation(timeout=30000):
                await page.click('input[name="wp-submit"]')
            
            # Small delay to ensure cookies are saved
            await asyncio.sleep(2)
            
            # Check if login successful
            logger.info(f"After login attempt, URL is: {page.url}")
            if "wp-login.php" in page.url:
                logger.warning("Still on login page, checking for errors...")
                error_msg = await page.locator("#login_error").text_content() if await page.locator("#login_error").count() > 0 else "Unknown error"
                logger.error(f"Login failed: {error_msg}")
                
                # If it's just a reauth issue, try to navigate to admin anyway
                if "reauth=1" in page.url:
                    logger.info("Detected reauth=1, attempting to force navigate to wp-admin...")
                    await page.goto(f"{url}/wp-admin/", timeout=30000)
            
            if '/wp-admin' not in page.url:
                logger.error(f"Failed to reach admin area. Current URL: {page.url}")
                # Log page content for debugging
                content = await page.content()
                logger.debug(f"Page content: {content[:1000]}")
                return {
                    'success': False,
                    'error_code': 'LOGIN_FAILED',
                    'message': f'Failed to reach admin area. Current URL: {page.url}'
                }
            
            logger.info("Successfully reached admin area")
            
            # Step 2: Upload plugin
            logger.info("Navigating to plugin upload page")
            await page.goto(f"{url}/wp-admin/plugin-install.php?tab=upload", timeout=30000)
            
            # Wait for page to be fully loaded and check if we are still authenticated
            await page.wait_for_load_state('networkidle', timeout=10000)
            
            if "wp-login.php" in page.url:
                logger.error("Redirected to login page when trying to access upload page")
                return {
                    'success': False,
                    'error_code': 'AUTH_LOST',
                    'message': 'Session lost when navigating to upload page'
                }
            
            # Upload the plugin zip
            logger.info(f"Uploading plugin from {PLUGIN_ZIP_PATH}")
            
            # Check if the "Upload Plugin" button needs to be clicked first (some versions hide the form)
            upload_button = page.locator('.upload-view-toggle')
            if await upload_button.count() > 0 and await upload_button.is_visible():
                logger.info("Clicking 'Upload Plugin' toggle button")
                await upload_button.click()

            file_input = page.locator('input[type="file"][name="pluginzip"]')
            
            # Wait for file input to be visible with longer timeout
            try:
                await file_input.wait_for(state='visible', timeout=20000)
                logger.info("File input is visible")
            except PlaywrightTimeout:
                logger.warning("File input not visible, checking if it is just attached...")
                await file_input.wait_for(state='attached', timeout=10000)
                logger.info("File input is attached but not visible")
            
            logger.info("Setting file input...")
            await file_input.set_input_files(PLUGIN_ZIP_PATH)
            logger.info("File set, clicking install button")
            
            # Click install button and wait for navigation
            async with page.expect_navigation(timeout=60000):
                await page.click('input[type="submit"][name="install-plugin-submit"]')
            
            logger.info(f"Navigation complete, current URL: {page.url}")
            
            # Wait for upload to complete - check for success message
            try:
                await page.wait_for_selector('text=Plugin installed successfully', timeout=10000)
                logger.info("Plugin uploaded successfully")
            except PlaywrightTimeout:
                # Check if there's an error message
                error_text = await page.text_content('body')
                logger.error(f"Plugin upload may have failed. Page content: {error_text[:500]}")
                raise
            
            # Step 3: Activate plugin
            logger.info("Activating plugin")
            activate_link = page.locator('a:has-text("Activate Plugin")')
            await activate_link.click()
            
            # Wait for activation
            await page.wait_for_url('**/wp-admin/plugins.php**', timeout=30000)
            logger.info("Plugin activated successfully")
            
            # Step 4: Get API key from plugin settings
            logger.info("Navigating to plugin settings to get API key")
            await page.goto(f"{url}/wp-admin/options-general.php?page=custom-migrator-settings", timeout=30000)
            
            # Wait for API key field
            api_key_input = page.locator('input[name="custom_migrator_api_key"]')
            await api_key_input.wait_for(timeout=10000)
            
            # Get API key value
            api_key = await api_key_input.get_attribute('value')
            
            if not api_key or len(api_key) != 32:
                logger.error(f"Invalid API key retrieved: {api_key}")
                return {
                    'success': False,
                    'error_code': 'INVALID_API_KEY',
                    'message': 'Failed to retrieve valid API key from plugin settings'
                }
            
            logger.info(f"Successfully retrieved API key: {api_key[:8]}...")
            
            # Step 5: Enable import for target
            logger.info("Enabling import on target")
            import_checkbox = page.locator('input[name="custom_migrator_enable_import"]')
            
            # Check if already checked
            is_checked = await import_checkbox.is_checked()
            if not is_checked:
                await import_checkbox.check()
                
                # Save settings
                save_button = page.locator('input[type="submit"][name="submit"]')
                await save_button.click()
                
                # Wait for settings saved message
                await page.wait_for_selector('text=Settings saved', timeout=10000)
                logger.info("Import enabled and settings saved")
            else:
                logger.info("Import already enabled")
            
            await browser.close()
            
            return {
                'success': True,
                'api_key': api_key,
                'plugin_status': 'activated',
                'import_enabled': True,
                'message': 'Browser-based setup completed successfully'
            }
            
    except PlaywrightTimeout as e:
        logger.error(f"Browser automation timeout: {str(e)}")
        if browser:
            await browser.close()
        return {
            'success': False,
            'error_code': 'BROWSER_TIMEOUT',
            'message': f'Browser automation timed out: {str(e)}'
        }
    except Exception as e:
        logger.error(f"Browser-based setup failed: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        if browser:
            await browser.close()
        return {
            'success': False,
            'error_code': 'BROWSER_SETUP_ERROR',
            'message': f'Browser setup failed: {str(e)}'
        }
