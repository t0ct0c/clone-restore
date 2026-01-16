"""
WordPress Setup Service - FastAPI Application

Provides REST API for automated WordPress plugin installation and cloning.
"""

import logging
import time
import os
from typing import Optional, Dict
from datetime import datetime
from fastapi import FastAPI, HTTPException, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl, Field
import requests

from .wp_auth import WordPressAuthenticator
from .wp_plugin import WordPressPluginInstaller
from .wp_options import WordPressOptionsFetcher
from .ec2_provisioner import EC2Provisioner
from .browser_setup import setup_target_with_browser


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI
app = FastAPI(
    title="WordPress Setup Service",
    description="Automated WordPress plugin installation and cloning service",
    version="1.0.0"
)

# Mount static files
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static')
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Configuration
PLUGIN_ZIP_PATH = os.getenv('PLUGIN_ZIP_PATH', '/app/plugin.zip')
PLUGIN_SLUG = 'custom-migrator'
PLUGIN_PATH = 'custom-migrator/custom-migrator.php'
TIMEOUT = int(os.getenv('TIMEOUT', '600'))


# Request/Response Models
class WordPressCredentials(BaseModel):
    url: HttpUrl
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class SetupRequest(BaseModel):
    url: HttpUrl
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    role: Optional[str] = Field('source', pattern='^(source|target)$')


class CloneRequest(BaseModel):
    source: WordPressCredentials
    target: Optional[WordPressCredentials] = None
    auto_provision: bool = Field(True, description="Auto-provision target if not provided")
    ttl_minutes: int = Field(60, ge=5, le=120, description="TTL for auto-provisioned target")


class ProvisionRequest(BaseModel):
    customer_id: str = Field(..., min_length=1, max_length=50, pattern='^[a-zA-Z0-9-]+$')
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


# Helper Functions
async def setup_wordpress(url: str, username: str, password: str, role: str = 'source') -> dict:
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
    logger.info(f"Starting setup for {url} (role: {role})")
    
    try:
        import traceback
        # Step 1: Authenticate
        auth = WordPressAuthenticator(str(url))
        if not auth.authenticate(username, password):
            return {
                'success': False,
                'error_code': 'AUTH_FAILED',
                'message': 'Invalid WordPress credentials or user is not administrator'
            }
        
        # Step 2: Check if plugin already installed
        plugin_installer = WordPressPluginInstaller(auth.session, str(url))
        plugin_status = plugin_installer.check_plugin_status(PLUGIN_SLUG)
        
        logger.info(f"Plugin status: {plugin_status}")
        
        # Step 3: Upload plugin if not installed
        if plugin_status == 'not-installed':
            logger.info("Plugin not found, uploading...")
            
            try:
                upload_nonce = auth.get_nonce('plugin-upload')
                if not upload_nonce:
                    logger.error("Failed to get upload nonce")
                    return {
                        'success': False,
                        'error_code': 'NONCE_ERROR',
                        'message': 'Could not retrieve nonce for plugin upload'
                    }
                
                logger.info(f"Got upload nonce, uploading plugin from {PLUGIN_ZIP_PATH}")
                upload_result = plugin_installer.upload_plugin(PLUGIN_ZIP_PATH, upload_nonce)
                logger.info(f"Plugin upload result: {upload_result}")
                
                if not upload_result:
                    logger.error("Plugin upload returned False")
                    return {
                        'success': False,
                        'error_code': 'PLUGIN_UPLOAD_FAILED',
                        'message': 'Failed to upload plugin ZIP file'
                    }
            except Exception as upload_error:
                logger.error(f"Exception during plugin upload: {str(upload_error)}")
                logger.error(f"Traceback: {traceback.format_exc()}")
                return {
                    'success': False,
                    'error_code': 'PLUGIN_UPLOAD_EXCEPTION',
                    'message': f'Plugin upload exception: {str(upload_error)}'
                }
            
            plugin_status = 'inactive'
        
        # Initialize options fetcher
        options_fetcher = WordPressOptionsFetcher(auth.session, str(url))
        
        # Step 4: Activate plugin if not active
        if plugin_status == 'inactive':
            logger.info("Activating plugin...")
            
            # Get both REST nonce and activation nonce
            rest_nonce = auth.get_rest_nonce()
            activate_nonce = auth.get_nonce('activate-plugin', plugin_path=PLUGIN_PATH)
            
            if not activate_nonce:
                return {
                    'success': False,
                    'error_code': 'NONCE_ERROR',
                    'message': 'Could not retrieve nonce for plugin activation'
                }
            
            activation_result = await plugin_installer.activate_plugin(PLUGIN_PATH, activate_nonce, rest_nonce, username, password)
            
            if not activation_result[0]:  # Check if activation succeeded
                return {
                    'success': False,
                    'error_code': 'PLUGIN_ACTIVATION_FAILED',
                    'message': 'Failed to activate plugin'
                }
            
            # Check if API key was returned from browser activation
            api_key = activation_result[1]
            
            if api_key:
                logger.info(f"API key retrieved from browser session: {api_key[:10]}...")
            else:
                # Wait for activation hook to complete and API key generation
                logger.info("Waiting for plugin activation hooks to complete...")
                time.sleep(5)
                
                # Step 5: Retrieve API key via requests session
                api_key = options_fetcher.get_migrator_api_key()
                
                if not api_key:
                    return {
                        'success': False,
                        'error_code': 'API_KEY_NOT_FOUND',
                        'message': 'Plugin activated but API key not found'
                    }
        else:
            # Plugin already active, retrieve API key
            api_key = options_fetcher.get_migrator_api_key()
            
            if not api_key:
                logger.warning("API key not found for active plugin, attempting deactivate/reactivate...")
                
                # Get deactivation nonce
                deactivate_nonce = auth.get_nonce('deactivate-plugin', plugin_path=PLUGIN_PATH)
                if not deactivate_nonce:
                    return {
                        'success': False,
                        'error_code': 'NONCE_ERROR',
                        'message': 'Could not retrieve nonce for plugin deactivation'
                    }
                
                # Deactivate plugin
                if not await plugin_installer.deactivate_plugin(PLUGIN_PATH, deactivate_nonce, username, password):
                    return {
                        'success': False,
                        'error_code': 'PLUGIN_DEACTIVATION_FAILED',
                        'message': 'Failed to deactivate plugin for API key regeneration'
                    }
                
                logger.info("Plugin deactivated, now reactivating...")
                time.sleep(2)
                
                # Get activation nonce
                rest_nonce = auth.get_rest_nonce()
                activate_nonce = auth.get_nonce('activate-plugin', plugin_path=PLUGIN_PATH)
                
                if not activate_nonce:
                    return {
                        'success': False,
                        'error_code': 'NONCE_ERROR',
                        'message': 'Could not retrieve nonce for plugin reactivation'
                    }
                
                # Reactivate plugin
                activation_result = await plugin_installer.activate_plugin(PLUGIN_PATH, activate_nonce, rest_nonce, username, password)
                
                if not activation_result[0]:
                    return {
                        'success': False,
                        'error_code': 'PLUGIN_REACTIVATION_FAILED',
                        'message': 'Failed to reactivate plugin'
                    }
                
                # Check if API key was returned from browser activation
                api_key = activation_result[1]
                
                if api_key:
                    logger.info(f"API key retrieved from browser session after reactivation: {api_key[:10]}...")
                else:
                    # Wait and retry API key retrieval
                    logger.info("Waiting for API key generation after reactivation...")
                    time.sleep(5)
                    api_key = options_fetcher.get_migrator_api_key()
                    
                    if not api_key:
                        return {
                            'success': False,
                            'error_code': 'API_KEY_NOT_FOUND',
                            'message': 'Plugin reactivated but API key still not found'
                        }
        
        # Step 6: Enable import for target sites
        import_enabled = False
        if role == 'target':
            logger.info("Enabling import for target site...")
            import_enabled = options_fetcher.enable_import()
            if not import_enabled:
                logger.warning("Failed to enable import, but continuing...")
        
        return {
            'success': True,
            'api_key': api_key,
            'plugin_status': 'activated',
            'import_enabled': import_enabled if role == 'target' else None,
            'message': 'Setup completed successfully'
        }
        
    except Exception as e:
        logger.error(f"Setup failed with exception: {str(e)}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return {
            'success': False,
            'error_code': 'SETUP_ERROR',
            'message': f'Setup exception: {str(e)}'
        }


def perform_clone(source_url: str, source_api_key: str, target_url: str, target_api_key: str) -> dict:
    """
    Perform WordPress clone operation
    
    Args:
        source_url: Source WordPress URL
        source_api_key: Source API key
        target_url: Target WordPress URL
        target_api_key: Target API key
    
    Returns:
        Dict with clone results
    """
    logger.info(f"Starting clone from {source_url} to {target_url}")
    
    try:
        # Step 1: Export from source
        logger.info("Exporting from source...")
        export_response = requests.post(
            f"{source_url}/wp-json/custom-migrator/v1/export",
            headers={'X-Migrator-Key': source_api_key},
            timeout=TIMEOUT
        )
        
        if export_response.status_code != 200:
            return {
                'success': False,
                'error_code': 'EXPORT_FAILED',
                'message': f'Export failed: {export_response.text}'
            }
        
        export_data = export_response.json()
        archive_url = export_data.get('download_url')
        
        if not archive_url:
            return {
                'success': False,
                'error_code': 'EXPORT_FAILED',
                'message': 'Export did not return archive URL'
            }
        
        logger.info(f"Export completed, archive URL: {archive_url}")
        
        # Step 2: Import to target
        logger.info("Importing to target...")
        import_response = requests.post(
            f"{target_url}/wp-json/custom-migrator/v1/import",
            headers={
                'X-Migrator-Key': target_api_key,
                'Content-Type': 'application/json'
            },
            json={'archive_url': archive_url},
            timeout=TIMEOUT
        )
        
        if import_response.status_code != 200:
            return {
                'success': False,
                'error_code': 'IMPORT_FAILED',
                'message': f'Import failed: {import_response.text}'
            }
        
        logger.info("Clone completed successfully")
        
        return {
            'success': True,
            'message': 'Clone completed successfully'
        }
        
    except Exception as e:
        logger.error(f"Clone failed: {e}")
        return {
            'success': False,
            'error_code': 'CLONE_ERROR',
            'message': f'Clone failed: {str(e)}'
        }


# API Endpoints
@app.get("/")
async def root():
    """Serve the UI"""
    static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static')
    index_path = os.path.join(static_dir, 'index.html')
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
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    
    # Get all loggers and their handlers
    loggers = [logging.getLogger(name) for name in logging.root.manager.loggerDict]
    all_logs = []
    
    # For now, return a simple message directing to docker logs
    return {
        "success": True,
        "message": "Use 'docker logs wp-setup-service' or check the latest clone attempt below",
        "note": "Logs are written to stdout/stderr and captured by Docker"
    }


@app.post("/setup", response_model=SetupResponse)
async def setup_endpoint(request: SetupRequest):
    """
    Setup WordPress site with Custom WP Migrator plugin
    """
    result = await setup_wordpress(
        str(request.url),
        request.username,
        request.password,
        request.role
    )
    
    if not result.get('success'):
        error_code = result.get('error_code', 'UNKNOWN_ERROR')
        status_code = {
            'AUTH_FAILED': status.HTTP_401_UNAUTHORIZED,
            'NOT_ADMIN': status.HTTP_403_FORBIDDEN,
            'PLUGIN_UPLOAD_FAILED': status.HTTP_500_INTERNAL_SERVER_ERROR,
            'PLUGIN_ACTIVATION_FAILED': status.HTTP_500_INTERNAL_SERVER_ERROR,
            'API_KEY_NOT_FOUND': status.HTTP_500_INTERNAL_SERVER_ERROR
        }.get(error_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        raise HTTPException(
            status_code=status_code,
            detail=result.get('message', 'Setup failed')
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
    
    # Setup source
    source_result = await setup_wordpress(
        str(request.source.url),
        request.source.username,
        request.source.password,
        role='source'
    )
    
    if not source_result.get('success'):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Source setup failed: {source_result.get('message')}"
        )
    
    # Determine target: use provided or auto-provision
    if request.target is None:
        if not request.auto_provision:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Target credentials required when auto_provision is False"
            )
        
        # Auto-provision EC2 target
        logger.info("Auto-provisioning EC2 target...")
        provisioner = EC2Provisioner()
        
        # Generate unique customer_id from timestamp
        customer_id = f"clone-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
        
        provision_result = provisioner.provision_target(
            customer_id=customer_id,
            ttl_minutes=request.ttl_minutes
        )
        
        if not provision_result.get('success'):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Target provisioning failed: {provision_result.get('message')}"
            )
        
        target_url = provision_result['target_url']  # Direct URL for setup
        public_url = provision_result.get('public_url', target_url)  # ALB URL for user
        target_username = provision_result['wordpress_username']
        target_password = provision_result['wordpress_password']
        
        provisioned_target_info = {
            'target_url': public_url,  # Show public URL to user
            'wordpress_username': target_username,
            'wordpress_password': target_password,
            'expires_at': provision_result.get('expires_at'),
            'ttl_minutes': request.ttl_minutes,
            'customer_id': customer_id,
            'instance_ip': provision_result.get('instance_ip')  # For Apache reload
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
        if provision_result.get('api_key'):
            logger.info("Using direct API key from provisioner, skipping browser setup")
            target_result = {
                'success': True,
                'api_key': provision_result['api_key'],
                'import_enabled': True,
                'message': 'Direct setup successful'
            }
        else:
            logger.info("Direct API key missing, falling back to browser-based setup")
            target_result = await setup_target_with_browser(
                target_url,
                target_username,
                target_password
            )
    else:
        # User-provided target - use HTTP-based setup
        logger.info("Using HTTP-based setup for user-provided target")
        target_result = await setup_wordpress(
            target_url,
            target_username,
            target_password,
            role='target'
        )
    
    if not target_result.get('success'):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Target setup failed: {target_result.get('message')}"
        )
    
    # Perform clone
    clone_result = perform_clone(
        str(request.source.url),
        source_result['api_key'],
        target_url,
        target_result['api_key']
    )
    
    if not clone_result.get('success'):
        logger.error(f"Clone failed: {clone_result.get('message')}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=clone_result.get('message', 'Clone failed')
        )
    
    # Reload Apache in auto-provisioned containers to reset database connections
    # This is required because SQLite connections become stale after import
    if provisioned_target_info and provisioned_target_info.get('instance_ip'):
        logger.info("Reloading Apache in target container to reset database connections...")
        provisioner = EC2Provisioner()
        provisioner.reload_apache_in_container(
            provisioned_target_info['instance_ip'],
            provisioned_target_info['customer_id']
        )
    
    logger.info("Clone process finished successfully")
    return CloneResponse(
        success=True,
        message="Clone completed successfully",
        source_api_key=source_result['api_key'],
        target_api_key=target_result['api_key'],
        target_import_enabled=target_result.get('import_enabled', False),
        provisioned_target=provisioned_target_info
    )


@app.post("/restore", response_model=CloneResponse)
async def restore_endpoint(request: CloneRequest):
    """
    Restore WordPress from source to target (identical to clone, just semantic naming)
    """
    return await clone_endpoint(request)


@app.post("/provision", response_model=ProvisionResponse)
async def provision_endpoint(request: ProvisionRequest):
    """
    Provision ephemeral WordPress target on AWS EC2
    """
    provisioner = EC2Provisioner()
    result = provisioner.provision_target(
        customer_id=request.customer_id,
        ttl_minutes=request.ttl_minutes
    )
    
    if not result.get('success'):
        error_code = result.get('error_code', 'UNKNOWN_ERROR')
        status_code = {
            'NO_CAPACITY': status.HTTP_503_SERVICE_UNAVAILABLE,
            'PORT_EXHAUSTED': status.HTTP_503_SERVICE_UNAVAILABLE,
            'DUPLICATE_TARGET': status.HTTP_409_CONFLICT
        }.get(error_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        raise HTTPException(
            status_code=status_code,
            detail=result.get('message', 'Provisioning failed')
        )
    
    return ProvisionResponse(**result)
