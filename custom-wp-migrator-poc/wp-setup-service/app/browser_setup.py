"""
Browser-based WordPress setup using Playwright for target instances
"""
from loguru import logger
import os
import asyncio
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from camoufox.async_api import AsyncCamoufox
from typing import Optional
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

# Try to find the plugin zip in common locations
DEFAULT_ZIP_PATH = os.getenv('PLUGIN_ZIP_PATH', '/app/plugin.zip')
if not os.path.exists(DEFAULT_ZIP_PATH):
    if os.path.exists('/app/custom-migrator.zip'):
        DEFAULT_ZIP_PATH = '/app/custom-migrator.zip'
    elif os.path.exists('./plugin.zip'):
        DEFAULT_ZIP_PATH = './plugin.zip'

PLUGIN_ZIP_PATH = DEFAULT_ZIP_PATH


async def setup_wordpress_with_browser(url: str, username: str, password: str, role: str = 'target') -> dict:
    """
    Setup WordPress using browser automation
    
    This is more reliable for external WordPress instances that have stricter
    security checks, 2FA, security plugins, or may not work well with cookie-based HTTP requests.
    
    Args:
        url: WordPress site URL
        username: Admin username
        password: Admin password
        role: 'source' or 'target' (determines if import should be enabled)
    
    Returns:
        Dict with setup results including API key
    """
    with tracer.start_as_current_span(f"browser_setup_{role}") as span:
        span.set_attribute("wordpress.url", url)
        span.set_attribute("wordpress.role", role)
        trace_id = format(span.get_span_context().trace_id, '032x')
        l = logger.bind(trace_id=trace_id)
        
        l.info(f"Starting browser-based setup for {url} (role: {role})")
        # Always normalize URL by removing trailing slash
        # We'll add paths with / prefix, so trailing slash causes double //
        url = url.rstrip('/')
        
        try:
            async with AsyncCamoufox(headless=True) as browser:
                # Create a context with realistic fingerprints
                context = await browser.new_context(
                    viewport={'width': 1280, 'height': 800},
                    accept_downloads=True
                )
                
                # Set global timeout for all actions
                context.set_default_timeout(240000) # 240s
                context.set_default_navigation_timeout(240000) # 240s
                
                page = await context.new_page()
                
                # Step 1: Login
                l.info(f"Step 1: Navigating to login page {url}/wp-login.php")
                try:
                    await page.goto(f"{url}/wp-login.php", wait_until="networkidle", timeout=120000)
                except Exception as e:
                    l.error(f"Failed to load login page: {e}")
                    # Log current page content for debugging
                    content = await page.content()
                    l.debug(f"Current page content (first 1000 chars): {content[:1000]}")
                    raise
                
                # Check for bot block or specific challenge
                content = await page.content()
                if "Cloudflare" in content or "Attention Required" in content:
                    l.warning("Detected Cloudflare or bot challenge on login page - trying to wait it out")
                    await asyncio.sleep(5)
                
                # Fill login form
                l.info("Filling login credentials")
                try:
                    await page.wait_for_selector('input[name="log"]', state="visible", timeout=60000)
                    await page.fill('input[name="log"]', username)
                    await page.fill('input[name="pwd"]', password)
                except Exception as e:
                    l.error(f"Login fields not found: {e}")
                    # Take a screenshot if possible? No, we don't have a volume mounted for it yet.
                    # Just log the page title and content snippet
                    title = await page.title()
                    l.info(f"Page title: {title}")
                    raise
                
                # Submit and wait for navigation
                l.info("Submitting login form and waiting for admin redirect")
                await page.click('input[name="wp-submit"]')
                
                # Wait for either admin dashboard or login error
                try:
                    # WordPress admin bar is a good indicator of successful login
                    await page.wait_for_selector('#wpadminbar, .login-action-login, #login_error', timeout=60000)
                except Exception:
                    l.warning("Timed out waiting for admin bar or login error after submit, checking current URL")
                
                # Small delay to ensure cookies are saved
                await asyncio.sleep(5)
                
                # Check if login successful
                l.info(f"After login attempt, current URL is: {page.url}")
                if "wp-login.php" in page.url:
                    l.warning("Still on login page, checking for error messages...")
                    login_error = page.locator("#login_error")
                    if await login_error.count() > 0:
                        error_text = await login_error.inner_text()
                        l.error(f"WordPress Login Error: {error_text.strip()}")
                    
                    # If it's just a reauth issue, try to navigate to admin anyway
                    if "reauth=1" in page.url or "loggedout=true" in page.url:
                        l.info("Detected reauth or loggedout, attempting force navigation to wp-admin")
                        await page.goto(f"{url}/wp-admin/", wait_until="networkidle", timeout=60000)
                
                # Check for both /wp-admin/ and /wp-admin.php (new clones use .php)
                if '/wp-admin' not in page.url and 'wp-admin.php' not in page.url:
                    l.error(f"Failed to reach admin area after login. Current URL: {page.url}")
                    # Log snippets of content to see if we're stuck on a 'Verify you are human' page
                    content = await page.content()
                    if "Verify you are human" in content or "Cloudflare" in content:
                        return {
                            'success': False,
                            'error_code': 'BOT_BLOCKED',
                            'message': 'Site is blocking automation via Cloudflare/Bot protection. Try again later or use camoufox.'
                        }
                    return {
                        'success': False,
                        'error_code': 'LOGIN_FAILED',
                        'message': f'Failed to reach admin area. Site might be blocking automated login. URL: {page.url}'
                    }
                
                l.info("Successfully reached admin area")
                
                # Step 2: Upload plugin
                l.info("Step 2: Checking if plugin needs upload on plugins page")
                await page.goto(f"{url}/wp-admin/plugins.php", wait_until="domcontentloaded", timeout=90000)
                
                plugin_slug = 'custom-migrator'
                # Wait for page to be ready - use multiple possible selectors
                try:
                    await page.wait_for_selector('.wp-list-table, #the-list, .plugins', timeout=30000)
                    l.info("Plugins table loaded successfully")
                except Exception as e:
                    l.warning(f"Plugins table selector timeout, checking content anyway: {e}")
                
                # Give slow sites extra time to fully render (betaweb.ai needs this)
                l.info("Waiting 5 seconds for page to fully render...")
                await page.wait_for_timeout(5000)
                
                # Check if plugin is already installed using proper selectors
                plugin_exists = False
                plugin_row = page.locator(f"tr[data-slug='{plugin_slug}']")
                count1 = await plugin_row.count()
                l.info(f"Checking tr[data-slug='{plugin_slug}']: found {count1}")
                
                if count1 == 0:
                    # Try fallback selectors
                    plugin_row = page.locator("tr[data-slug='custom-migrator.php']")
                    count2 = await plugin_row.count()
                    l.info(f"Checking tr[data-slug='custom-migrator.php']: found {count2}")
                    
                    if count2 == 0:
                        plugin_row = page.locator("tr:has-text('Custom WP Migrator')")
                        count3 = await plugin_row.count()
                        l.info(f"Checking tr:has-text('Custom WP Migrator'): found {count3}")
                
                if await plugin_row.count() > 0:
                    plugin_exists = True
                    l.info("Plugin already installed, skipping upload")
                else:
                    # For target role, if plugin not found, it might be corrupted or hidden
                    # Skip upload (which causes session loss) and try to activate directly
                    if role == 'target':
                        l.warning("Plugin not detected on target site - assuming it exists but is corrupted, will try direct activation")
                        plugin_exists = True  # Pretend it exists to skip upload
                
                if not plugin_exists:
                    l.info("Plugin not found in list, navigating to upload page")
                    await page.goto(f"{url}/wp-admin/plugin-install.php?tab=upload", wait_until="networkidle", timeout=60000)
                    
                    if "wp-login.php" in page.url:
                        l.error("Session lost: redirected to login page during upload attempt")
                        return {
                            'success': False,
                            'error_code': 'AUTH_LOST',
                            'message': 'Authentication session lost while navigating to upload'
                        }
                    
                    # Upload the plugin zip
                    l.info(f"Uploading plugin ZIP from path: {PLUGIN_ZIP_PATH}")
                    
                    # Check if the "Upload Plugin" button needs to be clicked first
                    upload_toggle = page.locator('.upload-view-toggle')
                    if await upload_toggle.count() > 0 and await upload_toggle.is_visible():
                        l.info("Clicking 'Upload Plugin' toggle")
                        await upload_toggle.click()
    
                    file_input = page.locator('input[type="file"][name="pluginzip"]')
                    await file_input.wait_for(state='attached', timeout=60000)
                    
                    l.info("Attaching plugin zip file")
                    await file_input.set_input_files(PLUGIN_ZIP_PATH)
                    
                    l.info("Clicking 'Install Now' and waiting for completion")
                    
                    try:
                        # Monitor outgoing requests to see if the upload actually starts
                        upload_started = False
                        async def log_request(request):
                            nonlocal upload_started
                            if request.method == "POST" and "update.php" in request.url:
                                l.info(f"Detected outgoing upload request: {request.url}")
                                upload_started = True
                        
                        page.on("request", log_request)

                        # Try multiple common selectors for the install button
                        submit_button = page.locator('input[type="submit"][name="install-plugin-submit"], #install-plugin-submit, input[value="Install Now"]')
                        
                        # Wait for the button to be present
                        await submit_button.wait_for(state='attached', timeout=60000)
                        
                        l.info("Button found, clicking 'Install Now'")
                        
                        try:
                            # Try a regular click with force=True and a shorter timeout
                            await submit_button.click(delay=100, force=True, timeout=30000)
                        except Exception as click_err:
                            l.warning(f"Regular click failed: {click_err}. Trying JavaScript click fallback...")
                            await page.evaluate('(sel) => { const el = document.querySelector(sel); if(el) el.click(); }', 'input[type="submit"][name="install-plugin-submit"], #install-plugin-submit, input[value="Install Now"]')
                        
                        # Wait a few seconds to see if it starts navigating
                        await asyncio.sleep(5)
                        
                        if not upload_started:
                            l.warning("Click didn't seem to trigger an upload request. Attempting form submission via JavaScript...")
                            try:
                                await page.evaluate('() => { const f = document.querySelector("form#plugin-upload-form, form.wp-upload-form"); if(f) f.submit(); }')
                            except Exception as eval_err:
                                l.error(f"JavaScript form submission failed: {eval_err}")

                        l.info("Waiting for result (navigation or error message)...")
                        
                        # Check progress every 15 seconds
                        for attempt in range(1, 13): # 12 * 15s = 180s
                            try:
                                # Wait for either the URL to change to update.php OR an error/success notice to appear
                                await page.wait_for_function(
                                    "() => window.location.href.includes('update.php') || document.querySelector('.error, .notice-error, .updated, .notice-success, #wp-admin-installer-error')",
                                    timeout=15000
                                )
                                break # If it finishes waiting, we are done
                            except Exception:
                                l.info(f"Wait attempt {attempt}/12: Still on {page.url}. Page title: {await page.title()}")
                                if attempt % 2 == 0: # Every 30s, log a bit of page content
                                    body_text = await page.inner_text("body")
                                    l.debug(f"Current page text snippet: {body_text[:500].replace(chr(10), ' ')}")
                        
                        l.info(f"Final URL after upload attempt: {page.url}")
                        
                        # Remove listener
                        page.remove_listener("request", log_request)
                        
                    except Exception as e:
                        l.error(f"Upload POST request failed or timed out: {e}")
                        # Log current page state
                        l.info(f"Current URL after timeout: {page.url}")
                        content = await page.content()
                        if 'error' in content.lower() or 'forbidden' in content.lower():
                            l.error("Page content contains error indicators")
                        raise
                    
                    # Check for success message
                    l.info("Checking for success or error messages...")
                    try:
                        await page.wait_for_selector('text=Plugin installed successfully', timeout=30000)
                        l.info("Success message 'Plugin installed successfully' found")
                    except Exception as e:
                        l.warning(f"Did not see 'Plugin installed successfully' message: {e}")
                        # Check for error messages
                        error_locator = page.locator('.error, .notice-error')
                        if await error_locator.count() > 0:
                            error_text = await error_locator.first.inner_text()
                            l.error(f"Upload error detected: {error_text}")
                            raise Exception(f"Plugin upload failed: {error_text}")
                        # Check if URL changed to indicate success despite missing message
                        if 'plugin-install.php?tab=upload' not in page.url:
                            l.info(f"URL changed to {page.url}, assuming upload succeeded")
                    
                    l.info(f"Upload flow complete, current URL: {page.url}")
                    
                    # Try to activate directly from the success page if the link exists
                    activate_direct = page.locator('a:has-text("Activate Plugin")')
                    if await activate_direct.count() > 0:
                        l.info("Found 'Activate Plugin' link on success page, clicking it directly")
                        async with page.expect_navigation(timeout=60000):
                            await activate_direct.click()
                        l.info("Direct activation complete")
                        
                    # Navigate back to plugins page to verify or activate if direct failed
                    await page.goto(f"{url}/wp-admin/plugins.php", wait_until="networkidle", timeout=60000)
                else:
                    l.info("Plugin already appears to be installed, skipping upload")
    
                # Step 3: Activate plugin
                l.info("Step 3: Activating plugin if inactive")
                # Wait for plugins table
                await page.wait_for_selector('.wp-list-table', timeout=30000)
                
                plugin_row = page.locator(f"tr[data-slug='{plugin_slug}']")
                
                if await plugin_row.count() == 0:
                    l.info(f"Plugin slug '{plugin_slug}' not found, trying fallback 'custom-migrator.php' or name search")
                    # Try another common slug variant
                    plugin_row = page.locator("tr[data-slug='custom-migrator.php']")
                    if await plugin_row.count() == 0:
                        plugin_row = page.locator("tr:has-text('Custom WP Migrator')")
                
                if await plugin_row.count() > 0:
                    deactivate_link = plugin_row.locator('a:has-text("Deactivate")')
                    if await deactivate_link.count() > 0:
                        l.info("Plugin is already active (Deactivate link present)")
                    else:
                        activate_link = plugin_row.locator('a:has-text("Activate")')
                        if await activate_link.count() > 0:
                            l.info("Found 'Activate' link, clicking it")
                            await activate_link.click()
                            await page.wait_for_load_state('networkidle', timeout=60000)
                            l.info("Plugin activation command submitted")
                            
                            # Verify activation
                            await page.goto(f"{url}/wp-admin/plugins.php", wait_until="networkidle", timeout=30000)
                            if 'Deactivate' in await plugin_row.inner_text():
                                l.info("Verified: Plugin is now active")
                            else:
                                l.warning("Could not verify activation on plugins page, continuing anyway")
                        else:
                            l.warning("Could not find either Activate or Deactivate link in plugin row")
                else:
                    l.error(f"Plugin row for '{plugin_slug}' not found on plugins page")
                    # Log the list of plugins found for debugging
                    all_plugins = await page.locator('tr[data-slug]').evaluate_all("(rows) => rows.map(r => r.getAttribute('data-slug'))")
                    l.info(f"Installed plugins: {all_plugins}")
                    return {
                        'success': False,
                        'error_code': 'PLUGIN_ROW_NOT_FOUND',
                        'message': f'Plugin row for {plugin_slug} not found'
                    }
                
                # Step 4: Get API key from plugin settings
                l.info("Step 4: Navigating to plugin settings to retrieve API key")
                await page.goto(f"{url}/wp-admin/options-general.php?page=custom-migrator-settings", wait_until="networkidle", timeout=60000)
                
                # Wait for API key field
                api_key_input = page.locator('input[name="custom_migrator_api_key"]')
                try:
                    await api_key_input.wait_for(state="visible", timeout=60000)
                except Exception:
                    l.error("API key field not found on settings page")
                    # Check if we're on the right page
                    l.info(f"Current page title: {await page.title()}")
                    return {
                        'success': False,
                        'error_code': 'API_KEY_FIELD_NOT_FOUND',
                        'message': 'API key field not found on plugin settings page'
                    }
                
                # Get API key value
                api_key = await api_key_input.get_attribute('value')
                
                # Accept either 32-char keys or the special migration-master-key (for sites that were clone targets)
                if not api_key or (len(api_key) != 32 and api_key != 'migration-master-key'):
                    l.error(f"Retrieved invalid API key: '{api_key}'")
                    return {
                        'success': False,
                        'error_code': 'INVALID_API_KEY',
                        'message': f'Failed to retrieve valid API key. Got: {api_key}'
                    }
                
                l.info(f"Successfully retrieved API key starting with: {api_key[:8]}...")
                
                # Step 4.5: Verify REST API is working
                l.info("Step 4.5: Verifying REST API endpoints are registered")
                # Navigate to a page to trigger plugins_loaded hook
                await page.goto(f"{url}/wp-admin/", wait_until="networkidle", timeout=30000)
                l.info("Triggered plugins_loaded by loading wp-admin dashboard")
                
                # Step 5: Enable import for target (skip for source)
                if role == 'target':
                    l.info("Enabling import on target")
                    # Navigate back to settings page to ensure we're on the right page
                    await page.goto(f"{url}/wp-admin/options-general.php?page=custom-migrator-settings", wait_until="networkidle", timeout=60000)
                    
                    import_checkbox = page.locator('input[name="custom_migrator_enable_import"]')
                    
                    # Check if already checked with timeout
                    try:
                        is_checked = await import_checkbox.is_checked(timeout=10000)
                        if not is_checked:
                            await import_checkbox.check(timeout=10000)
                            
                            # Save settings
                            save_button = page.locator('input[type="submit"][name="submit"]')
                            await save_button.click(timeout=10000)
                            
                            # Wait for settings saved message
                            await page.wait_for_selector('text=Settings saved', timeout=30000)
                            l.info("Import enabled and settings saved")
                        else:
                            l.info("Import already enabled")
                    except Exception as e:
                        l.warning(f"Could not enable import checkbox: {e}, continuing anyway")
                else:
                    l.info(f"Skipping import enable for {role} role")
                
                return {
                    'success': True,
                    'api_key': api_key,
                    'plugin_status': 'activated',
                    'import_enabled': True if role == 'target' else None,
                    'message': 'Browser-based setup completed successfully'
                }
                
        except PlaywrightTimeout as e:
            l.error(f"Browser automation timeout: {str(e)}")
            span.set_status(trace.Status(trace.StatusCode.ERROR, f"Browser automation timeout: {str(e)}"))
            return {
                'success': False,
                'error_code': 'BROWSER_TIMEOUT',
                'message': f'Browser automation timed out: {str(e)}'
            }
        except Exception as e:
            l.error(f"Browser-based setup failed: {str(e)}")
            import traceback as tb
            l.error(f"Traceback: {tb.format_exc()}")
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
            return {
                'success': False,
                'error_code': 'BROWSER_SETUP_ERROR',
                'message': f'Browser setup failed: {str(e)}'
            }


async def setup_target_with_browser(url: str, username: str, password: str) -> dict:
    """
    Backward-compatible wrapper for setup_wordpress_with_browser with role='target'
    """
    return await setup_wordpress_with_browser(url, username, password, role='target')
