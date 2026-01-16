# Capability: WordPress Setup Automation

## ADDED Requirements

### Requirement: Authenticate with WordPress Admin Credentials

The setup service SHALL authenticate with a WordPress site using only admin username and password, without requiring pre-installed plugins or SSH access.

#### Scenario: Successful authentication with Application Password
**GIVEN** a WordPress 5.6+ site at `https://example.com`
**AND** an administrator account with username `admin` and Application Password `abcd 1234 efgh 5678`
**WHEN** the setup service calls `/setup` with `{url: "https://example.com", username: "admin", password: "abcd 1234 efgh 5678"}`
**THEN** the service SHALL authenticate using HTTP Basic Auth to `/wp-json/wp/v2/users/me`
**AND** the service SHALL receive a 200 OK response with user data
**AND** the service SHALL store session cookies for subsequent requests

#### Scenario: Fallback to cookie-based authentication
**GIVEN** a WordPress site that doesn't support Application Passwords (< 5.6 or disabled)
**AND** an administrator account with username `admin` and password `secret123`
**WHEN** Application Password authentication fails with 401
**THEN** the service SHALL fallback to POST `/wp-login.php` with form data
**AND** the service SHALL extract `wordpress_logged_in_*` cookies from response
**AND** the service SHALL verify admin access by checking `/wp-admin/` returns 200 (not 302 redirect)

#### Scenario: Authentication fails with invalid credentials
**GIVEN** a WordPress site at `https://example.com`
**WHEN** the setup service calls `/setup` with invalid password
**THEN** the service SHALL return HTTP 401 with error code `AUTH_FAILED`
**AND** the response SHALL include message "Invalid WordPress credentials"

#### Scenario: User lacks administrator role
**GIVEN** a WordPress site at `https://example.com`
**AND** a user account with 'editor' role (not administrator)
**WHEN** the setup service authenticates successfully but user is not admin
**THEN** the service SHALL return HTTP 403 with error code `NOT_ADMIN`
**AND** the response SHALL include message "User does not have administrator privileges"

---

### Requirement: Install WordPress Plugin from ZIP File

The setup service SHALL programmatically upload and activate the Custom WP Migrator plugin on a WordPress site via HTTP API.

#### Scenario: Successfully install plugin on fresh WordPress
**GIVEN** an authenticated admin session for `https://example.com`
**AND** the Custom WP Migrator plugin is NOT installed
**AND** the plugin ZIP file is available at `/plugins/custom-wp-migrator-plugin.zip`
**WHEN** the service uploads the plugin via `/wp-admin/update.php?action=upload-plugin`
**THEN** WordPress SHALL accept the ZIP file and extract it to `wp-content/plugins/custom-migrator/`
**AND** the service SHALL receive a success message containing "Plugin installed successfully"

#### Scenario: Activate newly installed plugin
**GIVEN** the Custom WP Migrator plugin is installed but not activated
**WHEN** the service POSTs to `/wp-admin/plugins.php?action=activate&plugin=custom-migrator/custom-migrator.php` with valid nonce
**THEN** WordPress SHALL activate the plugin
**AND** the activation hook SHALL create necessary directories and generate API key
**AND** the service SHALL verify activation by checking `/wp-json/wp/v2/plugins` shows plugin as active

#### Scenario: Plugin already installed and active
**GIVEN** the Custom WP Migrator plugin is already active on the WordPress site
**WHEN** the setup service checks plugin status via `/wp-json/wp/v2/plugins`
**THEN** the service SHALL skip installation and activation steps
**AND** the service SHALL proceed directly to API key retrieval

#### Scenario: Plugin upload fails due to insufficient permissions
**GIVEN** an authenticated session with restricted file permissions
**WHEN** the service attempts to upload the plugin ZIP
**AND** WordPress cannot write to `wp-content/plugins/` directory
**THEN** the service SHALL return HTTP 500 with error code `PLUGIN_UPLOAD_FAILED`
**AND** the response SHALL include message "Failed to install plugin: insufficient file permissions"

---

### Requirement: Retrieve Generated API Key

The setup service SHALL retrieve the Custom WP Migrator API key from WordPress after plugin activation.

#### Scenario: Retrieve API key via custom REST endpoint
**GIVEN** the Custom WP Migrator plugin is active
**AND** the plugin exposes `/wp-json/custom-migrator/v1/get-key` endpoint (future enhancement)
**WHEN** the service sends authenticated GET request to the endpoint
**THEN** the service SHALL receive JSON response `{api_key: "abc123..."}`
**AND** the API key SHALL be 32 characters alphanumeric

#### Scenario: Fallback to screen-scraping settings page
**GIVEN** the Custom WP Migrator plugin is active
**AND** the custom REST endpoint is not available (older plugin version)
**WHEN** the service requests `/wp-admin/options-general.php?page=custom-migrator-settings`
**THEN** the service SHALL parse HTML to extract API key from input field
**AND** the service SHALL use regex `name="custom_migrator_api_key" value="([a-zA-Z0-9]{32})"`
**AND** the service SHALL return the matched API key value

#### Scenario: API key not found after activation
**GIVEN** the Custom WP Migrator plugin activated successfully
**WHEN** the activation hook failed to generate an API key (corrupted database)
**THEN** the service SHALL return HTTP 500 with error code `API_KEY_NOT_FOUND`
**AND** the response SHALL include message "Plugin activated but API key not generated"

---

### Requirement: Enable Import Configuration

The setup service SHALL programmatically enable "Allow Import" setting for target WordPress sites to permit incoming clones.

#### Scenario: Enable import for target site
**GIVEN** the Custom WP Migrator plugin is active on target site
**AND** the "Allow Import" option is currently disabled
**WHEN** the service calls `/setup` with `{url: "https://target.com", username: "admin", password: "pass", role: "target"}`
**THEN** the service SHALL update WordPress option `custom_migrator_allow_import` to `true`
**AND** the service SHALL verify the option is set by reading it back
**AND** the service SHALL return success response

#### Scenario: Skip import enablement for source site
**GIVEN** the Custom WP Migrator plugin is active on source site
**WHEN** the service calls `/setup` with `{url: "https://source.com", username: "admin", password: "pass", role: "source"}`
**THEN** the service SHALL NOT modify the `custom_migrator_allow_import` option
**AND** the service SHALL only retrieve the API key

#### Scenario: Enable import via WordPress REST API
**GIVEN** an authenticated admin session for target site
**WHEN** the service updates the option via POST to `/wp-json/wp/v2/settings`
**AND** the request body includes `{"custom_migrator_allow_import": "1"}`
**THEN** WordPress SHALL update the option in the database
**AND** subsequent import requests SHALL be accepted

#### Scenario: Fallback to direct option update
**GIVEN** the REST API settings endpoint is not accessible
**WHEN** the service attempts to enable import
**THEN** the service SHALL POST to `/wp-admin/options.php` with form data:
- `option_page=custom_migrator_settings`
- `custom_migrator_allow_import=1`
- `_wpnonce={nonce}`
**AND** WordPress SHALL save the option

---

### Requirement: Ephemeral Target Provisioning

The service SHALL provide an endpoint to provision temporary WordPress instances on AWS EC2 Auto Scaling with Docker for clone targets.

#### Scenario: Provision new ephemeral target on warm EC2
**GIVEN** a customer ID "client-abc-123"
**AND** desired TTL of 30 minutes
**AND** EC2 instance is already running with <5 containers
**WHEN** user calls `POST /provision` with `{customer_id: "client-abc-123", ttl_minutes: 30}`
**THEN** the service SHALL:
1. Query ALB target group to find least-loaded EC2 instance
2. SSH to selected EC2 instance
3. Run Docker container with WordPress image
4. Configure Nginx reverse proxy for subdomain routing
5. Schedule cron job to destroy container after 30 minutes
6. Wait for health check to pass
7. Return response with target URL, credentials, and expiration time
**AND** the entire provisioning SHALL complete within 20 seconds

#### Scenario: Auto-scale when EC2 capacity full
**GIVEN** the current EC2 instance has 5 running containers (at capacity)
**WHEN** user requests a new provision
**THEN** CloudWatch custom metric SHALL trigger Auto Scaling
**AND** a new EC2 instance SHALL launch within 60 seconds
**AND** the new instance SHALL join ALB target group
**AND** provisioning SHALL proceed on the new instance

#### Scenario: Access provisioned target via subdomain
**GIVEN** a provisioned target with customer_id "client-abc-123" on port 8001
**WHEN** user navigates to `https://client-abc-123.temp.your-domain.com`
**THEN** ALB SHALL route request to EC2 instance
**AND** Nginx SHALL proxy to `localhost:8001`
**AND** WordPress SHALL respond within 2 seconds

#### Scenario: Auto-destroy container after TTL expires
**GIVEN** a provisioned container with TTL of 30 minutes
**WHEN** 30 minutes elapse since creation
**THEN** cron job SHALL execute `docker stop client-abc-123 && docker rm client-abc-123`
**AND** the container SHALL be removed within 10 seconds
**AND** Nginx configuration SHALL be updated to remove subdomain route
**AND** DNS record SHALL return 404/502

#### Scenario: Provision with existing customer_id
**GIVEN** a container already exists for customer_id "client-abc-123"
**WHEN** user attempts to provision another target with same customer_id
**THEN** the service SHALL return HTTP 409 with error code `DUPLICATE_TARGET`
**AND** response SHALL include existing target URL and expiration time

---

### Requirement: End-to-End Clone Operation

The service SHALL provide `/clone` and `/restore` endpoints that handle the complete workflow from credentials to finished clone.

#### Scenario: Clone from Railway to local Docker
**GIVEN** source WordPress at `https://railway-app.up.railway.app` (credentials: admin/pass1)
**AND** target WordPress at `http://localhost:8081` (credentials: admin/pass2)
**WHEN** user calls `POST /clone` with source and target credentials
**THEN** the service SHALL:
1. Setup source (install plugin if needed, get API key)
2. Setup target (install plugin if needed, get API key, enable import)
3. Export from source via `/wp-json/custom-migrator/v1/export`
4. Import to target via `/wp-json/custom-migrator/v1/import` with archive URL
5. Return success response with both API keys
**AND** the entire operation SHALL complete within 120 seconds

#### Scenario: Restore from local to Railway
**GIVEN** source WordPress at `http://localhost:8081` (edited locally)
**AND** target WordPress at `https://railway-app.up.railway.app`
**WHEN** user calls `POST /restore` with source and target credentials
**THEN** the service SHALL perform identical workflow as `/clone`
**AND** enable import on Railway (target) before importing
**AND** return success when restore completes

#### Scenario: Clone fails at export stage
**GIVEN** source WordPress credentials are valid
**AND** target WordPress setup succeeds
**WHEN** export from source fails (disk full, plugin error)
**THEN** the service SHALL return HTTP 500 with error code `EXPORT_FAILED`
**AND** response SHALL include source error message
**AND** target import SHALL NOT be attempted

#### Scenario: Clone fails at import stage
**GIVEN** source export succeeds and returns archive URL
**AND** target import is enabled
**WHEN** import to target fails (network error, corrupted archive)
**THEN** the service SHALL return HTTP 500 with error code `IMPORT_FAILED`
**AND** response SHALL include target error message
**AND** source archive SHALL remain available for retry

---

### Requirement: Complete Setup Workflow

The setup service SHALL orchestrate the complete workflow from authentication to API key retrieval in a single `/setup` endpoint call.

#### Scenario: End-to-end setup for new WordPress site
**GIVEN** a fresh WordPress site at `https://client-site.com` with admin credentials
**WHEN** the orchestrator calls `POST /setup` with `{url: "https://client-site.com", username: "admin", password: "pass123"}`
**THEN** the service SHALL:
1. Authenticate with the WordPress site
2. Check if Custom WP Migrator plugin is installed
3. Upload plugin ZIP if not installed
4. Activate the plugin
5. Wait 2 seconds for activation hook to complete
6. Retrieve the generated API key
7. Return JSON response:
```json
{
  "success": true,
  "api_key": "abc123def456...",
  "plugin_status": "activated",
  "message": "Setup completed successfully"
}
```
**AND** the entire workflow SHALL complete within 60 seconds

#### Scenario: Setup timeout due to slow WordPress response
**GIVEN** a WordPress site that takes > 60 seconds to respond to plugin upload
**WHEN** the service attempts the setup workflow
**THEN** the service SHALL timeout after 60 seconds
**AND** the service SHALL return HTTP 504 with error code `NETWORK_ERROR`
**AND** the response SHALL include message "WordPress site did not respond within timeout period"

---

### Requirement: Integration with Clone Script

The clone orchestration script SHALL optionally call the setup service before initiating WordPress clone.

#### Scenario: Clone with automatic setup for source and target
**GIVEN** the setup service is running at `http://localhost:5000`
**AND** source WordPress at `https://source.com` (credentials: admin/pass1)
**AND** target WordPress at `https://target.com` (credentials: admin/pass2)
**WHEN** the user runs:
```bash
./clone.sh --auto-setup \
  --source-url https://source.com --source-user admin --source-pass pass1 \
  --target-url https://target.com --target-user admin --target-pass pass2
```
**THEN** the script SHALL:
1. Call `POST http://localhost:5000/setup` for source site
2. Store returned API key in `SOURCE_API_KEY` environment variable
3. Call `POST http://localhost:5000/setup` for target site
4. Store returned API key in `TARGET_API_KEY` environment variable
5. Proceed with existing clone flow using retrieved API keys
6. Complete the clone successfully

#### Scenario: Clone with pre-configured API keys (skip setup)
**GIVEN** the user has manually installed plugins and knows API keys
**WHEN** the user runs traditional command:
```bash
SOURCE_API_KEY=xxx TARGET_API_KEY=yyy ./clone.sh
```
**THEN** the script SHALL skip calling the setup service
**AND** the script SHALL proceed directly with clone using provided API keys
