# WordPress Clone & Restore System

## What This Does

This system **clones WordPress sites** into temporary testing environments on AWS. You can:

1. **Clone a live WordPress site** (e.g., bonnel.ai) to a temporary AWS container
2. Make changes safely on the clone without touching production
3. **Restore changes back** to production (⚠️ **NOT WORKING YET** - see [Current Status](#current-status))

**Key Feature:** Everything is automated via REST API - no manual server access or plugin installation needed.

## Current Status

### ✅ What's Working
- **Clone endpoint**: Creates clones from any WordPress site (tested with bonnel.ai)
- **Auto-provisioning**: Automatically creates isolated containers with unique credentials
- **Browser automation**: Logs in, installs plugin, configures everything automatically
- **Clone access**: Clones are accessible via ALB URLs with path-based routing

### ⚠️ What's NOT Working
- **Restore endpoint**: Cannot test restore because clones inherit SiteGround plugins that cause redirect loops when accessing REST API endpoints in subdirectory paths
- **Blocker**: Need another SiteGround WordPress site to test restore workflow

---

## Architecture

```mermaid
graph TD
    A["User / API Client"] --> B["Management Server<br/>13.222.20.138:8000"]
    
    B --> C["Browser Automation<br/>(Playwright)"]
    C --> D["Source WordPress<br/>(e.g., bonnel.ai)"]
    
    B --> E["Target EC2<br/>10.0.13.72"]
    E --> F["MySQL Container<br/>(Shared DB)"]
    E --> G["Clone Container 1<br/>(WordPress + Apache)"]
    E --> H["Clone Container 2<br/>(WordPress + Apache)"]
    E --> I["Nginx<br/>(Reverse Proxy)"]
    
    J["ALB<br/>wp-targets-alb-*.elb.amazonaws.com"] --> I
    I --> G
    I --> H
    
    G --> F
    H --> F
```

**Key Components:**
- **Management Server**: FastAPI service that orchestrates cloning
- **Browser Automation**: Playwright + Camoufox for plugin installation
- **Target EC2**: Runs Docker containers for WordPress clones
- **MySQL**: Shared database server, separate DB per clone
- **ALB + Nginx**: Path-based routing to clones (e.g., `/clone-20260124-035840/`)

---

## Quick Start: Clone a WordPress Site

### API Endpoint
```
POST http://13.222.20.138:8000/clone
Content-Type: application/json
```

### Request Body
```json
{
  "source": {
    "url": "https://bonnel.ai",
    "username": "your-username",
    "password": "your-password"
  },
  "auto_provision": true,
  "ttl_minutes": 60
}
```

**Important:**
- Use `https://` not `http://` (HTTP redirects break POST requests)
- `auto_provision: true` automatically creates a container
- `ttl_minutes`: Clone expires and is deleted after this time

### Response
```json
{
  "success": true,
  "message": "Clone completed successfully",
  "source_api_key": "GL24zU5fHmxC0Hlh4c4WxVorOzzi4DCr",
  "target_api_key": "migration-master-key",
  "provisioned_target": {
    "target_url": "http://wp-targets-alb-1392351630.us-east-1.elb.amazonaws.com/clone-20260124-035840",
    "wordpress_username": "admin",
    "wordpress_password": "F7n4xwasIMOimxSU",
    "expires_at": "2026-01-24T05:00:26.660750Z",
    "ttl_minutes": 60
  }
}
```

**You get back:**
- Clone URL to access your site
- Admin username and password
- Expiration time

---

## Infrastructure Details

### Management Server
- **IP**: 13.222.20.138
- **Service**: FastAPI (wp-setup-service)
- **Port**: 8000
- **What it does**: Orchestrates cloning, runs browser automation

### Target Server
- **IP**: 10.0.13.72 (private)
- **Components**:
  - Docker containers (one per clone)
  - MySQL container (shared, separate DB per clone)
  - Nginx reverse proxy
- **Access**: Via ALB at `wp-targets-alb-1392351630.us-east-1.elb.amazonaws.com`

### Clone Containers
- **Image**: `wordpress:latest` + Custom Migrator plugin + wp-cli
- **Database**: MySQL (shared server, separate database per clone)
- **Naming**: `clone-YYYYMMDD-HHMMSS`
- **Ports**: Dynamically assigned (e.g., 8021, 8022)
- **URL Pattern**: `http://ALB-DNS/clone-TIMESTAMP/`

---

## How It Works

### Clone Process

1. **You send a POST request** with source WordPress credentials
2. **Browser automation logs in** to the source site
   - Uploads Custom Migrator plugin
   - Activates plugin
   - Retrieves API key
3. **Container is provisioned** on target EC2
   - New MySQL database created
   - WordPress container started
   - Nginx routing configured
4. **Export from source** via plugin REST API
   - Creates ZIP with database, themes, plugins, uploads
5. **Import to clone** via plugin REST API
   - Extracts content
   - Updates URLs to ALB path
   - Creates must-use plugin to prevent redirects
6. **Response returned** with clone URL and credentials

### Restore Process (⚠️ NOT WORKING YET)

The restore endpoint exists but cannot be tested because:
- Clones inherit SiteGround plugins from bonnel.ai
- These plugins cause redirect loops in subdirectory paths
- Cannot export from clones to test restore workflow

**Blocker:** Need another SiteGround WordPress site to test restore to production.

---

## Known Issues

### ⚠️ Active Blocker
**SiteGround Plugin Redirect Loops**
- Clones inherit SiteGround plugins (sg-security, sg-cachepress, wordpress-starter)
- These plugins cause Apache redirect loops (AH00124) in subdirectory paths
- **Impact**: Cannot export from clones, blocks restore testing
- **Workaround**: Restore back to SiteGround hosting where plugins work correctly

### ✅ Fixed Issues
- WordPress redirect loops (fixed with must-use plugin)
- wp-admin.php redirect (browser automation updated)
- Import checkbox timeout (error handling added)

### Requirements
- **Use HTTPS**: Source URLs must be `https://` not `http://`
- **Clone TTL**: Clones auto-delete after expiration (default 60 minutes)

---

## Technical Details

### API Endpoints
- **Clone**: `POST http://13.222.20.138:8000/clone`
- **Restore**: `POST http://13.222.20.138:8000/restore` (⚠️ NOT WORKING)
- **Health**: `GET http://13.222.20.138:8000/health`
- **Web UI**: `http://13.222.20.138:8000/`

### SSH Access
```bash
# Management server
ssh -i wp-targets-key.pem ec2-user@13.222.20.138

# Target server (from management)
ssh -i /home/ec2-user/wp-targets-key.pem ec2-user@10.0.13.72
```

### Docker Images
- **Management**: `wp-setup-service:latest`
- **WordPress**: `044514005641.dkr.ecr.us-east-1.amazonaws.com/wordpress-target-sqlite:latest`
  - Note: Name says "sqlite" but actually uses MySQL (legacy naming)

### AWS Resources
- **Region**: us-east-1
- **ALB**: wp-targets-alb-1392351630.us-east-1.elb.amazonaws.com
- **ECR**: 044514005641.dkr.ecr.us-east-1.amazonaws.com

---

## Documentation

- **API_TEST_PLAN.md**: Detailed API usage examples and quirks
- **OPERATIONAL_MEMORY.md**: Current status, what's working, what's not
- **README.md**: This file - overview and quick start
