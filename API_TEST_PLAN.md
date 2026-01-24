# Clone & Restore API Test Plan

## Prerequisites
- wp-setup-service running on port 8000
- Source WordPress site (production) accessible
- Target EC2 instance with Docker available

## API Endpoints

### 1. Clone Endpoint
**Purpose:** Create a clone of a WordPress site on a target server

**Endpoint:** `POST http://localhost:8000/clone`

**Request Body (Auto-Provision):**
```json
{
  "source": {
    "url": "https://bonnel.ai",
    "username": "charles",
    "password": "your-password"
  },
  "auto_provision": true,
  "ttl_minutes": 60
}
```

**IMPORTANT QUIRKS:**
- ⚠️ **Use HTTPS for bonnel.ai**: `https://bonnel.ai` not `http://bonnel.ai` (HTTP gets 301 redirect which breaks POST requests)
- ⚠️ **Auto-provision recommended**: Set `auto_provision: true` and omit `target` field - the system will automatically provision an EC2 container
- ⚠️ **TTL**: Clones expire after `ttl_minutes` (default 60 minutes)

**Request Body (Manual Target - Advanced):**
```json
{
  "source": {
    "url": "https://bonnel.ai",
    "username": "charles",
    "password": "your-password"
  },
  "target": {
    "ssh_host": "10.0.13.72",
    "ssh_user": "ec2-user",
    "ssh_key_path": "/path/to/wp-targets-key.pem",
    "management_host": "13.222.20.138"
  }
}
```

**Expected Response (Auto-Provision):**
```json
{
  "success": true,
  "message": "Clone completed successfully",
  "source_api_key": "GL24zU5fHmxC0Hlh4c4WxVorOzzi4DCr",
  "target_api_key": "migration-master-key",
  "target_import_enabled": true,
  "provisioned_target": {
    "target_url": "http://wp-targets-alb-1392351630.us-east-1.elb.amazonaws.com/clone-20260124-035840",
    "public_url": "http://wp-targets-alb-1392351630.us-east-1.elb.amazonaws.com/clone-20260124-035840",
    "wordpress_username": "admin",
    "wordpress_password": "F7n4xwasIMOimxSU",
    "expires_at": "2026-01-24T05:00:26.660750Z",
    "ttl_minutes": 60,
    "customer_id": "clone-20260124-035840",
    "instance_ip": "10.0.13.72"
  }
}
```

**✅ YES - Response includes URL, username, and password!**
- `target_url` / `public_url`: Clone URL to access
- `wordpress_username`: Admin username (always "admin" for clones)
- `wordpress_password`: Randomly generated admin password
- `expires_at`: When the clone will be automatically deleted
- `target_api_key`: API key for the clone (always "migration-master-key")

**How to get API key from clone (without wp-admin):**
```bash
ssh ec2-user@10.0.13.72 'docker exec CLONE_NAME wp option get custom_migrator_api_key --path=/var/www/html --allow-root'
```

---

### 2. Restore Endpoint
**Purpose:** Restore a WordPress site from source (clone/staging) to target (production)

**Endpoint:** `POST http://localhost:8000/restore`

**Request Body (with clone as source):**
```json
{
  "source": {
    "url": "http://wp-targets-alb-1392351630.us-east-1.elb.amazonaws.com/clone-20260123-123456/",
    "username": "admin",
    "password": "admin",
    "api_key": "GL24zU5fHmxC0Hlh4c4WxVorOzzi4DCr"
  },
  "target": {
    "url": "http://your-production-site.com",
    "username": "admin",
    "password": "production-password"
  },
  "preserve_plugins": true,
  "preserve_themes": false
}
```

**Note:** When using a clone as source, provide the `api_key` to skip browser automation (since clones already have the plugin installed). Get the API key with:
```bash
ssh ec2-user@10.0.13.72 'docker exec CLONE_NAME wp option get custom_migrator_api_key --path=/var/www/html --allow-root'
```

**Parameters:**
- `preserve_plugins` (default: true) - Keep production plugins to avoid downgrading
- `preserve_themes` (default: false) - Restore themes from source

**Expected Response:**
```json
{
  "success": true,
  "message": "Restore completed successfully",
  "source_api_key": "abc123...",
  "target_api_key": "xyz789...",
  "integrity": {
    "warnings": []
  },
  "options": {}
}
```

---

## Test Workflow

### Step 1: Create a Clone
```bash
# Using auto-provision (recommended)
curl -X POST http://13.222.20.138:8000/clone \
  -H "Content-Type: application/json" \
  -d '{
    "source": {
      "url": "https://bonnel.ai",
      "username": "charles",
      "password": "VaA8S#OFl%zKf4&!o3#*86jq"
    },
    "auto_provision": true,
    "ttl_minutes": 60
  }'

# Response will include:
# - provisioned_target.target_url: Clone URL
# - provisioned_target.wordpress_username: "admin"
# - provisioned_target.wordpress_password: Random password
# - provisioned_target.expires_at: Expiration timestamp
```

### Step 2: Verify Clone
```bash
# Check clone URL is accessible (use URL from response)
curl -I http://wp-targets-alb-1392351630.us-east-1.elb.amazonaws.com/clone-20260124-035840/

# SSH to target server and verify plugin
ssh -i /path/to/wp-targets-key.pem ec2-user@13.222.20.138 \
  "ssh -i /home/ec2-user/wp-targets-key.pem ec2-user@10.0.13.72 \
  'docker exec clone-20260124-035840 wp plugin list --path=/var/www/html --allow-root'"

# Get API key (should be "migration-master-key" for clones)
ssh -i /path/to/wp-targets-key.pem ec2-user@13.222.20.138 \
  "ssh -i /home/ec2-user/wp-targets-key.pem ec2-user@10.0.13.72 \
  'docker exec clone-20260124-035840 wp option get custom_migrator_api_key --path=/var/www/html --allow-root'"

# Check clone users (inherited from bonnel.ai)
ssh -i /path/to/wp-targets-key.pem ec2-user@13.222.20.138 \
  "ssh -i /home/ec2-user/wp-targets-key.pem ec2-user@10.0.13.72 \
  'docker exec clone-20260124-035840 wp user list --path=/var/www/html --allow-root'"
```

### Step 3: Test Restore (Clone → Production)
```bash
curl -X POST http://localhost:8000/restore \
  -H "Content-Type: application/json" \
  -d '{
    "source": {
      "url": "http://wp-targets-alb-1392351630.us-east-1.elb.amazonaws.com/clone-TIMESTAMP/",
      "username": "admin",
      "password": "admin"
    },
    "target": {
      "url": "http://production-site.com",
      "username": "admin",
      "password": "PROD_PASSWORD"
    },
    "preserve_plugins": true,
    "preserve_themes": false
  }'
```

---

## Current Issues & Workarounds

### Issue: wp-admin redirects to /wp-admin.php on new clones
**Status:** FIXED (deployed 2026-01-24)
**Impact:** Browser automation needs to accept both `/wp-admin/` and `/wp-admin.php` as valid admin URLs
**Solution:** Updated browser_setup.py to recognize `wp-admin.php` as successful login
**Note:** New clones redirect to `/wp-admin.php` instead of `/wp-admin/` - this is normal behavior

### Issue: SiteGround plugins cause REST API redirect loops in clones
**Status:** KNOWN LIMITATION
**Impact:** Clones inherit SiteGround plugins (sg-security, sg-cachepress, wordpress-starter) from bonnel.ai which cause Apache internal redirect loops (AH00124) when accessing REST API endpoints in subdirectory paths
**Workaround:** 
  - For testing: Use a non-SiteGround WordPress source
  - For production: Restore back to SiteGround hosting where these plugins work correctly
**Root cause:** SiteGround plugins are designed for root path (`/`) and conflict with subdirectory clone paths (`/clone-xxx/`)

### Issue: Duplicate plugin installations
**Status:** FIXED (deployed)
**Solution:** Importer now excludes custom-migrator from source during restore

### Issue: HTTP to HTTPS redirect on bonnel.ai
**Status:** DOCUMENTED
**Impact:** Using `http://bonnel.ai` causes 301 redirect which breaks POST requests
**Solution:** Always use `https://bonnel.ai` in source URL

---

## Success Criteria

✅ Clone endpoint creates accessible clone
✅ Clone has custom-migrator plugin installed
✅ Clone API key can be retrieved via wp-cli
✅ Restore endpoint accepts clone as source
✅ Restore completes without errors
✅ Target site has restored content
✅ No duplicate plugins in restored site
