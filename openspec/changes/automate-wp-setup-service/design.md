# Design: WordPress Setup Automation Service

## Architecture Overview

```
┌─────────────┐         ┌──────────────────┐         ┌─────────────────┐
│   Clone     │         │  Setup Service   │         │  WordPress Site │
│  Script     ├────────→│   (Python API)   ├────────→│  (Source/Target)│
│  (Bash)     │  HTTP   │                  │  HTTP   │                 │
└─────────────┘         └──────────────────┘         └─────────────────┘
                              │
                              ├─ WordPressAuthenticator
                              ├─ WordPressPluginInstaller  
                              ├─ WordPressOptionsFetcher
                              └─ FastAPI HTTP Server
```

## Component Design

### 1. WordPressAuthenticator

**Responsibility**: Establish authenticated session with WordPress admin panel

**Authentication Flow**:
1. **Primary Method**: Application Passwords (WordPress 5.6+)
   - POST to `/wp-json/wp/v2/users/me` with Basic Auth
   - Header: `Authorization: Basic base64(username:app_password)`
   - If 200 OK → auth successful, store cookies
   
2. **Fallback Method**: Cookie-based Login
   - GET `/wp-login.php` to retrieve login nonce
   - POST `/wp-login.php` with `log=username&pwd=password&wp-submit=Log+In`
   - Extract `wordpress_logged_in_*` cookies
   - Verify admin access via `/wp-admin/` (302 redirect = not admin)

**Key Methods**:
```python
class WordPressAuthenticator:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.session = requests.Session()
    
    def authenticate(self, username: str, password: str) -> bool:
        # Try Application Password first
        if self._try_app_password(username, password):
            return True
        # Fallback to cookie auth
        return self._try_cookie_auth(username, password)
    
    def verify_admin_capability(self) -> bool:
        # Check /wp-json/wp/v2/users/me for 'administrator' role
        pass
    
    def get_rest_nonce(self) -> str:
        # Extract nonce from /wp-admin/ HTML
        pass
```

### 2. WordPressPluginInstaller

**Responsibility**: Upload and activate Custom WP Migrator plugin ZIP file

**Critical Assumptions**:
- WordPress admin panel is accessible (not behind additional auth)
- File uploads are enabled in PHP configuration
- `wp-content/plugins/` directory is writable
- WordPress REST API is available (enabled by default since WP 4.7+, but can be disabled)

**Installation Flow**:
1. Check if plugin already installed/active:
   - **Primary**: GET `/wp-json/wp/v2/plugins` (requires auth, available WP 5.5+)
   - **Fallback**: Screen-scrape `/wp-admin/plugins.php` to check for plugin presence
   - Look for `custom-migrator/custom-migrator.php` in response
   
2. Upload plugin ZIP:
   - **Method**: Multipart form POST to `/wp-admin/update.php?action=upload-plugin`
   - This uses WordPress's built-in plugin installer (always available, no REST API needed)
   - Headers: `Content-Type: multipart/form-data`
   - Form fields:
     - `pluginzip=@plugin.zip` (binary file upload)
     - `_wpnonce={nonce}` (CSRF protection, extracted from plugins page)
     - `install-plugin-submit=Install Now`
   - Parse response HTML for success message or error

3. Activate plugin:
   - **Method**: POST to `/wp-admin/plugins.php?action=activate&plugin=custom-migrator/custom-migrator.php`
   - Include `_wpnonce` from plugins page
   - This is a traditional admin form action (no REST API required)
   - Verify activation via REST API if available, or screen-scrape plugins page

**Why This Works for "Foreign" WordPress Sites**:
- Uses **standard WordPress admin panel endpoints** (available since WP 2.7+)
- Does NOT require REST API for plugin upload/activation (only for optional status checks)
- Only requires admin username/password (no FTP, SSH, or special plugins)
- Works even if REST API is disabled via plugin or `.htaccess`

**REST API Availability**:
- **Enabled by default**: WordPress 4.7+ (2016) has REST API enabled
- **Can be disabled**: Some security plugins disable it
- **Our approach**: Use REST API for status checks when available, fall back to screen-scraping
- **Plugin upload/activation**: Uses traditional admin panel forms (always works)

**Key Methods**:
```python
class WordPressPluginInstaller:
    def __init__(self, session: requests.Session, base_url: str):
        self.session = session
        self.base_url = base_url
    
    def is_plugin_installed(self, plugin_slug: str) -> bool:
        # Try REST API first, fall back to screen-scraping
        pass
    
    def upload_plugin(self, zip_path: str) -> bool:
        # Upload via admin panel (no REST API needed)
        pass
    
    def activate_plugin(self, plugin_slug: str) -> bool:
        # Activate via admin action (no REST API needed)
        pass
```

### 3. WordPressOptionsFetcher

**Responsibility**: Retrieve Custom WP Migrator API key from WordPress options and manage import settings

**Retrieval Strategy**:
1. **Primary**: WordPress Settings REST API
   - GET `/wp-json/wp/v2/settings`
   - Requires admin authentication
   - Look for custom option namespaces (may not work if plugin doesn't register settings in REST)

2. **Fallback**: Custom REST Endpoint
   - Add temporary REST endpoint in our plugin: `/wp-json/custom-migrator/v1/get-key`
   - Requires admin authentication
   - Returns `{api_key: "..."}`

3. **Last Resort**: Screen-scrape settings page
   - GET `/wp-admin/options-general.php?page=custom-migrator-settings`
   - Parse HTML for API key input field value
   - Regex: `name="custom_migrator_api_key" value="([a-zA-Z0-9]{32})"`

**Option Update Strategy** (for enabling "Allow Import"):
1. **Primary**: POST to `/wp-json/wp/v2/settings` with `{"custom_migrator_allow_import": "1"}`
2. **Fallback**: POST to `/wp-admin/options.php` with form data including nonce

**Key Methods**:
```python
class WordPressOptionsFetcher:
    def __init__(self, session: requests.Session, base_url: str):
        self.session = session
        self.base_url = base_url
    
    def get_migrator_api_key(self) -> Optional[str]:
        # Try REST API first, fall back to scraping
        pass
    
    def enable_import(self) -> bool:
        # Update custom_migrator_allow_import option to '1'
        pass
    
    def verify_import_enabled(self) -> bool:
        # Read back option to confirm
        pass
```

### 4. Setup Service HTTP API

**Technology**: FastAPI (Python 3.8+) for async support and auto-generated OpenAPI docs

**Endpoints**:

#### POST /provision
Provision ephemeral WordPress target on AWS EC2 Auto Scaling with Docker

**Request**:
```json
{
  "customer_id": "client-abc-123",
  "ttl_minutes": 30
}
```

**Response**:
```json
{
  "success": true,
  "target_url": "https://client-abc-123.temp.your-domain.com",
  "wordpress_username": "admin",
  "wordpress_password": "auto_generated_pass",
  "expires_at": "2026-01-14T13:30:00Z",
  "status": "running",
  "message": "Target provisioned successfully"
}
```

**Workflow**:
1. Query ALB target group to find least-loaded EC2 instance
2. SSH to selected EC2 instance
3. Run `docker run -d --name client-abc-123 -p 8001:80 wordpress-migrator:v6`
4. Configure Nginx reverse proxy: `client-abc-123.temp.domain.com` → `localhost:8001`
5. Reload Nginx configuration
6. Schedule cron job to stop/remove container after TTL
7. Wait for WordPress health check (~10-15 seconds)
8. Return target URL and credentials

**EC2 Auto Scaling Configuration**:
- **Min instances**: 1 (always warm, no cold start)
- **Max instances**: 5 (scale based on load)
- **Instance type**: t3.medium (2 vCPU, 4GB RAM)
- **Containers per instance**: Max 5 concurrent
- **Scaling trigger**: CloudWatch custom metric "container_count > 5"
- **Cost**: $30/month base (1 instance) + scale-up as needed

**Container Configuration**:
- **Image**: `ghcr.io/t0ct0c/wordpress-migrator:latest`
- **Resources**: 0.4 vCPU, 800MB RAM per container
- **Port**: Dynamic (8001-8010 range)
- **Network**: Bridge mode with port mapping
- **TTL**: Cron job runs `docker stop && docker rm` after expiration

**Nginx Routing**:
```nginx
server {
    listen 80;
    server_name client-abc-123.temp.your-domain.com;
    location / {
        proxy_pass http://localhost:8001;
    }
}
```

**Cold Start Time**: ~10-15 seconds (Docker pull cached, container startup only)

**Architecture Benefits**:
- No ECS cold start delay (instance already running)
- Multiple customers per EC2 (cost-efficient)
- Auto-scale only when needed
- Faster provisioning than ECS Fargate

#### POST /clone
Clone from source to target (enables import on target)

**Request**:
```json
{
  "source": {
    "url": "https://source.com",
    "username": "admin",
    "password": "pass123"
  },
  "target": {
    "url": "https://target.com",
    "username": "admin",
    "password": "pass456"
  }
}
```

**Response**:
```json
{
  "success": true,
  "message": "Clone completed successfully",
  "source_api_key": "abc123...",
  "target_api_key": "def456...",
  "target_import_enabled": true
}
```

**Workflow**:
1. Setup source (install plugin, get API key)
2. Setup target (install plugin, get API key, **enable import**)
3. Call export on source
4. Call import on target with archive URL
5. Return success

#### POST /restore
Restore from local/staging back to production (enables import on production)

**Request**:
```json
{
  "source": {
    "url": "http://localhost:8081",
    "username": "admin",
    "password": "local_pass"
  },
  "target": {
    "url": "https://production.com",
    "username": "admin",
    "password": "prod_pass"
  }
}
```

**Response**: Same as `/clone`

**Workflow**: Identical to `/clone` - both operations are conceptually the same (source→target), just semantic naming for clarity

#### POST /setup
**Request**:
```json
{
  "url": "https://example.com",
  "username": "admin",
  "password": "secret123",
  "role": "target"  // "source" or "target" - determines if import should be enabled
}
```

**Response (Success)**:
```json
{
  "success": true,
  "api_key": "abc123def456...",
  "plugin_status": "activated",
  "import_enabled": true,  // Only set for role="target"
  "message": "Custom WP Migrator plugin installed and activated"
}
```

**Response (Failure)**:
```json
{
  "success": false,
  "error_code": "AUTH_FAILED",
  "message": "Invalid WordPress credentials",
  "details": "Login returned 401 Unauthorized"
}
```

**Error Codes**:
- `AUTH_FAILED`: Invalid username/password
- `NOT_ADMIN`: User lacks administrator role
- `PLUGIN_UPLOAD_FAILED`: Plugin ZIP upload rejected
- `PLUGIN_ACTIVATION_FAILED`: Plugin activation failed
- `API_KEY_NOT_FOUND`: Could not retrieve API key after activation
- `NETWORK_ERROR`: Connection timeout or DNS failure

#### GET /health
```json
{
  "status": "healthy",
  "version": "1.0.0"
}
```

## Trade-offs & Decisions

### Why Python over Go?
- **Pro Python**: Mature WordPress ecosystem (`python-wordpress-xmlrpc`), easier cookie/session handling, BeautifulSoup for HTML parsing
- **Pro Go**: Better concurrency, smaller Docker image, no dependency hell
- **Decision**: Use Python for faster development and better WordPress library support

### Why Cookie Auth over JWT?
- **Pro JWT**: Stateless, no session management
- **Con JWT**: Requires installing JWT Authentication plugin on client site (violates zero-dependency goal)
- **Decision**: Use cookie-based auth as fallback, Application Passwords as primary

### Why Not Use WordPress XMLRPC?
- XMLRPC is deprecated in WordPress 5.5+ and disabled by default
- Security concerns (common attack vector)
- REST API is the modern standard

### Why Screen-Scraping as Last Resort?
- Not all WordPress sites expose options via REST API
- Screen-scraping is brittle but provides fallback for edge cases
- Better than failing entirely

## Security Considerations

1. **Credential Handling**:
   - Never log passwords in plaintext
   - Use environment variables for sensitive data
   - Clear session cookies after operation

2. **Plugin Trust**:
   - Verify plugin ZIP integrity (SHA256 checksum)
   - Only install our own signed plugin
   - Validate plugin activation status before returning API key

3. **Error Messages**:
   - Don't leak WordPress version or plugin info in errors
   - Sanitize URLs in logs (remove auth params)

## Alternative Approaches Considered

### 1. WP-CLI Remote Execution
**Rejected**: Requires shell access, defeats purpose of credential-only approach

### 2. SSH Tunnel + Direct DB Access
**Rejected**: Too invasive, requires SSH keys, breaks abstraction

### 3. WordPress Multisite Admin
**Rejected**: Only works for multisite networks, not applicable to single-site clients

## Implementation Phases

1. **MVP**: Cookie auth + screen-scraping only (fastest path)
2. **V2**: Add Application Password support
3. **V3**: Add custom REST endpoint in plugin for cleaner API key retrieval
4. **V4**: Docker packaging and ECS deployment

## Docker & ECS Deployment

### Dockerfile Structure
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Copy plugin ZIP (bundled in image)
COPY ../custom-wp-migrator-poc/custom-wp-migrator-plugin.zip /app/plugin.zip

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### ECS Task Definition
- **CPU**: 512 (0.5 vCPU)
- **Memory**: 1024 MB
- **Port**: 8000
- **Health Check**: `GET /health` (interval: 30s, timeout: 5s)
- **Environment Variables**:
  - `LOG_LEVEL=info`
  - `TIMEOUT=120` (seconds for clone operations)

### Container Resource Requirements
- Small footprint: ~100MB image size
- Low CPU usage: mostly I/O bound (HTTP requests)
- Memory: 1GB sufficient for concurrent operations
- Network: Requires outbound HTTPS to WordPress sites
