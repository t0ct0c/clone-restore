# Operational Memory Document - WordPress Clone/Restore System

**Last Updated**: 2026-01-24

## Current Status Summary

### ✅ What's Working
- **Clone endpoint**: Successfully creates clones from bonnel.ai (SiteGround)
- **Auto-provisioning**: Automatically provisions EC2 containers with unique credentials
- **Browser automation**: Logs in, uploads plugin, activates, retrieves API key
- **Response format**: Returns URL, username, password, expiration time
- **Path-based routing**: ALB routes traffic to correct clone containers
- **Frontend access**: Clone homepages and content accessible via ALB URLs
- **wp-admin access**: Login pages load correctly (with wp-admin.php redirect)

### ⚠️ Current Blockers
- **SiteGround plugin redirect loops**: Clones inherit SiteGround plugins (sg-security, sg-cachepress, wordpress-starter) that cause Apache internal redirect loops (AH00124) when accessing REST API endpoints in subdirectory paths
- **Export endpoint fails**: Cannot export from clones due to redirect loops, preventing clone-to-clone restore testing
- **Restore testing blocked**: Need another SiteGround WordPress site to test full restore workflow

### 🎯 Next Steps
1. Get SiteGround WordPress credentials for restore target testing
2. Test full workflow: Clone bonnel.ai → Restore to SiteGround target
3. Verify restore works correctly with SiteGround hosting (where plugins work)

## Infrastructure Overview

### Management Server (EC2 Instance)
- **Public IP**: 13.222.20.138
- **Private IP**: 10.0.13.72 (same host, different network interface)
- **SSH Key**: wp-targets-key.pem
- **Service**: wp-setup-service (FastAPI + Playwright + Camoufox)
- **Port**: 8000
- **Role**: Orchestrates clone/restore operations, browser automation

### Target Server (EC2 Instance)
- **Private IP**: 10.0.13.72
- **Role**: Runs WordPress clone containers
- **Container ports**: Dynamically assigned (e.g., 8021, 8022, etc.)
- **Storage**: Each container uses SQLite (no shared MySQL)
- **Reverse Proxy**: Nginx for path-based routing

### Load Balancer
- **ALB DNS**: wp-targets-alb-1392351630.us-east-1.elb.amazonaws.com
- **Path-based routing**: /clone-YYYYMMDD-HHMMSS/
- **Target**: Routes to Nginx on 10.0.13.72

## Successfully Resolved Issues

### ✅ Issue 1: WordPress Redirect Loop to localhost (FIXED)
**Solution**: 
- Created must-use plugin (`force-url-constants.php`) that disables canonical redirects
- Sets `WP_HOME` and `WP_SITEURL` constants in wp-config.php before wp-settings.php
- Removed `$_SERVER['HTTP_HOST']` override that was causing REST API redirect loops
**Status**: Frontend and wp-admin now accessible on all new clones
**Deployed**: 2026-01-24, Docker image SHA: `sha256:1d0a35138189a85d43b604f72b104ef2f0a0dd0d07db3ded5d397cb3fe68d3bc`

### ✅ Issue 2: wp-admin.php Redirect (FIXED)
**Problem**: New clones redirect to `/wp-admin.php` instead of `/wp-admin/`
**Solution**: Updated browser automation to accept both `/wp-admin/` and `/wp-admin.php` as valid admin URLs
**Status**: Browser automation no longer times out on new clones
**Deployed**: 2026-01-24

### ✅ Issue 3: Import Checkbox Timeout (FIXED)
**Problem**: Browser automation timing out (240s) when enabling import on target sites
**Solution**: Added explicit navigation to settings page, shorter timeouts (10s), and error handling
**Status**: Restore endpoint no longer hangs on import enable step
**Deployed**: 2026-01-24

### ✅ Issue 4: HTTP to HTTPS Redirect (DOCUMENTED)
**Problem**: Using `http://bonnel.ai` causes 301 redirect that breaks POST requests
**Solution**: Always use `https://bonnel.ai` in source URL
**Status**: Documented in API_TEST_PLAN.md and README.md

## Current Active Issues

### ⚠️ Issue 1: SiteGround Plugin Redirect Loops (BLOCKER)
**Symptoms**: 
- Clones inherit SiteGround plugins from bonnel.ai
- Apache logs show: `AH00124: Request exceeded the limit of 10 internal redirects`
- Export endpoint returns 500 error instead of creating archive
- Affects: sg-security, sg-cachepress, wordpress-starter plugins

**Root Cause**:
- SiteGround plugins designed for root path (`/`) installations
- When cloned to subdirectory path (`/clone-xxx/`), plugin rewrite rules conflict with Apache
- Creates infinite internal redirect loop when accessing REST API endpoints

**Impact**:
- Cannot export from clones (blocks clone-to-clone restore testing)
- Frontend and wp-admin work fine, only REST API affected

**Workaround**:
- Restore back to SiteGround hosting where plugins work correctly
- Use non-SiteGround WordPress source for testing

**Status**: Known limitation, not a bug - plugins work correctly in production SiteGround environment

## Commands Used

### SSH Access
```bash
# Management server
ssh -i wp-targets-key.pem -o StrictHostKeyChecking=no ec2-user@13.222.20.138

# Target server (from management server)
ssh -i /home/ec2-user/wp-targets-key.pem -o StrictHostKeyChecking=no ec2-user@10.0.13.72

# Combined SSH access
ssh -i wp-targets-key.pem -o StrictHostKeyChecking=no ec2-user@13.222.20.138 "ssh -i /home/ec2-user/wp-targets-key.pem -o StrictHostKeyChecking=no ec2-user@10.0.13.72 'COMMAND'"
```

### Docker Operations
```bash
# Check container logs
sudo docker logs wp-setup-service --tail 50

# Check WordPress container logs
sudo docker logs CONTAINER_NAME

# Execute commands in WordPress container
sudo docker exec CONTAINER_NAME COMMAND

# WordPress options
sudo docker exec CONTAINER_NAME wp option get home --path=/var/www/html --allow-root
sudo docker exec CONTAINER_NAME wp option get siteurl --path=/var/www/html --allow-root
```

### Nginx Configuration
```bash
# Check Nginx config for specific clone
sudo cat /etc/nginx/default.d/clone-YYYYMMDD-HHMMSS.conf

# Nginx config example for working clone:
location /clone-20260122-143617/ {
    proxy_pass http://localhost:8022/;
    # Always present upstream as localhost to WordPress to avoid host-mismatch redirect loops
    proxy_set_header Host localhost;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-Prefix /clone-20260122-143617;
    
    # Rewrite redirects back through the path prefix
    proxy_redirect / /clone-20260122-143617/;
}
```

### Testing Commands
```bash
# Test redirects
curl -I "http://wp-targets-alb-1392351630.us-east-1.elb.amazonaws.com/clone-YYYYMMDD-HHMMSS/wp-admin" 2>/dev/null | grep -i location

# Test direct container access
curl -I "http://10.0.13.72:PORT/wp-admin" 2>/dev/null | head -1

# Verbose curl for detailed tracing
curl -v "http://wp-targets-alb-1392351630.us-east-1.elb.amazonaws.com/clone-YYYYMMDD-HHMMSS/wp-admin" 2>&1 | grep -E "^(>|<)"
```

### WordPress Configuration
```bash
# Check wp-config.php syntax
sudo docker exec CONTAINER_NAME php -l /var/www/html/wp-config.php

# Backup wp-config.php
sudo docker exec CONTAINER_NAME cp /var/www/html/wp-config.php /var/www/html/wp-config.php.backup

# Check Apache error logs
sudo docker exec CONTAINER_NAME tail -20 /var/log/apache2/error.log
```

## Successful Implementations

### Implementation 1: Must-Use Plugin for Canonical Redirects
**Action**: Created `force-url-constants.php` mu-plugin during import
**Result**: ✅ Successfully prevents frontend redirect loops
**Code Location**: `wordpress-target-image/plugin/includes/class-importer.php`
**Key Learning**: Must-use plugins load before regular plugins and can override WordPress core behavior

### Implementation 2: URL Constants in wp-config.php
**Action**: Inject `WP_HOME` and `WP_SITEURL` constants before wp-settings.php
**Result**: ✅ WordPress uses correct ALB URLs instead of localhost
**Key Learning**: Constants must be placed before `require_once ABSPATH . 'wp-settings.php';`

### Implementation 3: Browser Automation with Playwright
**Action**: Use Playwright + Camoufox for headless browser automation
**Result**: ✅ Successfully logs in, uploads plugin, activates, retrieves API key
**Key Learning**: Browser automation more reliable than REST API for initial setup

### Implementation 4: Auto-Provisioning Workflow
**Action**: Automatically provision EC2 containers with unique credentials and TTL
**Result**: ✅ Clone endpoint returns complete response with URL, username, password
**Key Learning**: Auto-provisioning simplifies API usage - users don't need to manage infrastructure

## Failed Attempts & Lessons Learned

### Attempt 1: $_SERVER['HTTP_HOST'] Override
**Action**: Override `$_SERVER['HTTP_HOST']` to fix wp-admin redirects
**Failure**: Caused REST API redirect loops (AH00124 errors)
**Lesson**: Overriding server variables can break WordPress REST API routing
**Resolution**: Removed override, rely on WP_HOME/WP_SITEURL constants only

### Attempt 2: Clone-to-Clone Restore Testing
**Action**: Attempted to restore from clone to another clone
**Failure**: SiteGround plugins cause redirect loops preventing export
**Lesson**: Clones inherit production plugins that may not work in subdirectory paths
**Resolution**: Need SiteGround target for realistic restore testing

## Recent Successful Clones

### Clone 1: clone-20260124-014146
- **Created**: 2026-01-24 01:41:46
- **Source**: https://bonnel.ai
- **Status**: ✅ Created successfully, frontend accessible
- **Issue**: REST API redirect loops (SiteGround plugins)

### Clone 2: clone-20260124-032130
- **Created**: 2026-01-24 03:21:30
- **Source**: https://bonnel.ai
- **Status**: ✅ Created successfully, frontend accessible
- **Issue**: REST API redirect loops (SiteGround plugins)

### Clone 3: clone-20260124-035840
- **Created**: 2026-01-24 03:58:40
- **Source**: https://bonnel.ai
- **Status**: ✅ Created successfully, frontend accessible
- **Credentials**: admin / F7n4xwasIMOimxSU
- **Issue**: REST API redirect loops (SiteGround plugins)

## Next Actions Required

### Immediate (Blocked - Waiting for User)
1. **Get SiteGround WordPress credentials** for restore target testing
   - Need URL, username, password for another SiteGround WordPress install
   - Will test: Clone bonnel.ai → Restore to SiteGround target
   - This simulates real production workflow

### Future Enhancements (Not Blockers)
1. **Add plugin blacklist** to importer to automatically disable problematic plugins
2. **Implement clone cleanup** based on TTL expiration
3. **Add restore progress tracking** for long-running operations
4. **Improve error messages** for common failure scenarios
5. **Add health check endpoint** for clone containers

## Environment Context
- **Region**: us-east-1
- **AWS Account**: 044514005641
- **ECR Registry**: 044514005641.dkr.ecr.us-east-1.amazonaws.com
- **Service**: wp-setup-service:latest (FastAPI)
- **WordPress Image**: wordpress-target-sqlite:latest
  - Latest SHA: `sha256:1d0a35138189a85d43b604f72b104ef2f0a0dd0d07db3ded5d397cb3fe68d3bc`
- **Database**: SQLite (per-container, no shared MySQL)
- **Loki Logging**: Enabled on management server
- **Terraform State**: Managed separately in infra/wp-targets/

## Connection Details
- **Management Server**: ec2-user@13.222.20.138
- **Target Server**: ec2-user@10.0.13.72 (same host, via SSH)
- **SSH Key Location**: /home/ec2-user/wp-targets-key.pem (on management server)
- **Local SSH Key**: /home/chaz/Desktop/clone-restore/custom-wp-migrator-poc/wp-targets-key.pem
- **Docker Network**: Host networking used for communication

## API Endpoints
- **Clone**: `POST http://13.222.20.138:8000/clone`
- **Restore**: `POST http://13.222.20.138:8000/restore`
- **Health**: `GET http://13.222.20.138:8000/health`
- **Web UI**: `http://13.222.20.138:8000/`

## Documentation Status
- ✅ **README.md**: Updated with current architecture and mermaid diagram (2026-01-24)
- ✅ **API_TEST_PLAN.md**: Updated with auto-provisioning, quirks, response format (2026-01-24)
- ✅ **OPERATIONAL_MEMORY.md**: Updated with current status (2026-01-24)
- ✅ **.gitignore**: Added AGENTS.md, QODER.md, .qoder/, openspec/

## Git Repository
- **Branch**: feat/restore
- **Remote**: https://github.com/t0ct0c/clone-restore.git
- **Last Push**: 2026-01-24 (8 commits ahead of main)
- **Untracked**: .windsurf/ (IDE folder, not committed)