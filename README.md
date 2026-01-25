# WordPress Clone & Restore System

## What This Does

This system **clones WordPress sites** into temporary testing environments on AWS and **restores changes back to production**. You can:

1. **Clone a live WordPress site** (e.g., bonnel.ai) to a temporary AWS container
2. Make changes safely on the clone without touching production
3. **Restore changes back** to production with control over themes and plugins

**Key Feature:** Everything is automated via REST API - no manual server access or plugin installation needed.

## Current Status

### ✅ What's Working
- **Clone endpoint**: Creates clones from any WordPress site (tested with bonnel.ai on SiteGround)
- **Restore endpoint**: Restores content, themes, and plugins from source to target
- **Auto-provisioning**: Automatically creates isolated containers with unique credentials
- **Browser automation**: Logs in, installs plugin, configures everything automatically
- **Clone access**: Clones are accessible via ALB URLs with path-based routing
- **Preserve options**: Control whether to keep or replace target themes and plugins

### ⚠️ Known Limitations
- **SiteGround clones**: Clones inherit SiteGround plugins that cause redirect loops in subdirectory paths
- **Recommendation**: If source is SiteGround, restore back to SiteGround (not to clones)

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

## Quick Start

### 1. Clone a WordPress Site

Creates a temporary copy of your WordPress site for testing.

**Endpoint:** `POST http://13.222.20.138:8000/clone`

**Request:**
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

**Parameters:**
- `url`: **Must use HTTPS** (HTTP redirects break POST requests)
- `username`: WordPress admin username
- `password`: WordPress admin password
- `auto_provision`: Set to `true` to automatically create a container
- `ttl_minutes`: Clone expires and is deleted after this time (default: 60)

**Response:**
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

**What you get:**
- Clone URL to access your site
- Admin username and password
- Expiration time

---

### 2. Restore to Production

Restores content, themes, and plugins from source (clone or staging) to target (production).

**Endpoint:** `POST http://13.222.20.138:8000/restore`

**Request (Copy Everything):**
```json
{
  "source": {
    "url": "https://bonnel.ai",
    "username": "charles",
    "password": "source-password"
  },
  "target": {
    "url": "https://betaweb.ai",
    "username": "Charles",
    "password": "target-password"
  },
  "preserve_themes": false,
  "preserve_plugins": false
}
```

**Request (Keep Target Themes/Plugins):**
```json
{
  "source": {
    "url": "https://bonnel.ai",
    "username": "charles",
    "password": "source-password"
  },
  "target": {
    "url": "https://betaweb.ai",
    "username": "Charles",
    "password": "target-password"
  },
  "preserve_themes": true,
  "preserve_plugins": true
}
```

**Parameters:**
- `preserve_themes`:
  - `false` (default): Replace target themes with source themes
  - `true`: Keep target's existing themes
- `preserve_plugins`:
  - `false` (default): Replace target plugins with source plugins
  - `true`: Keep target's existing plugins

**Response:**
```json
{
  "success": true,
  "message": "Restore completed successfully",
  "source_api_key": "GL24zU5fHmxC0Hlh4c4WxVorOzzi4DCr",
  "target_api_key": "GL24zU5fHmxC0Hlh4c4WxVorOzzi4DCr"
}
```

**What happens:**
- Database content restored from source
- Themes copied (unless `preserve_themes: true`)
- Plugins copied (unless `preserve_plugins: true`)
- Uploads/media copied
- Custom Migrator plugin always preserved on target

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

### Restore Process

1. **Browser automation logs in** to both source and target
2. **Export from source** via plugin REST API
   - Creates ZIP with database, themes, plugins, uploads
3. **Import to target** via plugin REST API
   - Extracts content
   - Replaces or preserves themes based on `preserve_themes`
   - Replaces or preserves plugins based on `preserve_plugins`
   - Updates URLs to target domain
   - Creates must-use plugin to prevent redirects
4. **Response returned** with success status

---

## Important Gotchas

### 🔴 SiteGround Sources

**If your source is on SiteGround hosting (like bonnel.ai):**

**Problem:**
- Clones inherit SiteGround plugins (sg-security, sg-cachepress, wordpress-starter)
- These plugins cause Apache redirect loops (AH00124) in subdirectory paths
- **Impact**: Cannot export from clones back to other clones

**Solution:**
- ✅ **Clone from SiteGround** → Works perfectly
- ✅ **Restore SiteGround → SiteGround** → Works perfectly
- ❌ **Restore Clone → Clone** → Fails due to plugin conflicts
- ✅ **Restore SiteGround → SiteGround** → Recommended workflow

**Recommended Workflow:**
```
1. Clone bonnel.ai (SiteGround) → Creates clone-xxx
2. Test changes on clone-xxx
3. Restore bonnel.ai → betaweb.ai (both SiteGround)
   ✅ This works because SiteGround plugins work correctly on SiteGround hosting
```

**Don't do this:**
```
❌ Restore clone-xxx → betaweb.ai
   (Clone has SiteGround plugins that break in subdirectory paths)
```

### 🔴 Other Requirements

- **Use HTTPS**: Source URLs must be `https://` not `http://` (HTTP redirects break POST requests)
- **Clone TTL**: Clones auto-delete after expiration (default 60 minutes)
- **Credentials**: Must provide valid WordPress admin credentials

### ✅ Fixed Issues
- WordPress redirect loops (fixed with must-use plugin)
- wp-admin.php redirect (browser automation updated)
- Import checkbox timeout (error handling added)
- Preserve parameters naming (now correctly implemented)

---

## Technical Details

### API Endpoints
- **Clone**: `POST http://13.222.20.138:8000/clone`
- **Restore**: `POST http://13.222.20.138:8000/restore`
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
