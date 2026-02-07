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
DEFAULT_ZIP_PATH = os.getenv("PLUGIN_ZIP_PATH", "/app/plugin.zip")
if not os.path.exists(DEFAULT_ZIP_PATH):
    if os.path.exists("/app/custom-migrator.zip"):
        DEFAULT_ZIP_PATH = "/app/custom-migrator.zip"
    elif os.path.exists("./plugin.zip"):
        DEFAULT_ZIP_PATH = "./plugin.zip"

PLUGIN_ZIP_PATH = DEFAULT_ZIP_PATH


async def setup_wordpress_with_browser(
    url: str, username: str, password: str, role: str = "target"
) -> dict:
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
        trace_id = format(span.get_span_context().trace_id, "032x")
        l = logger.bind(trace_id=trace_id)

        l.info(f"Starting browser-based setup for {url} (role: {role})")
        # Always normalize URL by removing trailing slash
        # We'll add paths with / prefix, so trailing slash causes double //
        url = url.rstrip("/")

        try:
            async with AsyncCamoufox(headless=True) as browser:
                # Create a context with realistic fingerprints
                context = await browser.new_context(
                    viewport={"width": 1280, "height": 800}, accept_downloads=True
                )

                # Set global timeout for all actions
                context.set_default_timeout(240000)  # 240s
                context.set_default_navigation_timeout(240000)  # 240s

                page = await context.new_page()

                # Step 1: Login
                l.info(f"Step 1: Navigating to login page {url}/wp-login.php")
                try:
                    await page.goto(
                        f"{url}/wp-login.php", wait_until="networkidle", timeout=120000
                    )
                except Exception as e:
                    l.error(f"Failed to load login page: {e}")
                    # Log current page content for debugging
                    content = await page.content()
                    l.debug(
                        f"Current page content (first 1000 chars): {content[:1000]}"
                    )
                    raise

                # Check for bot block or specific challenge
                content = await page.content()
                if "Cloudflare" in content or "Attention Required" in content:
                    l.warning(
                        "Detected Cloudflare or bot challenge on login page - trying to wait it out"
                    )
                    await asyncio.sleep(5)

                # Fill login form
                l.info("Filling login credentials")
                try:
                    await page.wait_for_selector(
                        'input[name="log"]', state="visible", timeout=60000
                    )
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
                    await page.wait_for_selector(
                        "#wpadminbar, .login-action-login, #login_error", timeout=60000
                    )
                except Exception:
                    l.warning(
                        "Timed out waiting for admin bar or login error after submit, checking current URL"
                    )

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
                        l.info(
                            "Detected reauth or loggedout, attempting force navigation to wp-admin"
                        )
                        await page.goto(
                            f"{url}/wp-admin/", wait_until="networkidle", timeout=60000
                        )

                # Check for both /wp-admin/ and /wp-admin.php (new clones use .php)
                if "/wp-admin" not in page.url and "wp-admin.php" not in page.url:
                    l.error(
                        f"Failed to reach admin area after login. Current URL: {page.url}"
                    )
                    # Log snippets of content to see if we're stuck on a 'Verify you are human' page
                    content = await page.content()
                    if "Verify you are human" in content or "Cloudflare" in content:
                        return {
                            "success": False,
                            "error_code": "BOT_BLOCKED",
                            "message": "Site is blocking automation via Cloudflare/Bot protection. Try again later or use camoufox.",
                        }
                    return {
                        "success": False,
                        "error_code": "LOGIN_FAILED",
                        "message": f"Failed to reach admin area. Site might be blocking automated login. URL: {page.url}",
                    }

                l.info("Successfully reached admin area")

                # Step 2: Check if plugin is already active by trying settings page first
                # SiteGround's SG Security forces reauth on plugins.php, so we avoid it
                # Instead: check settings page → if plugin active, get key → done
                #          if not active, go to plugin-install.php to upload (not plugins.php)
                l.info("Step 2: Checking if plugin is already active via settings page")
                plugin_slug = "custom-migrator"
                plugin_already_active = False

                await page.goto(
                    f"{url}/wp-admin/options-general.php?page=custom-migrator-settings",
                    wait_until="networkidle",
                    timeout=60000,
                )
                l.info(f"Settings page URL: {page.url}")

                # Check if we got redirected to login (reauth)
                if "wp-login.php" in page.url:
                    l.warning(f"Redirected to login from settings page: {page.url}")
                    # Re-login - the redirect_to should bring us back to settings
                    await page.wait_for_selector(
                        'input[name="log"]', state="visible", timeout=30000
                    )
                    await page.fill('input[name="log"]', username)
                    await page.fill('input[name="pwd"]', password)
                    await page.click('input[name="wp-submit"]')
                    await asyncio.sleep(5)
                    l.info(f"After re-login from settings redirect: {page.url}")

                # Check if the settings page has the API key field (plugin is active)
                api_key_input = page.locator('input[name="custom_migrator_api_key"]')
                try:
                    await api_key_input.wait_for(state="visible", timeout=10000)
                    plugin_already_active = True
                    l.info("Plugin is already active - found API key field on settings page")
                except Exception:
                    l.info("Plugin settings page not found - plugin needs to be uploaded")

                if plugin_already_active:
                    # Plugin is active, get the API key directly
                    api_key = await api_key_input.get_attribute("value")
                    if api_key and (len(api_key) == 32 or api_key == "migration-master-key"):
                        l.info(f"Retrieved API key from settings: {api_key[:8]}...")

                        # Enable import if target role
                        if role == "target":
                            l.info("Enabling import on target")
                            import_checkbox = page.locator(
                                'input[name="custom_migrator_allow_import"]'
                            )
                            try:
                                if await import_checkbox.count() > 0:
                                    is_checked = await import_checkbox.is_checked(timeout=5000)
                                    if not is_checked:
                                        await import_checkbox.check(timeout=5000)
                                        save_button = page.locator(
                                            'input[type="submit"][name="submit"]'
                                        )
                                        await save_button.click(timeout=10000)
                                        await page.wait_for_load_state("networkidle", timeout=30000)
                                        l.info("Import enabled and settings saved")
                                    else:
                                        l.info("Import already enabled")
                            except Exception as e:
                                l.warning(f"Could not enable import: {e}, continuing anyway")

                        return {
                            "success": True,
                            "api_key": api_key,
                            "plugin_status": "active",
                            "import_enabled": True if role == "target" else None,
                            "message": "Plugin already active, retrieved API key from settings",
                        }
                    else:
                        l.warning(f"API key field found but value invalid: '{api_key}', will re-upload plugin")
                        plugin_already_active = False

                # Plugin not active - need to upload it
                # Go to plugin-install.php?tab=upload directly (avoids plugins.php reauth)
                l.info("Step 2b: Plugin not active, navigating to plugin upload page")
                plugins_page_loaded = False

                for plugins_attempt in range(3):
                    try:
                        await page.goto(
                            f"{url}/wp-admin/plugin-install.php?tab=upload",
                            wait_until="networkidle",
                            timeout=60000,
                        )
                        current_url = page.url
                        l.info(f"Upload page attempt {plugins_attempt + 1}/3 - URL: {current_url}")

                        if "wp-login.php" in current_url:
                            l.warning("Redirected to login from upload page, re-logging in...")
                            await page.wait_for_selector(
                                'input[name="log"]', state="visible", timeout=30000
                            )
                            await page.fill('input[name="log"]', username)
                            await page.fill('input[name="pwd"]', password)
                            await page.click('input[name="wp-submit"]')
                            await asyncio.sleep(5)
                            l.info(f"After re-login: {page.url}")
                            if "wp-login.php" in page.url:
                                if plugins_attempt < 2:
                                    await asyncio.sleep(3)
                                continue

                        # Check if we're on the upload page
                        upload_form = page.locator('input[type="file"][name="pluginzip"]')
                        await upload_form.wait_for(state="visible", timeout=30000)
                        plugins_page_loaded = True
                        l.info("Plugin upload page loaded successfully")
                        break
                    except Exception as e:
                        l.warning(
                            f"Upload page attempt {plugins_attempt + 1}/3 failed: {e}"
                        )
                        if plugins_attempt < 2:
                            l.info("Retrying after short delay...")
                            await asyncio.sleep(3)

                if not plugins_page_loaded:
                    l.error("Could not load plugin upload page after 3 attempts")
                    return {
                        "success": False,
                        "error_code": "UPLOAD_PAGE_TIMEOUT",
                        "message": "Could not access plugin upload page. "
                        "The hosting provider may be blocking admin page access.",
                    }

                # We're on the upload page - upload the plugin zip
                l.info(f"Uploading plugin ZIP from path: {PLUGIN_ZIP_PATH}")

                # Check if the "Upload Plugin" button needs to be clicked first
                upload_toggle = page.locator(".upload-view-toggle")
                if (
                    await upload_toggle.count() > 0
                    and await upload_toggle.is_visible()
                ):
                    l.info("Clicking 'Upload Plugin' toggle")
                    await upload_toggle.click()

                file_input = page.locator('input[type="file"][name="pluginzip"]')
                await file_input.wait_for(state="attached", timeout=60000)

                l.info("Attaching plugin zip file")
                await file_input.set_input_files(PLUGIN_ZIP_PATH)

                l.info("Clicking 'Install Now' and waiting for completion")

                try:
                    # Monitor outgoing requests to see if the upload actually starts
                    upload_started = False

                    async def log_request(request):
                        nonlocal upload_started
                        if request.method == "POST" and "update.php" in request.url:
                            l.info(
                                f"Detected outgoing upload request: {request.url}"
                            )
                            upload_started = True

                    page.on("request", log_request)

                    # Try multiple common selectors for the install button
                    submit_button = page.locator(
                        'input[type="submit"][name="install-plugin-submit"], #install-plugin-submit, input[value="Install Now"]'
                    )

                    # Wait for the button to be present
                    await submit_button.wait_for(state="attached", timeout=60000)

                    l.info("Button found, clicking 'Install Now'")

                    try:
                        await submit_button.click(
                            delay=100, force=True, timeout=30000
                        )
                    except Exception as click_err:
                        l.warning(
                            f"Regular click failed: {click_err}. Trying JavaScript click fallback..."
                        )
                        await page.evaluate(
                            "(sel) => { const el = document.querySelector(sel); if(el) el.click(); }",
                            'input[type="submit"][name="install-plugin-submit"], #install-plugin-submit, input[value="Install Now"]',
                        )

                    # Wait a few seconds to see if it starts navigating
                    await asyncio.sleep(5)

                    if not upload_started:
                        l.warning(
                            "Click didn't seem to trigger an upload request. Attempting form submission via JavaScript..."
                        )
                        try:
                            await page.evaluate(
                                '() => { const f = document.querySelector("form#plugin-upload-form, form.wp-upload-form"); if(f) f.submit(); }'
                            )
                        except Exception as eval_err:
                            l.error(
                                f"JavaScript form submission failed: {eval_err}"
                            )

                    l.info("Waiting for result (navigation or error message)...")

                    # Check progress every 15 seconds
                    for attempt in range(1, 13):  # 12 * 15s = 180s
                        try:
                            await page.wait_for_function(
                                "() => window.location.href.includes('update.php') || document.querySelector('.error, .notice-error, .updated, .notice-success, #wp-admin-installer-error')",
                                timeout=15000,
                            )
                            break
                        except Exception:
                            l.info(
                                f"Wait attempt {attempt}/12: Still on {page.url}. Page title: {await page.title()}"
                            )
                            if attempt % 2 == 0:
                                body_text = await page.inner_text("body")
                                l.debug(
                                    f"Current page text snippet: {body_text[:500].replace(chr(10), ' ')}"
                                )

                    l.info(f"Final URL after upload attempt: {page.url}")
                    page.remove_listener("request", log_request)

                except Exception as e:
                    l.error(f"Upload POST request failed or timed out: {e}")
                    l.info(f"Current URL after timeout: {page.url}")
                    content = await page.content()
                    if "error" in content.lower() or "forbidden" in content.lower():
                        l.error("Page content contains error indicators")
                    raise

                # Check for success message
                l.info("Checking for success or error messages...")
                try:
                    await page.wait_for_selector(
                        "text=Plugin installed successfully", timeout=30000
                    )
                    l.info("Success message 'Plugin installed successfully' found")
                except Exception as e:
                    l.warning(
                        f"Did not see 'Plugin installed successfully' message: {e}"
                    )
                    error_locator = page.locator(".error, .notice-error")
                    if await error_locator.count() > 0:
                        error_text = await error_locator.first.inner_text()
                        l.error(f"Upload error detected: {error_text}")
                        raise Exception(f"Plugin upload failed: {error_text}")
                    if "plugin-install.php?tab=upload" not in page.url:
                        l.info(
                            f"URL changed to {page.url}, assuming upload succeeded"
                        )

                l.info(f"Upload flow complete, current URL: {page.url}")

                # Step 3: Activate plugin directly from the upload success page
                # AVOID plugins.php - SiteGround's SG Security forces reauth on it
                l.info("Step 3: Activating plugin from upload success page")
                activate_direct = page.locator('a:has-text("Activate Plugin")')
                if await activate_direct.count() > 0:
                    l.info(
                        "Found 'Activate Plugin' link on success page, clicking it"
                    )
                    try:
                        await activate_direct.click()
                        await page.wait_for_load_state("networkidle", timeout=60000)
                        l.info(f"Activation click done, current URL: {page.url}")
                    except Exception as act_err:
                        l.warning(f"Activation click failed: {act_err}")
                else:
                    l.warning(
                        "No 'Activate Plugin' link found on success page. "
                        "Plugin may already be active or activation link has different text."
                    )
                    page_text = await page.inner_text("body")
                    if "activated" in page_text.lower():
                        l.info("Page indicates plugin was already activated")

                # Step 4: Get API key from plugin settings
                l.info("Step 4: Navigating to plugin settings to retrieve API key")
                await page.goto(
                    f"{url}/wp-admin/options-general.php?page=custom-migrator-settings",
                    wait_until="networkidle",
                    timeout=60000,
                )
                l.info(f"Settings page URL after navigation: {page.url}")

                # Handle reauth redirect
                if "wp-login.php" in page.url:
                    l.warning("Redirected to login from settings page, re-logging in...")
                    await page.wait_for_selector(
                        'input[name="log"]', state="visible", timeout=30000
                    )
                    await page.fill('input[name="log"]', username)
                    await page.fill('input[name="pwd"]', password)
                    await page.click('input[name="wp-submit"]')
                    await asyncio.sleep(5)
                    l.info(f"After re-login: {page.url}")

                # Wait for API key field
                api_key_input = page.locator('input[name="custom_migrator_api_key"]')
                try:
                    await api_key_input.wait_for(state="visible", timeout=60000)
                except Exception:
                    l.error("API key field not found on settings page")
                    l.info(f"Current URL: {page.url}, title: {await page.title()}")
                    return {
                        "success": False,
                        "error_code": "API_KEY_FIELD_NOT_FOUND",
                        "message": "API key field not found on plugin settings page",
                    }

                # Get API key value
                api_key = await api_key_input.get_attribute("value")

                # Accept either 32-char keys or the special migration-master-key (for sites that were clone targets)
                if not api_key or (
                    len(api_key) != 32 and api_key != "migration-master-key"
                ):
                    l.error(f"Retrieved invalid API key: '{api_key}'")
                    return {
                        "success": False,
                        "error_code": "INVALID_API_KEY",
                        "message": f"Failed to retrieve valid API key. Got: {api_key}",
                    }

                l.info(
                    f"Successfully retrieved API key starting with: {api_key[:8]}..."
                )

                # Step 4.5: Verify REST API is working
                l.info("Step 4.5: Verifying REST API endpoints are registered")
                # Navigate to a page to trigger plugins_loaded hook
                await page.goto(
                    f"{url}/wp-admin/", wait_until="networkidle", timeout=30000
                )
                l.info("Triggered plugins_loaded by loading wp-admin dashboard")

                # Step 5: Enable import for target (skip for source)
                if role == "target":
                    l.info("Enabling import on target")
                    # Navigate back to settings page to ensure we're on the right page
                    await page.goto(
                        f"{url}/wp-admin/options-general.php?page=custom-migrator-settings",
                        wait_until="networkidle",
                        timeout=60000,
                    )

                    import_checkbox = page.locator(
                        'input[name="custom_migrator_allow_import"]'
                    )

                    # Check if already checked with timeout
                    try:
                        is_checked = await import_checkbox.is_checked(timeout=10000)
                        if not is_checked:
                            await import_checkbox.check(timeout=10000)

                            # Save settings
                            save_button = page.locator(
                                'input[type="submit"][name="submit"]'
                            )
                            await save_button.click(timeout=10000)

                            # Wait for settings saved message
                            await page.wait_for_selector(
                                "text=Settings saved", timeout=30000
                            )
                            l.info("Import enabled and settings saved")
                        else:
                            l.info("Import already enabled")
                    except Exception as e:
                        l.warning(
                            f"Could not enable import checkbox: {e}, continuing anyway"
                        )
                else:
                    l.info(f"Skipping import enable for {role} role")

                return {
                    "success": True,
                    "api_key": api_key,
                    "plugin_status": "activated",
                    "import_enabled": True if role == "target" else None,
                    "message": "Browser-based setup completed successfully",
                }

        except PlaywrightTimeout as e:
            l.error(f"Browser automation timeout: {str(e)}")
            span.set_status(
                trace.Status(
                    trace.StatusCode.ERROR, f"Browser automation timeout: {str(e)}"
                )
            )
            return {
                "success": False,
                "error_code": "BROWSER_TIMEOUT",
                "message": f"Browser automation timed out: {str(e)}",
            }
        except Exception as e:
            l.error(f"Browser-based setup failed: {str(e)}")
            import traceback as tb

            l.error(f"Traceback: {tb.format_exc()}")
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
            return {
                "success": False,
                "error_code": "BROWSER_SETUP_ERROR",
                "message": f"Browser setup failed: {str(e)}",
            }


async def setup_target_with_browser(url: str, username: str, password: str) -> dict:
    """
    Backward-compatible wrapper for setup_wordpress_with_browser with role='target'
    """
    return await setup_wordpress_with_browser(url, username, password, role="target")
