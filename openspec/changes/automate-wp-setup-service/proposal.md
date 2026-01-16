# Change: Automate WordPress Setup Service

## Why
Currently, cloning WordPress sites requires manual steps:
1. Client must manually install the Custom WP Migrator plugin via WordPress admin UI
2. Client must manually retrieve API key from Settings page  
3. Orchestrator script (`clone.sh`) requires pre-configured API keys

This creates friction for automated deployments and makes it impossible to clone sites where we only have admin credentials (username/password) without manual UI access.

## What Changes
Create a standalone automation service (Python or Go) that:
1. **Accepts WordPress credentials** (URL, username, password) instead of requiring pre-installed plugins
2. **Authenticates with WordPress** using standard WordPress REST API authentication
3. **Programmatically installs Custom WP Migrator plugin** by uploading the ZIP file
4. **Activates the plugin** via WordPress Plugin API
5. **Retrieves the generated API key** from WordPress options
6. **Orchestrates the clone** by calling export/import endpoints with retrieved API keys

This eliminates all manual steps and enables fully automated WordPress cloning with only admin credentials.

## What Problem This Solves
- **Client onboarding**: No need to ask clients to install plugins manually
- **Automated pipelines**: CI/CD can clone WordPress sites without human intervention
- **Remote management**: Clone sites where we have credentials but no shell/FTP access
- **Zero-touch deployment**: From credentials to cloned site in one command

## Technical Approach

### Language Choice
**Python** is recommended over Go because:
- Better WordPress REST API client libraries (`python-wordpress-xmlrpc`, `requests`)
- More mature HTTP form/multipart handling for plugin upload
- Simpler cookie/session management for wp-login authentication
- Rich ecosystem for HTML parsing (BeautifulSoup) if needed for scraping nonces

### Authentication Strategy
WordPress supports multiple auth methods:
1. **Application Passwords** (WordPress 5.6+, recommended): Generate via `/wp-admin/authorize-application.php`
2. **Cookie-based auth**: Login via `wp-login.php`, maintain session cookies
3. **JWT tokens**: Requires JWT plugin (adds dependency)

We'll use **Application Passwords** as primary method with cookie auth as fallback.

## Impact
- **New capability**: `wp-setup-automation` - Automates plugin installation and API key retrieval
- **New capability**: `wp-auth-api` - WordPress authentication abstraction layer
- **Modified**: `clone.sh` orchestration script will optionally call setup service before cloning
- **New service**: Python/Go HTTP service exposing `/setup` endpoint
- **Dependencies**: Python `requests`, `python-wordpress-xmlrpc` (or Go `net/http`, `go-wordpress`)

## Out of Scope
- Multi-site WordPress support (only single-site for now)
- Custom authentication plugins (stick to core WordPress auth)
- Plugin configuration beyond basic activation (use defaults)
- Handling WordPress sites behind additional firewalls/VPNs

## Implementation Sequence
1. Create authentication layer (Application Password generation or cookie auth)
2. Implement plugin upload/activation via WordPress REST/XMLRPC APIs
3. Implement API key retrieval from WordPress options table
4. Create HTTP service with `/setup` endpoint
5. Integrate with existing `clone.sh` workflow
