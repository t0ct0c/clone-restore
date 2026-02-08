"""
WordPress Setup Service - FastAPI Application

Provides REST API for automated WordPress plugin installation and cloning.
"""

from loguru import logger
import time
import os
from typing import Optional, Dict
from datetime import datetime
from fastapi import FastAPI, HTTPException, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl, Field
import requests

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource

from .wp_auth import WordPressAuthenticator
from .wp_plugin import WordPressPluginInstaller
from .wp_options import WordPressOptionsFetcher
from .ec2_provisioner import EC2Provisioner
from .browser_setup import setup_target_with_browser, setup_wordpress_with_browser


def _rest_url(base_url: str, route: str, method: str = "GET") -> str:
    """Build a WordPress REST API URL.
    
    For GET: always use ?rest_route= (works regardless of permalink settings).
    For POST: use /wp-json/ (SiteGround blocks POST to ?rest_route=).
    For clone URLs (contain /clone-): always use ?rest_route= (plain permalinks).
    """
    base = base_url.rstrip("/")
    is_clone = "/clone-" in base
    if method.upper() == "GET" or is_clone:
        return f"{base}/?rest_route={route}"
    else:
        return f"{base}/wp-json{route}"


def _post_rest_api(base_url: str, route: str, headers: dict, timeout: int,
                   json_data: dict = None) -> requests.Response:
    """POST to a WordPress REST API endpoint with automatic fallback.
    
    Tries in order:
    1. POST /wp-json/ (standard, works when rewrite rules are intact)
    2. POST ?rest_route= (works on clones with plain permalinks)
    3. GET ?rest_route= (ultimate fallback - SiteGround blocks POST to ?rest_route=
       for custom routes, but GET always works; plugin routes accept ALLMETHODS)
    """
    base = base_url.rstrip("/")
    primary_url = _rest_url(base, route, "POST")
    
    resp = requests.post(primary_url, headers=headers, json=json_data, timeout=timeout)
    
    # If primary failed with 404 and we used /wp-json/, try POST ?rest_route=
    if resp.status_code == 404 and "/wp-json/" in primary_url:
        fallback_url = f"{base}/?rest_route={route}"
        logger.info(f"POST to {primary_url} got 404, trying POST fallback: {fallback_url}")
        resp = requests.post(fallback_url, headers=headers, json=json_data, timeout=timeout)
    
    # If POST ?rest_route= also failed with 404, try GET ?rest_route= (SiteGround workaround)
    if resp.status_code == 404:
        get_url = f"{base}/?rest_route={route}"
        logger.info(f"POST failed with 404, trying GET fallback: {get_url}")
        resp = requests.get(get_url, headers=headers, json=json_data, timeout=timeout)
    
    return resp


# Configure loguru
import sys

logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level> trace_id={extra[trace_id]}",
    level="INFO",
    filter=lambda record: "trace_id" in record["extra"],
)
logger.add(
    sys.stderr,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level> trace_id=0",
    level="INFO",
    filter=lambda record: "trace_id" not in record["extra"],
)

# Configure OpenTelemetry
resource = Resource.create({"service.name": "wp-setup-service"})
trace.set_tracer_provider(TracerProvider(resource=resource))
tracer = trace.get_tracer(__name__)

# Use the management host IP for tracing if not specified
# Inside Docker, localhost:4318 will fail. We default to the management host's private IP.
DEFAULT_OTEL_ENDPOINT = "http://10.0.4.2:4318/v1/traces"
otlp_exporter = OTLPSpanExporter(
    endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", DEFAULT_OTEL_ENDPOINT)
)
span_processor = SimpleSpanProcessor(otlp_exporter)
trace.get_tracer_provider().add_span_processor(span_processor)

# Initialize FastAPI
app = FastAPI(
    title="WordPress Setup Service",
    description="Automated WordPress plugin installation and cloning service",
    version="1.0.0",
)

# Instrument FastAPI with OpenTelemetry
FastAPIInstrumentor.instrument_app(app)
RequestsInstrumentor().instrument()

# Mount static files
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Configuration
PLUGIN_ZIP_PATH = os.getenv("PLUGIN_ZIP_PATH", "/app/plugin.zip")
PLUGIN_SLUG = "custom-migrator"
PLUGIN_PATH = "custom-migrator/custom-migrator.php"
TIMEOUT = int(os.getenv("TIMEOUT", "600"))


# Request/Response Models
class WordPressCredentials(BaseModel):
    url: HttpUrl
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class SetupRequest(BaseModel):
    url: HttpUrl
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    role: Optional[str] = Field("source", pattern="^(source|target)$")


class CloneRequest(BaseModel):
    source: WordPressCredentials
    target: Optional[WordPressCredentials] = None
    auto_provision: bool = Field(
        True, description="Auto-provision target if not provided"
    )
    ttl_minutes: int = Field(
        60, ge=5, le=120, description="TTL for auto-provisioned target"
    )


class ProvisionRequest(BaseModel):
    customer_id: str = Field(
        ..., min_length=1, max_length=50, pattern="^[a-zA-Z0-9-]+$"
    )
    ttl_minutes: int = Field(30, ge=5, le=120)


class ProvisionResponse(BaseModel):
    success: bool
    target_url: Optional[str] = None
    wordpress_username: Optional[str] = None
    wordpress_password: Optional[str] = None
    expires_at: Optional[str] = None
    status: Optional[str] = None
    message: str


class SetupResponse(BaseModel):
    success: bool
    api_key: Optional[str] = None
    plugin_status: str
    import_enabled: Optional[bool] = None
    message: str


class CloneResponse(BaseModel):
    success: bool
    message: str
    source_api_key: Optional[str] = None
    target_api_key: Optional[str] = None
    target_import_enabled: bool = False
    provisioned_target: Optional[Dict] = None  # Details of auto-provisioned target


class RestoreRequest(BaseModel):
    source: WordPressCredentials
    target: WordPressCredentials
    preserve_plugins: bool = Field(
        True, description="Preserve production plugin updates"
    )
    preserve_themes: bool = Field(
        False,
        description="Preserve production themes (default: false, restore from staging)",
    )


class RestoreResponse(BaseModel):
    success: bool
    message: str
    source_api_key: Optional[str] = None
    target_api_key: Optional[str] = None
    integrity: Optional[Dict] = None
    options: Optional[Dict] = None


# Helper Functions
async def setup_wordpress(
    url: str, username: str, password: str, role: str = "source"
) -> dict:
    """
    Setup WordPress site with Custom WP Migrator plugin

    Args:
        url: WordPress site URL
        username: Admin username
        password: Admin password
        role: 'source' or 'target' (determines if import should be enabled)

    Returns:
        Dict with setup results
    """
    with tracer.start_as_current_span(f"setup_wordpress_{role}") as span:
        span.set_attribute("wordpress.url", url)
        span.set_attribute("wordpress.role", role)
        trace_id = format(span.get_span_context().trace_id, "032x")
        l = logger.bind(trace_id=trace_id)

        l.info(f"Starting setup for {url} (role: {role})")

        try:
            with logger.contextualize(trace_id=trace_id):
                import traceback

                # Step 1: Authenticate
                auth = WordPressAuthenticator(str(url))
                if not auth.authenticate(username, password):
                    return {
                        "success": False,
                        "error_code": "AUTH_FAILED",
                        "message": "Invalid WordPress credentials or user is not administrator",
                    }

                # Step 2: Check if plugin already installed
                plugin_installer = WordPressPluginInstaller(auth.session, str(url))
                plugin_status = plugin_installer.check_plugin_status(PLUGIN_SLUG)

                l.info(f"Plugin status: {plugin_status}")

                # Step 3: Upload plugin if not installed
                if plugin_status == "not-installed":
                    l.info("Plugin not found, uploading...")

                    try:
                        upload_nonce = auth.get_nonce("plugin-upload")
                        if not upload_nonce:
                            l.error("Failed to get upload nonce")
                            return {
                                "success": False,
                                "error_code": "NONCE_ERROR",
                                "message": "Could not retrieve nonce for plugin upload",
                            }

                        l.info(
                            f"Got upload nonce, uploading plugin from {PLUGIN_ZIP_PATH}"
                        )
                        upload_result = plugin_installer.upload_plugin(
                            PLUGIN_ZIP_PATH, upload_nonce
                        )
                        l.info(f"Plugin upload result: {upload_result}")

                        if not upload_result:
                            l.error("Plugin upload returned False")
                            return {
                                "success": False,
                                "error_code": "PLUGIN_UPLOAD_FAILED",
                                "message": "Failed to upload plugin ZIP file",
                            }
                    except Exception as upload_error:
                        l.error(f"Exception during plugin upload: {str(upload_error)}")
                        l.error(f"Traceback: {traceback.format_exc()}")
                        return {
                            "success": False,
                            "error_code": "PLUGIN_UPLOAD_EXCEPTION",
                            "message": f"Plugin upload exception: {str(upload_error)}",
                        }

                    plugin_status = "inactive"

                # Initialize options fetcher
                options_fetcher = WordPressOptionsFetcher(auth.session, str(url))

                # Step 4: Activate plugin if not active
                if plugin_status == "inactive":
                    l.info("Activating plugin...")

                    # Get both REST nonce and activation nonce
                    rest_nonce = auth.get_rest_nonce()
                    activate_nonce = auth.get_nonce(
                        "activate-plugin", plugin_path=PLUGIN_PATH
                    )

                    if not activate_nonce:
                        return {
                            "success": False,
                            "error_code": "NONCE_ERROR",
                            "message": "Could not retrieve nonce for plugin activation",
                        }

                    activation_result = await plugin_installer.activate_plugin(
                        PLUGIN_PATH, activate_nonce, rest_nonce, username, password
                    )

                    if not activation_result[0]:  # Check if activation succeeded
                        return {
                            "success": False,
                            "error_code": "PLUGIN_ACTIVATION_FAILED",
                            "message": "Failed to activate plugin",
                        }

                    # Check if API key was returned from browser activation
                    api_key = activation_result[1]

                    if api_key:
                        l.info(
                            f"API key retrieved from browser session: {api_key[:10]}..."
                        )
                    else:
                        # Wait for activation hook to complete and API key generation
                        l.info("Waiting for plugin activation hooks to complete...")
                        time.sleep(5)

                        # Step 5: Retrieve API key via requests session
                        api_key = options_fetcher.get_migrator_api_key()

                        if not api_key:
                            return {
                                "success": False,
                                "error_code": "API_KEY_NOT_FOUND",
                                "message": "Plugin activated but API key not found",
                            }
                else:
                    # Plugin already active, retrieve API key
                    api_key = options_fetcher.get_migrator_api_key()

                    if not api_key:
                        l.warning(
                            "API key not found for active plugin, attempting deactivate/reactivate..."
                        )

                        # Get deactivation nonce
                        deactivate_nonce = auth.get_nonce(
                            "deactivate-plugin", plugin_path=PLUGIN_PATH
                        )
                        if not deactivate_nonce:
                            return {
                                "success": False,
                                "error_code": "NONCE_ERROR",
                                "message": "Could not retrieve nonce for plugin deactivation",
                            }

                        # Deactivate plugin
                        if not await plugin_installer.deactivate_plugin(
                            PLUGIN_PATH, deactivate_nonce, username, password
                        ):
                            return {
                                "success": False,
                                "error_code": "PLUGIN_DEACTIVATION_FAILED",
                                "message": "Failed to deactivate plugin for API key regeneration",
                            }

                        l.info("Plugin deactivated, now reactivating...")
                        time.sleep(2)

                        # Get activation nonce
                        rest_nonce = auth.get_rest_nonce()
                        activate_nonce = auth.get_nonce(
                            "activate-plugin", plugin_path=PLUGIN_PATH
                        )

                        if not activate_nonce:
                            return {
                                "success": False,
                                "error_code": "NONCE_ERROR",
                                "message": "Could not retrieve nonce for plugin reactivation",
                            }

                        # Reactivate plugin
                        activation_result = await plugin_installer.activate_plugin(
                            PLUGIN_PATH, activate_nonce, rest_nonce, username, password
                        )

                        if not activation_result[0]:
                            return {
                                "success": False,
                                "error_code": "PLUGIN_REACTIVATION_FAILED",
                                "message": "Failed to reactivate plugin",
                            }

                        # Check if API key was returned from browser activation
                        api_key = activation_result[1]

                        if api_key:
                            l.info(
                                f"API key retrieved from browser session after reactivation: {api_key[:10]}..."
                            )
                        else:
                            # Wait and retry API key retrieval
                            l.info(
                                "Waiting for API key generation after reactivation..."
                            )
                            time.sleep(5)
                            api_key = options_fetcher.get_migrator_api_key()

                            if not api_key:
                                return {
                                    "success": False,
                                    "error_code": "API_KEY_NOT_FOUND",
                                    "message": "Plugin reactivated but API key still not found",
                                }

                # Step 6: Enable import for target sites
                import_enabled = False
                if role == "target":
                    l.info("Enabling import for target site...")
                    import_enabled = options_fetcher.enable_import()
                    if not import_enabled:
                        l.warning("Failed to enable import, but continuing...")

                return {
                    "success": True,
                    "api_key": api_key,
                    "plugin_status": "activated",
                    "import_enabled": import_enabled if role == "target" else None,
                    "message": "Setup completed successfully",
                }

        except Exception as e:
            l.error(f"Setup failed with exception: {str(e)}")
            l.error(f"Full traceback: {traceback.format_exc()}")
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
            return {
                "success": False,
                "error_code": "SETUP_ERROR",
                "message": f"Setup exception: {str(e)}",
            }


def perform_clone(
    source_url: str,
    source_api_key: str,
    target_url: str,
    target_api_key: str,
    public_target_url: str = None,
    admin_user: str = None,
    admin_password: str = None,
) -> dict:
    """
    Perform WordPress clone operation

    Args:
        source_url: Source WordPress URL
        source_api_key: Source API key
        target_url: Target WordPress URL (direct connection)
        target_api_key: Target API key
        public_target_url: Public URL for database search-replace
        admin_user: Administrator username to create/update after import
        admin_password: Administrator password to create/update after import

    Returns:
        Dict with clone results
    """
    logger.info(
        f"Starting clone from {source_url} to {target_url} (Public: {public_target_url})"
    )

    try:
        # Step 1: Export from source
        logger.info("Exporting from source...")
        export_response = _post_rest_api(
            source_url, "/custom-migrator/v1/export",
            headers={"X-Migrator-Key": source_api_key},
            timeout=TIMEOUT,
        )

        if export_response.status_code != 200:
            return {
                "success": False,
                "error_code": "EXPORT_FAILED",
                "message": f"Export failed: {export_response.text}",
            }

        export_data = export_response.json()
        archive_url = export_data.get("download_url")

        if not archive_url:
            return {
                "success": False,
                "error_code": "EXPORT_FAILED",
                "message": "Export did not return archive URL",
            }

        logger.info(f"Export completed, archive URL: {archive_url}")

        # Step 2: Import to target
        logger.info("Importing to target...")
        import_payload = {"archive_url": archive_url}
        if public_target_url:
            import_payload["public_url"] = public_target_url

        if admin_user and admin_password:
            import_payload["admin_user"] = admin_user
            import_payload["admin_password"] = admin_password

        import_response = _post_rest_api(
            target_url, "/custom-migrator/v1/import",
            headers={
                "X-Migrator-Key": target_api_key,
                "Content-Type": "application/json",
            },
            json_data=import_payload,
            timeout=TIMEOUT,
        )

        if import_response.status_code != 200:
            return {
                "success": False,
                "error_code": "IMPORT_FAILED",
                "message": f"Import failed: {import_response.text}",
            }

        logger.info("Clone completed successfully")

        return {"success": True, "message": "Clone completed successfully"}

    except Exception as e:
        logger.error(f"Clone failed: {e}")
        return {
            "success": False,
            "error_code": "CLONE_ERROR",
            "message": f"Clone failed: {str(e)}",
        }


def perform_restore(
    source_url: str,
    source_api_key: str,
    target_url: str,
    target_api_key: str,
    preserve_plugins: bool = True,
    preserve_themes: bool = False,
    admin_user: str = None,
    admin_password: str = None,
) -> dict:
    """
    Perform WordPress restore operation with selective preservation

    Args:
        source_url: Source WordPress URL (staging/backup)
        source_api_key: Source API key
        target_url: Target WordPress URL (production)
        target_api_key: Target API key
        preserve_plugins: Keep production plugins (default: True)
        preserve_themes: Keep production themes (default: False - restore from staging)
        admin_user: Administrator username to create/update after import
        admin_password: Administrator password to create/update after import

    Returns:
        Dict with restore results including integrity check
    """
    logger.info(f"Starting restore from {source_url} to {target_url}")
    logger.info(f"Preservation: plugins={preserve_plugins}, themes={preserve_themes}")

    # Check if source is a clone (uses plain permalinks with query string format)
    is_clone_source = "/clone-" in source_url

    try:
        # Step 1: Export from source (staging/backup)
        logger.info("Exporting from source...")

        export_response = _post_rest_api(
            source_url, "/custom-migrator/v1/export",
            headers={"X-Migrator-Key": source_api_key},
            timeout=TIMEOUT,
        )

        if export_response.status_code != 200:
            error_text = export_response.text
            # Provide clearer error for DB connection failures
            if "Error establishing a database connection" in error_text:
                error_text = (
                    "Source WordPress has lost its database connection. "
                    "If the source is a clone, the MySQL database may have been lost "
                    "due to a container restart. Please create a new clone and retry."
                )
            return {
                "success": False,
                "error_code": "EXPORT_FAILED",
                "message": f"Export failed: {error_text}",
            }

        export_data = export_response.json()
        archive_url = export_data.get("download_url")

        if not archive_url:
            return {
                "success": False,
                "error_code": "EXPORT_FAILED",
                "message": "Export did not return archive URL",
            }

        logger.info(f"Export completed, archive URL: {archive_url}")

        # Step 2: Import to target with preservation options
        logger.info("Importing to target with preservation options...")
        import_payload = {
            "archive_url": archive_url,
            "preserve_plugins": preserve_plugins,
            "preserve_themes": preserve_themes,
            "public_url": target_url.rstrip("/"),
        }

        if admin_user and admin_password:
            import_payload["admin_user"] = admin_user
            import_payload["admin_password"] = admin_password

        import_response = _post_rest_api(
            target_url, "/custom-migrator/v1/import",
            headers={
                "X-Migrator-Key": target_api_key,
                "Content-Type": "application/json",
            },
            json_data=import_payload,
            timeout=TIMEOUT,
        )

        if import_response.status_code != 200:
            return {
                "success": False,
                "error_code": "IMPORT_FAILED",
                "message": f"Import failed: {import_response.text}",
            }

        import_data = import_response.json()
        logger.info("Restore completed successfully")

        # Include integrity check results
        integrity = import_data.get("integrity", {})
        if integrity.get("warnings"):
            logger.warning(f"Integrity warnings: {integrity['warnings']}")

        return {
            "success": True,
            "message": "Restore completed successfully",
            "integrity": integrity,
            "options": import_data.get("options", {}),
        }

    except Exception as e:
        logger.error(f"Restore failed: {e}")
        return {
            "success": False,
            "error_code": "RESTORE_ERROR",
            "message": f"Restore failed: {str(e)}",
        }


# API Endpoints
@app.get("/")
async def root():
    """Serve the UI"""
    static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "WordPress Clone Manager API", "docs": "/docs"}


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "version": "1.0.0"}


@app.get("/logs")
async def get_logs(lines: int = 200):
    """Get recent logs for debugging"""
    import io
    import logging

    # Return in-memory logs from the logger
    log_stream = io.StringIO()
    handler = logging.StreamHandler(log_stream)
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )

    # Get all loggers and their handlers
    loggers = [logging.getLogger(name) for name in logging.root.manager.loggerDict]
    all_logs = []

    # For now, return a simple message directing to docker logs
    return {
        "success": True,
        "message": "Use 'docker logs wp-setup-service' or check the latest clone attempt below",
        "note": "Logs are written to stdout/stderr and captured by Docker",
    }


@app.post("/setup", response_model=SetupResponse)
async def setup_endpoint(request: SetupRequest):
    """
    Setup WordPress site with Custom WP Migrator plugin
    """
    result = await setup_wordpress(
        str(request.url), request.username, request.password, request.role
    )

    if not result.get("success"):
        error_code = result.get("error_code", "UNKNOWN_ERROR")
        status_code = {
            "AUTH_FAILED": status.HTTP_401_UNAUTHORIZED,
            "NOT_ADMIN": status.HTTP_403_FORBIDDEN,
            "PLUGIN_UPLOAD_FAILED": status.HTTP_500_INTERNAL_SERVER_ERROR,
            "PLUGIN_ACTIVATION_FAILED": status.HTTP_500_INTERNAL_SERVER_ERROR,
            "API_KEY_NOT_FOUND": status.HTTP_500_INTERNAL_SERVER_ERROR,
        }.get(error_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

        raise HTTPException(
            status_code=status_code, detail=result.get("message", "Setup failed")
        )

    return SetupResponse(**result)


@app.post("/clone", response_model=CloneResponse)
async def clone_endpoint(request: CloneRequest):
    """
    Clone WordPress from source to target

    If target is not provided and auto_provision is True, an ephemeral EC2 target
    will be automatically provisioned.
    """
    provisioned_target_info = None
    target_url = None
    target_username = None
    target_password = None

    # Setup source - Use browser-based setup for better compatibility with bot protection
    source_result = await setup_wordpress_with_browser(
        str(request.source.url),
        request.source.username,
        request.source.password,
        role="source",
    )

    if not source_result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Source setup failed: {source_result.get('message')}",
        )

    # Determine target: use provided or auto-provision
    if request.target is None:
        if not request.auto_provision:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Target credentials required when auto_provision is False",
            )

        # Auto-provision EC2 target
        logger.info("Auto-provisioning EC2 target...")
        provisioner = EC2Provisioner()

        # Generate unique customer_id from timestamp
        customer_id = f"clone-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"

        provision_result = provisioner.provision_target(
            customer_id=customer_id, ttl_minutes=request.ttl_minutes
        )

        if not provision_result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Target provisioning failed: {provision_result.get('message')}",
            )

        target_url = provision_result["target_url"]  # Direct URL for setup
        public_url = provision_result.get("public_url", target_url)  # ALB URL for user
        target_username = provision_result["wordpress_username"]
        target_password = provision_result["wordpress_password"]

        provisioned_target_info = {
            "target_url": public_url,  # Show public URL to user
            "public_url": public_url,  # For URL updates after Apache reload
            "wordpress_username": target_username,
            "wordpress_password": target_password,
            "expires_at": provision_result.get("expires_at"),
            "ttl_minutes": request.ttl_minutes,
            "customer_id": customer_id,
            "instance_ip": provision_result.get("instance_ip"),  # For Apache reload
        }

        logger.info(f"Target provisioned: {public_url}")
    else:
        # Use provided target credentials
        target_url = str(request.target.url)
        target_username = request.target.username
        target_password = request.target.password

    # Setup target: use browser or direct if already provisioned
    if request.target is None:
        # Auto-provisioned target
        if provision_result.get("api_key"):
            logger.info("Using direct API key from provisioner, skipping browser setup")
            target_result = {
                "success": True,
                "api_key": provision_result["api_key"],
                "import_enabled": True,
                "message": "Direct setup successful",
            }
        else:
            logger.info("Direct API key missing, falling back to browser-based setup")
            target_result = await setup_target_with_browser(
                target_url, target_username, target_password
            )
    else:
        # User-provided target - use HTTP-based setup
        logger.info("Using HTTP-based setup for user-provided target")
        target_result = await setup_wordpress(
            target_url, target_username, target_password, role="target"
        )

    if not target_result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Target setup failed: {target_result.get('message')}",
        )

    # Perform clone
    clone_result = perform_clone(
        str(request.source.url),
        source_result["api_key"],
        target_url,
        target_result["api_key"],
        public_target_url=public_url,
        admin_user=target_username,
        admin_password=target_password,
    )

    if not clone_result.get("success"):
        logger.error(f"Clone failed: {clone_result.get('message')}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=clone_result.get("message", "Clone failed"),
        )

    # Re-activate the migrator plugin on the clone and set a known API key
    # (import process deactivates plugin and clone inherits source's API key)
    if provisioned_target_info and provisioned_target_info.get("instance_ip"):
        instance_ip = provisioned_target_info["instance_ip"]
        customer_id = provisioned_target_info["customer_id"]
        provisioner = EC2Provisioner()

        logger.info("Re-activating custom-migrator plugin on clone container...")
        provisioner.activate_plugin_in_container(instance_ip, customer_id)

        # Set API key to migration-master-key so restore endpoint can use a known key
        logger.info("Setting clone API key to migration-master-key...")
        provisioner.run_wp_cli_in_container(
            instance_ip, customer_id,
            "option update custom_migrator_api_key migration-master-key"
        )
        # Also enable import on the clone
        provisioner.run_wp_cli_in_container(
            instance_ip, customer_id,
            "option update custom_migrator_allow_import 1"
        )

    # Reload Apache in auto-provisioned containers to reset database connections
    # This is required because SQLite connections become stale after import
    if provisioned_target_info and provisioned_target_info.get("instance_ip"):
        logger.info(
            "Reloading Apache in target container to reset database connections..."
        )
        provisioner = EC2Provisioner()
        provisioner.reload_apache_in_container(
            provisioned_target_info["instance_ip"],
            provisioned_target_info["customer_id"],
        )

        # Force-update WordPress URLs after Apache reload
        # WordPress auto-detects Host header and may revert URLs to localhost
        logger.info("Force-updating WordPress URLs to prevent auto-correction...")
        provisioner.update_wordpress_urls(
            provisioned_target_info["instance_ip"],
            provisioned_target_info["customer_id"],
            provisioned_target_info["public_url"],
        )

    logger.info("Clone process finished successfully")
    return CloneResponse(
        success=True,
        message="Clone completed successfully",
        source_api_key=source_result["api_key"],
        target_api_key=target_result["api_key"],
        target_import_enabled=target_result.get("import_enabled", False),
        provisioned_target=provisioned_target_info,
    )


@app.post("/restore", response_model=RestoreResponse)
async def restore_endpoint(request: RestoreRequest):
    """
    Restore WordPress from staging/backup to production with selective preservation.

    By default:
    - Preserves production plugins (to avoid downgrading updated plugins)
    - Restores themes from staging (to deploy design changes)
    - Restores database and uploads from staging
    """
    logger.info(f"Restore requested: {request.source.url} -> {request.target.url}")
    logger.info(
        f"Options: preserve_plugins={request.preserve_plugins}, preserve_themes={request.preserve_themes}"
    )

    source_url = str(request.source.url)

    # Check if source is a clone (uses plain permalinks with query string format)
    is_clone_source = "/clone-" in source_url

    # Skip browser automation for clones - auto-detect the API key
    # Clones inherit the source site's API key, which may not be migration-master-key
    if is_clone_source:
        logger.info("Source is a clone, auto-detecting API key...")
        source_api_key = None
        candidate_keys = ["migration-master-key"]

        # Pre-check: verify clone is healthy and find working API key
        logger.info("Verifying clone source is healthy...")
        health_url = (
            f"{source_url.rstrip('/')}/?rest_route=/custom-migrator/v1/status"
        )

        for candidate_key in candidate_keys:
            try:
                health_resp = requests.get(
                    health_url, headers={"X-Migrator-Key": candidate_key}, timeout=15
                )
                if health_resp.status_code == 200:
                    source_api_key = candidate_key
                    logger.info(f"Clone API key found: {candidate_key[:10]}...")
                    break
                elif health_resp.status_code == 403:
                    logger.info(f"Key '{candidate_key[:10]}...' rejected (403), trying next...")
                else:
                    resp_text = health_resp.text
                    if "Error establishing a database connection" in resp_text:
                        raise HTTPException(
                            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=(
                                f"Source clone database is unreachable. "
                                f"The MySQL database for this clone may have been lost due to a MySQL container restart. "
                                f"Please create a new clone using the /clone endpoint and retry with the new clone URL."
                            ),
                        )
                    logger.warning(
                        f"Clone health check returned {health_resp.status_code} with key '{candidate_key[:10]}...': {resp_text[:200]}"
                    )
            except requests.RequestException as e:
                logger.warning(f"Clone health check failed: {e}")
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"Source clone is unreachable: {str(e)}. The clone may have expired or been cleaned up.",
                )

        if source_api_key is None:
            # None of the candidate keys worked - fall back to browser automation
            # to retrieve the actual API key from the clone's settings page
            logger.info("No candidate key worked for clone, falling back to browser automation...")
            source_result = await setup_wordpress_with_browser(
                source_url, request.source.username, request.source.password, role="source"
            )
            if not source_result.get("success"):
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Source clone setup failed: {source_result.get('message')}",
                )
            source_api_key = source_result["api_key"]
            logger.info(f"Got clone API key via browser: {source_api_key[:10]}...")
    else:
        # Use browser automation for regular WordPress sites
        logger.info(f"Setting up source (regular site)...")
        source_result = await setup_wordpress_with_browser(
            source_url, request.source.username, request.source.password, role="source"
        )

        if not source_result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Source setup failed: {source_result.get('message')}",
            )
        source_api_key = source_result["api_key"]

    # Setup target (production) - ALWAYS use browser automation.
    # SiteGround caches REST API responses and the plugin becomes inactive after
    # every restore (DB replacement). Browser automation reliably uploads a fresh
    # plugin and activates it every time.
    target_url = str(request.target.url).rstrip("/")
    logger.info("Setting up target via browser automation (ensures fresh plugin)...")
    target_result = await setup_wordpress_with_browser(
        target_url,
        request.target.username,
        request.target.password,
        role="target",
    )

    if not target_result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Target setup failed: {target_result.get('message')}",
        )

    # Perform restore with preservation options
    restore_result = perform_restore(
        source_url,
        source_api_key,
        str(request.target.url),
        target_result["api_key"],
        preserve_plugins=request.preserve_plugins,
        preserve_themes=request.preserve_themes,
        admin_user=request.target.username,
        admin_password=request.target.password,
    )

    if not restore_result.get("success"):
        logger.error(f"Restore failed: {restore_result.get('message')}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=restore_result.get("message", "Restore failed"),
        )

    logger.info("Restore process finished successfully")
    return RestoreResponse(
        success=True,
        message="Restore completed successfully",
        source_api_key=source_api_key,
        target_api_key=target_result["api_key"],
        integrity=restore_result.get("integrity"),
        options=restore_result.get("options"),
    )


@app.post("/provision", response_model=ProvisionResponse)
async def provision_endpoint(request: ProvisionRequest):
    """
    Provision ephemeral WordPress target on AWS EC2
    """
    provisioner = EC2Provisioner()
    result = provisioner.provision_target(
        customer_id=request.customer_id, ttl_minutes=request.ttl_minutes
    )

    if not result.get("success"):
        error_code = result.get("error_code", "UNKNOWN_ERROR")
        status_code = {
            "NO_CAPACITY": status.HTTP_503_SERVICE_UNAVAILABLE,
            "PORT_EXHAUSTED": status.HTTP_503_SERVICE_UNAVAILABLE,
            "DUPLICATE_TARGET": status.HTTP_409_CONFLICT,
        }.get(error_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

        raise HTTPException(
            status_code=status_code, detail=result.get("message", "Provisioning failed")
        )

    return ProvisionResponse(**result)
