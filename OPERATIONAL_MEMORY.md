# Operational Memory Document - WordPress Clone/Restore System

## Infrastructure Overview

### Management Server (EC2 Instance)
- **Public IP**: 13.222.20.138
- **Private IP**: 10.0.13.72
- **SSH Key**: wp-targets-key.pem
- **Role**: Runs wp-setup-service container, manages target provisioning

### Target Servers (EC2 Auto Scaling Group)
- **Instance IP**: 10.0.13.72 (typical)
- **Role**: Runs WordPress containers for clones
- **Container ports**: Dynamically assigned (e.g., 8021, 8022, etc.)

### Load Balancer
- **ALB DNS**: wp-targets-alb-1392351630.us-east-1.elb.amazonaws.com
- **Path-based routing**: /clone-YYYYMMDD-HHMMSS/

## Current Issues & Solutions

### Issue 1: WordPress Redirect Loop to localhost/wp-admin
**Symptoms**: 
- Accessing `http://wp-targets-alb-1392351630.us-east-1.elb.amazonaws.com/clone-20260122-143617/wp-admin` 
- Results in 301 redirect to `http://localhost/wp-admin/`

**Root Cause**:
WordPress canonical redirect logic detects a mismatch between:
- The `Host` header value (ALB DNS name)
- The `home` and `siteurl` options in the database (`http://localhost`)

**Technical Details**:
1. Nginx path-based routing uses `proxy_set_header Host localhost;` to prevent redirect loops
2. WordPress detects Host header mismatch and triggers canonical redirects
3. WordPress auto-corrects URLs based on incoming request headers
4. wp-config.php constants must be placed BEFORE `require_once wp-settings.php` to be effective

**Current Status**:
- The clone `/clone-20260122-143617` currently has 500 errors due to wp-config.php syntax issues
- Direct container access works: `http://10.0.13.72:8021/`
- Path-based routing through ALB fails

### Issue 2: wp-config.php Syntax Errors
**Problem**: Manual edits to wp-config.php have introduced syntax errors causing 500 Internal Server Errors
**Cause**: Improper placement of PHP constants or malformed code during sed operations
**Current State**: wp-config.php.backup exists as working reference

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

## Failed Attempts & Lessons Learned

### Attempt 1: wp-config.php Constants Placement
**Action**: Added WP_HOME/WP_SITEURL constants using sed
**Failure**: Constants placed incorrectly (after wp-settings.php) or caused syntax errors
**Lesson**: Constants must be placed BEFORE `require_once wp-settings.php` and syntax must be perfect

### Attempt 2: Core File Patching
**Action**: Attempted to patch wp-includes/functions.php wp_guess_url() function
**Failure**: Caused additional complications without resolving the core issue
**Lesson**: Modifying core WordPress files is fragile and not sustainable

### Attempt 3: .htaccess Rules
**Action**: Added rewrite rules to handle redirects at Apache level
**Failure**: .htaccess not processed due to AllowOverride settings
**Lesson**: Need to check Apache configuration for .htaccess support

### Attempt 4: Database URL Updates
**Action**: Updated home/siteurl options via wp-cli
**Failure**: WordPress auto-corrected values after Apache reload
**Lesson**: WordPress prioritizes dynamic URL detection over database values in some contexts

## Partial Workarounds

### Direct Container Access
**Method**: Access containers directly via their assigned ports
**URL Pattern**: `http://10.0.13.72:PORT/`
**Status**: Works as temporary workaround, bypasses ALB path routing issues
**Limitation**: Not scalable for multiple concurrent clones - this is NOT a real solution

## Unresolved Issues

### Primary Issue: Path-Based Routing Failure
**Status**: Still occurring - WordPress clones redirect to localhost despite all fixes attempted
**Impact**: Path-based routing through ALB is completely broken
**Workaround Required**: Direct container access only

## Future Actions Required

1. **Fix wp-config.php syntax errors** in current broken clone
2. **Implement proper URL locking mechanism** that places constants before wp-settings.php
3. **Verify Apache configuration** allows .htaccess processing if needed
4. **Update wp-setup-service** to properly handle URL locking during provisioning
5. **Test new clones** to ensure the fix works for future provisions

## Environment Context
- **Region**: us-east-1
- **AWS Account**: (ECR registry: 044514005641.dkr.ecr.us-east-1.amazonaws.com)
- **Service**: wp-setup-service:latest
- **MySQL Container**: Running as 'mysql' on target EC2
- **Loki Logging**: Enabled on management server
- **Terraform State**: Managed separately in infra/wp-targets/

## Connection Details
- **Management Server**: ec2-user@13.222.20.138
- **Target Server**: ec2-user@10.0.13.72 (via management server)
- **SSH Key Location**: /home/ec2-user/wp-targets-key.pem (on management server)
- **Docker Network**: Host networking used for communication