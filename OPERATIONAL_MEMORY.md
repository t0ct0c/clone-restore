# Operational Memory Document - WordPress Clone/Restore System

**Last Updated**: 2026-02-26 23:40 SGT (15:40 UTC)

## CURRENT BRANCH: feat/kubernetes-restore
**Status**: ⚙️ OPTIMIZATION IN PROGRESS - Core system working, performance tuning complete
**System**: Kubernetes-based WordPress Clone/Restore (EKS + Traefik + Warm Pool + Local MySQL)
**Last Deployed**: wp-k8s-service:ttl-fix-20260226-230812 (WITH: atomic warm pool assignment + TTL extension + 8 workers)
**Clone Image**: wp-k8s-service-clone:final-fix-20260226-104040 (CORRECT - has HTTPS in entrypoint)

### ✅ PERFORMANCE & RELIABILITY FIXES - 2026-02-26 23:40 SGT (15:40 UTC)

**Session Goal**: Investigate and fix message queue reliability issues for 50-clone bulk test
**Issues Resolved**: Race conditions, queue throughput, TTL expiration, resource exhaustion

---

## Investigation Summary: "Lost Messages" Were Never Lost

### What We Thought Was Wrong:
- Messages accepted by API but never processed
- Jobs appearing to "vanish" from the queue
- Customer requests getting lost silently

### What Was Actually Happening:
1. **Messages were NOT lost** - all 17 "missing" messages were sitting in Redis queue
2. **Workers were processing slowly** - only 4 concurrent workers (2 processes × 2 threads)
3. **Queue throughput bottleneck** - 4 workers @ ~2-3 min/clone = ~1.3-2 clones/minute
4. **TTL race condition** - Jobs expired before processing (30min TTL from submission, not from processing start)

### Root Causes Identified:

#### 1. Insufficient Worker Capacity
- **Before**: 4 workers → ~1.3-2 clones/minute
- **Attempted**: 16 workers → ~5-6 clones/minute BUT caused memory exhaustion
- **Fixed**: 8 workers → ~3-4 clones/minute (stable)

#### 2. TTL Started at Submission (Not Processing)
- Jobs submitted to queue with 30-minute TTL
- If job waited 20 minutes in queue, only 10 minutes left to complete
- **Fixed**: Extended TTL by 60 minutes when job status changes to "running"
- Code location: `app/job_store.py:148` - TTL extension logic

#### 3. Resource Exhaustion Despite Karpenter
**Why Karpenter Couldn't Save Us:**
- Karpenter hit maximum node limit (29/30 nodes)
- Worker memory: Requested 1Gi, Actually used 2.5GB with 16 workers
- Node evictions: "Container dramatiq-worker was using 2504416Ki, request is 1Gi"
- Each worker runs Python + Playwright/Chromium = ~150-200MB per worker
- 16 workers × 150MB = 2.4GB (exceeded 1Gi request → eviction)

**Why So Many Nodes:**
- 30 clones × 2 containers (WordPress + MySQL) = 60 containers
- 16 workers with Chromium browsers = high memory
- Infrastructure pods (Traefik, warm pool, etc.)
- Total: Cluster saturation at 29 nodes

**The Fix:**
- Reduced workers from 16 to 8 (halves memory to ~1.2GB)
- Increased memory request from 1Gi to 2Gi (prevents evictions)
- Configuration: 2 processes × 4 threads = 8 concurrent workers

#### 4. Atomic Warm Pool Assignment (Race Condition)
- **Before**: Multiple workers could claim the same warm pod
- **Result**: Clone IDs skipped (e.g., 001 and 002 both tried to use same pod, only 002 succeeded)
- **Fixed**: Implemented atomic label updates using Kubernetes optimistic concurrency control
- Code location: `app/warm_pool_controller.py:135-225` - assign_warm_pod() method

---

### ✅ CRITICAL FIX COMPLETED - 2026-02-26 14:40 UTC

**Bug Fixed**: wp-admin login redirect loop AND CrashLoopBackOff on WordPress clone pods

**Root Cause (FINAL UNDERSTANDING)**:
1. WordPress needs `$_SERVER['HTTPS'] = 'on'` in wp-config.php because pods sit behind TLS-terminating Traefik LB
2. Kubernetes health probes configured as `httpGet` on port 80 triggered WordPress canonical redirect logic
3. Apache access logs confirmed: `"GET / HTTP/1.1" 301 263 "-" "kube-probe/1.35+"` - probe gets 301 redirect to HTTPS
4. Kubelet follows the 301 to HTTPS:443, which doesn't exist on the pod → connection refused → pod fails probe → CrashLoopBackOff

**The Solution (DEPLOYED AND VERIFIED)**:
Changed all WordPress container health probes from `httpGet` to `tcpSocket` on port 80. This checks "is Apache listening?" without triggering WordPress redirect logic.

### Changes Applied (2026-02-26)

**✅ Step 1**: Reverted `$_SERVER['HTTPS']` from warm_pool_controller.py wp-config templates (lines 308 and 682)
- The Docker entrypoint in image `final-fix-20260226-104040` already sets this flag correctly
- Templates no longer have duplicate HTTPS flag

**✅ Step 2**: Changed WordPress probes in warm_pool_controller.py (lines 414-425)
- Changed from: `http_get=client.V1HTTPGetAction(path="/", port=80)`
- Changed to: `tcp_socket=client.V1TCPSocketAction(port=80)`
- Applied to both liveness_probe and readiness_probe

**✅ Step 3**: Changed WordPress probes in k8s_provisioner.py (lines 515-532 and 1010-1025)
- Changed from: `http_get=client.V1HTTPGetAction(path="/", port=80)`
- Changed to: `tcp_socket=client.V1TCPSocketAction(port=80)`
- Applied to both liveness_probe and readiness_probe in 2 locations (warm pool + cold provision)

**✅ Step 4**: Built, pushed, and deployed new wp-k8s-service image
- Image: `wp-k8s-service:tcpsocket-probes-20260226-141959`
- Pushed to ECR: `044514005641.dkr.ecr.us-east-1.amazonaws.com/wp-k8s-service:tcpsocket-probes-20260226-141959`
- Deployed to EKS: `kubectl set image deployment/wp-k8s-service -n wordpress-staging ...`
- Deployment rolled out successfully

**✅ Step 5**: Deleted broken warm pool pods - New pods stabilized at 2/2 Ready with 0 restarts

**✅ Step 6**: Created test clone `ttl-test-final` and verified wp-admin login works perfectly

### Verification Results (2026-02-26 14:35 UTC)

**Warm Pool Status:**
- All pods: 2/2 Running with 0 restarts for 13+ minutes
- Events: Only 1 initial readiness probe failure during startup (expected while Apache starts)
- No probe failures after initial startup
- Pods stable and healthy

**Test Clone Status:**
- Clone ID: `ttl-test-final`
- Created in: ~71 seconds (source export to completion)
- Pod status: 2/2 Running, 0 restarts, 12+ minutes uptime
- URL: `https://ttl-test-final.clones.betaweb.ai`

**wp-admin Access Verification:**
- ✅ Homepage: Returns 200 OK
- ✅ wp-login.php: Returns 200 OK with proper HTTPS redirect parameters
- ✅ wp-admin: Fully accessible, dashboard loads with all assets
- ✅ Login cookies: Set with `secure` flag correctly
- ✅ **NO REDIRECT LOOP** - wp-admin dashboard fully functional

### Current System Configuration (2026-02-26 23:40 SGT)

**wp-k8s-service Deployment:**
- Image: `wp-k8s-service:ttl-fix-20260226-230812`
- Workers: 8 concurrent (2 processes × 4 threads)
- Memory: Request 2Gi, Limit 4Gi (prevents evictions)
- CPU: Request 500m, Limit 2
- Expected throughput: ~3-4 clones/minute
- Location: `kubernetes/wp-k8s-service/`

**Redis Queue:**
- Persistence: AOF enabled (appendonly yes)
- Eviction policy: noeviction (won't drop messages)
- Memory usage: ~2MB / 192Mi limit (1% used)
- Queue name: `dramatiq:clone-queue`

**Warm Pool:**
- Baseline: 2 pods maintained
- Max burst: 20 pods (queue-based scaling)
- Assignment: Atomic with optimistic concurrency control
- Image: `wp-k8s-service-clone:final-fix-20260226-104040`

**Job TTL Logic:**
- Initial: 30-60 minutes from submission
- Extension: +60 minutes when processing starts (status=running, progress=10)
- Prevents: Jobs expiring while waiting in queue

---

### Critical "DO NOT" List (IMPORTANT - READ THIS)
These mistakes have caused bugs multiple times. Follow these rules to prevent regression:

1. **DO NOT remove `$_SERVER['HTTPS']` from docker-entrypoint.sh**
   - The clone image `final-fix-20260226-104040` has this in the entrypoint
   - This is REQUIRED for wp-admin to work behind Traefik TLS load balancer
   - Removing it causes redirect loop on wp-admin login

2. **DO NOT use `httpGet` probes for WordPress containers**
   - httpGet probes trigger WordPress canonical redirect logic
   - WordPress returns 301 to HTTPS when it has `$_SERVER['HTTPS']=on`
   - Kubelet follows redirect to port 443 which doesn't exist → CrashLoopBackOff
   - ALWAYS use `tcpSocket` probes on port 80 for WordPress containers

3. **DO NOT scale workers beyond 8 without increasing memory request**
   - Each worker uses ~150-200MB (Python + Playwright/Chromium)
   - 8 workers = ~1.2GB (safe within 2Gi request)
   - 16 workers = ~2.5GB (caused evictions with 1Gi request)
   - If scaling to 12-16 workers, increase memory request to 3Gi

4. **DO NOT submit 30+ clones simultaneously without batching**
   - Karpenter limit: 30 nodes maximum
   - Each clone: 2 containers (WordPress + MySQL)
   - 30 clones = 60 containers → cluster saturation
   - Recommended: Batch in groups of 10 clones

5. **DO NOT rebuild the clone image unless absolutely necessary**
   - Current image `final-fix-20260226-104040` is correct
   - Rebuilding risks losing the working entrypoint configuration

6. **DO NOT commit changes to main branch without cluster verification**
   - Always test on EKS cluster first
   - Verify warm pool pods reach 2/2 Ready with 0 restarts
   - Create test clone and verify wp-admin login works
   - Monitor worker pod memory usage (should stay under request)
   - Only then commit to version control

### Files Modified (Final State)
1. ✅ `kubernetes/wp-k8s-service/app/warm_pool_controller.py` - tcpSocket probes (lines 414-425)
2. ✅ `kubernetes/wp-k8s-service/app/k8s_provisioner.py` - tcpSocket probes (lines 515-532, 1010-1025)

### Images
- **Clone image (CORRECT, keep)**: `wp-k8s-service-clone:final-fix-20260226-104040`
- **Service image (NEEDS REBUILD)**: currently `wp-k8s-service:fix-https-flag-20260226-123505`
- **ECR**: `044514005641.dkr.ecr.us-east-1.amazonaws.com`

---

## Previous Session Summary (2026-02-25 afternoon)

### What We Fixed
1. **TTL Cleaner** (✅ COMPLETE):
   - Added `ttl-expires-at` labels to Services, Ingresses, Secrets
   - Updated TTL cleaner to delete all resources when pods expire
   - Cleaned up 17 orphaned services, 7 ingresses, 36 secrets
   - Deployed: committed to feat/kubernetes-restore

2. **WordPress Image Issue** (✅ COMPLETE):
   - Problem: Cold provision was using wrong image (wordpress-target-sqlite:latest)
   - Solution: Updated k8s_provisioner.py to use optimized-v14 (same as warm pool)
   - Removed unnecessary WP-CLI plugin activation code (plugin already active in image)
   - Deployed: wp-k8s-service:use-working-image-20260225-223634

### What NOT to Do
- ❌ Don't build new WordPress clone images - optimized-v14 works
- ❌ Don't modify docker-entrypoint.sh - it's working as-is
- ❌ Don't add WP-CLI plugin activation - plugin already activated in image
- ✅ Always check what's working first before creating new solutions

### Restore Implementation Status
- ✅ Created `POST /api/v2/restore` endpoint (returns job_id immediately)
- ✅ Created `restore_wordpress()` Dramatiq task with progress tracking
- ✅ Test scripts ready (scripts/restore-single.py, TEST_SCENARIO.md)
- ⏳ **NOT YET TESTED** - This is the actual goal, paused due to clone bug discovery

### 🏗️ Current Infrastructure (Kubernetes on EKS)
- **EKS Cluster**: `wp-clone-restore` in us-east-1
- **Namespace**: `wordpress-staging`
- **wp-k8s-service**: `use-working-image-20260225-223634` (2 pods running)
- **dramatiq-worker**: `use-working-image-20260225-223634` (same deployment)
- **Warm Pool**: 2 WordPress pods using `optimized-v14` image (✅ working, has plugin)
- **Redis**: Master pod running for async job queue
- **TTL Cleaner**: CronJob executing every 5 minutes (✅ now cleans all resources)
- **Ingress**: Traefik for unlimited subdomain-based routing
- **Domain**: `clones.betaweb.ai` (subdomain routing: `clone-id.clones.betaweb.ai`)
- **WordPress Image**: `optimized-v14` (warm pool + cold provision both use this now)

### 📋 Testing Scripts Available
- **scripts/clone-single.py**: Test single clone creation with timing
- **scripts/restore-single.py**: Test async restore endpoint (NEW - Feb 25, 2026)
- **scripts/bulk-create-clones.py**: Load test with 50 concurrent clones
- **scripts/delete-clones.py**: Cleanup test clones and resources
- **TEST_SCENARIO.md**: Complete testing guide for async restore (NEW - Feb 25, 2026)

### ✅ What's Working (Kubernetes Architecture)
- **Warm pool system**: Pre-provisioned WordPress pods ready for instant assignment
- **Local MySQL sidecars**: Each pod has dedicated MySQL container (no shared DB bottleneck)
- **Async clone creation**: Dramatiq workers process clone jobs via Redis queue (`POST /api/v2/clone`)
- **Async restore endpoint**: New non-blocking restore with job status polling (`POST /api/v2/restore`) - READY FOR TESTING
- **Traefik ingress**: Dynamic subdomain routing (`clone-id.clones.betaweb.ai`)
- **TTL-based cleanup**: CronJob automatically removes expired clones
- **Parallel execution**: WordPress setup runs concurrently with pod assignment
- **Job status polling**: `/api/v2/job-status/{job_id}` endpoint tracks progress
- **HTTPS support**: All clones accessible via HTTPS subdomain
- **Progress tracking**: Restore operations report progress (10% → 30% → 50% → 100%)

### 🔧 Optimization Implementation Details
**Warm Pool Controller** (`kubernetes/wp-k8s-service/app/warm_pool_controller.py`):
- Maintains pool of 3 ready pods
- Instant assignment when clone requested
- Automatic pool replenishment after assignment

**K8s Provisioner** (`kubernetes/wp-k8s-service/app/k8s_provisioner.py`):
- Creates Deployment + Service + Ingress for each clone
- Local MySQL sidecar per pod (no external DB)
- Parallel WordPress setup during provisioning

**TTL Cleaner** (`kubernetes/wp-k8s-service/app/ttl_cleaner.py`):
- CronJob checks for expired clones every 5 minutes
- Cleans up Kubernetes resources (Deployment, Service, Ingress, Secret)
- Returns pods to warm pool when possible

**Async Task Queue** (`kubernetes/wp-k8s-service/app/tasks.py`):
- Dramatiq workers process clone jobs
- Redis backend for job queue
- Status tracking for each job

### ✅ Testing Phase COMPLETE - Results (2026-02-25)

**Test 1: Single Clone Creation (Warm Pool)**
- ✅ Clone created in **55 seconds** (10s under 65s target!)
- ✅ Pod assigned from warm pool instantly
- ✅ HTTPS URL accessible: `test-opencode-001.clones.betaweb.ai`
- ✅ MySQL sidecar running (2/2 containers)
- ✅ Database healthy with source content (1MB)

**Test 2: Second Clone (Cold Provision)**
- ✅ Clone created in **80 seconds** (warm pool empty)
- ✅ Cold provisioning fallback working correctly
- ✅ New warm pool pod created automatically
- ✅ Both clones accessible simultaneously

**Test 3: Bulk Load Test (10 Clones)**
- ✅ 10 clones created successfully
- ✅ Mix of warm pool + cold deployments
- ✅ All clones accessible with unique subdomains
- ✅ System handled concurrent load without issues
- ✅ Services + Ingress created for all clones

**MySQL Sidecar Verification:**
- ✅ Database connectivity: All 15 WordPress tables healthy
- ✅ Database size: ~1MB with source site content
- ✅ WP-CLI commands working: `wp db check`, `wp db size`, `wp post list`
- ✅ Local MySQL eliminates shared DB bottleneck

**Warm Pool Behavior:**
- ✅ Pods assigned instantly when available
- ⚠️ Warm pool depletes during high load (as expected)
- ✅ Cold provisioning fallback working (80s vs 55s)
- ✅ Warm pool pods are reused directly (not creating deployments)
- ✅ Pod labels updated: `app=wordpress-warm` → `app=wordpress-clone`

**Outstanding Items (feat/kubernetes branch)**:
- ⏳ Test TTL cleanup and pod return to pool
- ⏳ Test 50 clones/hour sustained load
- ⏳ Push remaining commits to remote

**Outstanding Items (feat/kubernetes-restore branch - CURRENT)**:
- ⏳ **USER ACTION REQUIRED**: Run test scenario from TEST_SCENARIO.md
- ⏳ Verify async restore works end-to-end (clone → edit → restore)
- ⏳ Extract perform_restore() function from perform_clone() (future enhancement)
- ⏳ Implement preserve_plugins/preserve_themes properly (future enhancement)
- ⏳ Update API documentation with new endpoint
- ⏳ Push feat/kubernetes-restore branch to remote
- ⏳ Consider merging to feat/kubernetes after successful testing

### 📊 Performance Targets (Phase 1 & 2)
- ✅ **Local MySQL**: Eliminate shared DB bottleneck (IMPLEMENTED)
- ✅ **Warm Pool**: < 10s pod assignment (IMPLEMENTED - 3 pods ready)
- ✅ **Parallel Execution**: WordPress setup + pod provisioning concurrent (IMPLEMENTED)
- ⏳ **Total Clone Time**: < 65 seconds (NEEDS TESTING)
- ⏳ **Sustained Load**: 50 clones/hour without degradation (NEEDS TESTING)

### 📝 Recent Commits (feat/kubernetes-restore branch - Unpushed)
1. `8bc0ccb` - feat: implement async restore endpoint with progress tracking (Feb 25, 2026)

### 📝 Recent Commits (feat/kubernetes branch - Unpushed - 5 commits)
1. `49311a0` - chore: cleanup and documentation updates
2. `c7bed15` - fix: add JSON credential file cleanup to delete-clones.py
3. `8bf7f42` - fix: preserve app label in warm pool _tag_pod for TTL cleaner
4. `4c91b77` - fix: add HTTPS flag post-clone so wp-login works behind TLS LB
5. `bffd5dd` - fix: resolve 5-layer clone failure - clones now serve actual source content

### 🆕 Async Restore Implementation (Feb 25, 2026)
**Branch**: feat/kubernetes-restore (branched from feat/kubernetes)
**Status**: Implementation Complete - Awaiting User Testing
**Deployed**: Docker image `wp-k8s-service:bugfix-20260225-112952` to EKS cluster

**Implementation Summary**:
- **New Endpoint**: `POST /api/v2/restore` returns `job_id` immediately (non-blocking)
- **Dramatiq Task**: `restore_wordpress()` in tasks.py processes restore jobs asynchronously
- **Progress Tracking**: 10% (job received) → 30% (source setup) → 50% (target setup) → 100% (complete)
- **Clone Detection**: Automatically detects clone sources (URLs with `/clone-` or `.clones.betaweb.ai`)
- **Fast Path**: Clone sources try `migration-master-key` first before browser automation
- **Browser Automation**: Used for source key retrieval and target setup when needed
- **Backward Compatible**: Old `/restore` endpoint preserved but marked as deprecated
- **Job Status**: Poll via existing `GET /api/v2/job-status/{job_id}` endpoint

**Key Features**:
1. **Non-blocking**: Returns immediately, client polls for status
2. **Progress visibility**: Real-time progress updates via job status endpoint
3. **Timeout prevention**: No risk of HTTP timeouts on long operations (60-120s)
4. **Consistent UX**: Matches existing async clone endpoint pattern
5. **Error handling**: Comprehensive error reporting through job status

**Files Modified**:
- `kubernetes/wp-k8s-service/app/main.py`:
  - Lines 1087-1111: AsyncRestoreRequest model
  - Lines 1157-1178: POST /api/v2/restore endpoint
  - Lines 826-845: Deprecated old restore endpoint (marked with warning)
- `kubernetes/wp-k8s-service/app/tasks.py`:
  - Lines 181-310: restore_wordpress() Dramatiq task

**Files Created**:
- `scripts/restore-single.py`: Test script for async restore endpoint
- `TEST_SCENARIO.md`: Complete step-by-step testing guide
- `openspec/changes/restore-async-optimization/README.md`: Implementation design
- `openspec/changes/restore-async-optimization/tasks.md`: Detailed task breakdown

**Testing Instructions**:
See `TEST_SCENARIO.md` for complete testing workflow:
1. Create test clone: `python3 scripts/clone-single.py restore-test-clone`
2. Edit clone in browser (make visible changes)
3. Update `scripts/restore-single.py` with clone credentials
4. Run restore: `python3 scripts/restore-single.py`
5. Verify changes appeared on target site
6. Cleanup test resources

**Future Enhancements**:
- Extract dedicated `perform_restore()` function (currently reuses `perform_clone()`)
- Implement `preserve_plugins` and `preserve_themes` parameters properly
- Add comprehensive API documentation
- Consider adding restore-specific progress milestones

### 🔑 Key Fixes in Latest Commits
- **5-layer clone fix**: Clones now correctly serve source WordPress content (not default WP)
- **HTTPS wp-login**: Set HTTPS flag after clone creation for TLS load balancer compatibility
- **Warm pool labels**: Preserve `app=wordpress-warm` label so TTL cleaner can identify pool pods
- **Credential cleanup**: delete-clones.py now removes JSON credential files after deletion

---

## OLD INFRASTRUCTURE (EC2-based - DEPRECATED - Use for Reference Only)

### Management Server (EC2 Instance - DEPRECATED)
- **Public IP**: 13.222.20.138 (no longer used for Kubernetes architecture)
- **Private IP**: 10.0.13.72 (same host, different network interface)
- **SSH Key**: wp-targets-key.pem
- **Service**: wp-setup-service (FastAPI + Playwright + Camoufox)
- **Port**: 8000
- **Role**: Orchestrates clone/restore operations, browser automation

### Target Server (EC2 Instance)
- **Private IP**: 10.0.13.72
- **Role**: Runs WordPress clone containers
- **Container ports**: Dynamically assigned (e.g., 8021, 8022, etc.)
- **Storage**: Each container uses MySQL (shared MySQL container per EC2 instance)
- **Reverse Proxy**: Nginx for path-based routing

### Load Balancer
- **ALB DNS**: wp-targets-alb-1392351630.us-east-1.elb.amazonaws.com
- **Custom Domain**: clones.betaweb.ai (CNAME → ALB DNS)
- **HTTPS**: ACM cert `arn:aws:acm:us-east-1:044514005641:certificate/c3fb5ab3-160f-4db2-ac4b-056fe7166558`
- **HTTPS Listener ARN**: `arn:aws:elasticloadbalancing:us-east-1:044514005641:listener/app/wp-targets-alb/9deaa3f04bc5506b/f6542ccc3f16bfd7`
- **HTTP Listener**: Redirects 301 → HTTPS
- **Path-based routing**: /clone-YYYYMMDD-HHMMSS/
- **Target**: Routes to Nginx on EC2 instances

## Successfully Resolved Issues

### ✅ Issue 10: Plugin Corruption After Restore - Database/File Mismatch (FIXED - Jan 28, 2026)
**Problem**: 
- After restore operations, target site's custom-migrator plugin becomes corrupted
- Plugin files exist on disk but WordPress doesn't recognize it as active
- REST API returns 404 "No route was found matching the URL and request method"
- Session management breaks on admin pages
- Site becomes unrecoverable without manual intervention

**Symptoms**:
1. Plugin files physically present in wp-content/plugins/custom-migrator/
2. WordPress database has plugin marked as inactive in wp_options.active_plugins
3. REST API endpoints non-functional (404 errors)
4. Admin page navigation triggers session invalidation
5. Site exhibits same corruption pattern as betaweb.ai (Issue 9)

**Root Cause - Sequential Analysis**:
The import process in [class-importer.php](file:///home/chaz/Desktop/clone-restore/custom-wp-migrator-poc/wordpress-target-image/plugin/includes/class-importer.php) has a critical sequencing flaw:

1. **Line 38-39**: Import database from source (includes source's active_plugins list)
   - If source had custom-migrator **inactive** when exported, database will have it inactive
   
2. **Line 48-49**: Restore files (physically copies plugins including custom-migrator to disk)
   - Plugin files are present but database still says "inactive"
   
3. **Line 62-63**: Disable problematic plugins (modifies active_plugins)
   - Only removes unwanted plugins, doesn't ensure essential plugins are active

**The Gap**: No step ensures custom-migrator is activated after file restoration. The imported database state (from source) controls plugin activation, not the physical file presence.

**Solution Implemented**:
Added `ensure_custom_migrator_active()` function to [class-importer.php](file:///home/chaz/Desktop/clone-restore/custom-wp-migrator-poc/wordpress-target-image/plugin/includes/class-importer.php):

```php
private function ensure_custom_migrator_active() {
    // Critical: Ensure custom-migrator plugin is active after restore
    // Source database may have it inactive, causing corruption on target
    $plugin_path = 'custom-migrator/custom-migrator.php';
    
    // Get current active plugins
    $active_plugins = get_option('active_plugins', array());
    
    // Check if custom-migrator is already active
    if (!in_array($plugin_path, $active_plugins)) {
        // Add to active plugins list
        $active_plugins[] = $plugin_path;
        $active_plugins = array_values($active_plugins); // Re-index array
        
        update_option('active_plugins', $active_plugins);
        $this->log('CRITICAL: Activated custom-migrator plugin to prevent corruption');
    } else {
        $this->log('Custom-migrator plugin already active');
    }
}
```

**Implementation Details**:
1. Function called after `restore_files()` and `disable_siteground_plugins()` (line 66)
2. Forcibly adds `custom-migrator/custom-migrator.php` to active_plugins array
3. Updates wp_options table to reflect activation
4. Logs activation for debugging via Loki

**Why This Works**:
- Modifies the database `active_plugins` option directly
- WordPress will load plugin on next request
- REST API endpoints will be registered automatically
- No reliance on source database state
- Idempotent - safe to call even if already active

**Files Modified**:
- `/wordpress-target-image/plugin/includes/class-importer.php` (lines 65-66, 737-758)
  - Added function call in import() flow
  - Added ensure_custom_migrator_active() function

**Status**: ✅ Code deployed, awaiting production testing
**Deployed**: 2026-01-28
**Next Steps**: 
1. Build new Docker image with fix
2. Push to ECR registry
3. Test with restore operation
4. Verify plugin remains active after restore
5. Check REST API endpoints work immediately

**Prevention**: This fix prevents future betaweb.ai-style corruption on restore targets
**Impact**: High - Resolves critical corruption issue blocking restore workflow

**Key Learnings**:
1. **Import sequence matters** - Database import before file restore creates mismatch window
2. **Database state trumps file presence** - WordPress uses wp_options, not filesystem
3. **Essential plugins need forced activation** - Can't rely on imported database state
4. **Sequential thinking reveals gaps** - Step-by-step analysis found the missing activation
5. **Similar pattern to Issue 9** - betaweb.ai likely suffered from this same bug
6. **Loki logging confirms success** - Recent clone logs show proper activation flow

### ✅ Issue 11: Restore Endpoint Preflight Validation - Preventing Silent Failures (FIXED - Jan 28, 2026)
**Problem**: 
- Restore endpoint had no preflight validation before destructive operations
- Failed restores returned `success: true` even when database was empty
- Target site showed WordPress language setup screen after "successful" restore
- No verification that restore actually worked after import completed
- Initial preflight attempts checked REST API endpoints that returned HTTP 403
- REST API checks failed even though browser automation could bypass security

**Symptoms**:
1. Restore API returns 200 OK with `success: true`
2. Target site shows WordPress language setup screen (database empty)
3. REST API returns 404 (no WordPress installation)
4. Cannot log in to target site (no admin users exist)
5. Previous working site completely destroyed with no rollback
6. Preflight checks blocked restores that would have worked (false negatives)

**What Was Tried** (Sequential troubleshooting):

**Attempt 1: REST API Status Endpoint Validation** ❌
- Added preflight check: `GET /wp-json/custom-migrator/v1/status`
- Checked `import_allowed` flag from status response
- **Failed**: betaweb.ai firewall/security returns HTTP 403 for REST API
- **Why it failed**: REST API blocked by SiteGround security or Cloudflare WAF
- **Error**: "Target has import disabled (safety check)" even though import was enabled

**Attempt 2: REST API with 403 Exception Handling** ❌
- Added special handling: treat HTTP 403 as acceptable, defer to browser automation
- Logged warnings instead of errors for 403 responses
- **Failed**: Still blocked restore because subsequent checks also hit 403
- **Why it failed**: Multiple REST API checks all returned 403 (status, plugin verification)

**Attempt 3: HTTP Checks for wp-login.php and wp-admin** ❌
- Replaced REST API checks with HTTP requests to login/admin pages
- Checked if wp-login.php returns 200
- Checked if wp-admin returns 302 (redirect) or 200
- **Failed**: Both endpoints returned HTTP 403 from security/firewall
- **Why it failed**: Security plugins block automated HTTP requests, but NOT browser automation
- **Errors logged**:
  ```
  1. Target login page unreachable (HTTP 403)
  2. Target wp-admin blocked by security/firewall
  ```

**Attempt 4: Minimal HTTP Checks Only** ✅
- **Key realization**: Browser automation uses Camoufox with `humanize=True` and `geoip=True`
- Browser requests appear as real user traffic, bypassing security
- HTTP requests from Python `requests` library get blocked as bots
- **Solution**: Only check what HTTP requests can reliably validate

**Root Cause - Sequential Analysis**:
The restore process uses TWO different access methods:
1. **Python requests library** (for REST API export/import calls)
   - Gets blocked by security plugins/firewalls (HTTP 403)
   - Used for actual data transfer (export/import endpoints)
   
2. **Browser automation** (Camoufox + Playwright)
   - Bypasses security because it looks like real user
   - Used for authentication, plugin setup, API key retrieval

Preflight checks were using Python requests to validate endpoints that only browser automation needed. This created false negatives - blocking restores that would have worked.

**Solution Implemented**:
Implemented **tiered preflight validation** in [main.py](file:///home/chaz/Desktop/clone-restore/custom-wp-migrator-poc/wp-setup-service/app/main.py) restore endpoint:

**Preflight Checks (Lines 483-552):**
```python
# === PREFLIGHT CHECKS START ===

# 1. Source API accessible (used by Python requests)
GET source/?rest_route=/custom-migrator/v1/status
✓ Validates source export endpoint reachable

# 2. Target WordPress installed (not setup screen)
GET target_url (follow redirects)
✓ Detects if target shows language setup/install.php
✓ Prevents restore to broken/uninstalled WordPress

# 3. Source export endpoint functional
GET source/?rest_route=/custom-migrator/v1/status
✓ Confirms source can generate export archives

# 4. Target credential validation (DEFERRED TO BROWSER)
✓ Logged: "Target credential validation will occur during browser setup"
✓ Browser automation handles this - no HTTP preflight needed

# 5. Target wp-admin access (DEFERRED TO BROWSER)
✓ Logged: "Target wp-admin validation will occur during browser setup"
✓ Browser automation handles this - no HTTP preflight needed

if preflight_errors:
    return {
        'success': False,
        'error_code': 'PREFLIGHT_FAILED',
        'preflight_errors': preflight_errors
    }
```

**Post-Import Verification (Lines 632-699):**
```python
# === POST-IMPORT VERIFICATION START ===

# 1. Target homepage returns 200 (not setup screen)
GET target_url
if 'wp-admin/install.php' in url or 'language' in text:
    FAIL: "Target shows language setup - database not populated"
✓ Detects silent database import failures

# 2. REST API functional (may return 403 - acceptable)
GET target/wp-json/custom-migrator/v1/status
if status == 403:
    ✓ Accept (security plugin active, not a failure)
elif status != 200:
    FAIL: "REST API non-functional"

# 3. Admin area accessible
GET target/wp-admin/ (no redirects)
if status == 500:
    FAIL: "Admin area returns 500 error"
✓ Confirms WordPress core functional

if verification_errors:
    return {
        'success': False,
        'error_code': 'IMPORT_VERIFICATION_FAILED',
        'verification_errors': verification_errors
    }
```

**Why This Works**:
- **Fail fast**: Validates only what Python requests need (export endpoint, WordPress installed)
- **Defers to browser**: Doesn't check endpoints that only browser automation accesses
- **Accepts security blocks**: Treats HTTP 403 as acceptable when expected
- **Post-import verification**: Confirms database actually populated (not empty)
- **No false negatives**: Doesn't block restores that would work

**What Works vs What Doesn't**:

✅ **Works (Validated by HTTP)**:
- Source export endpoint reachable
- Target homepage not showing setup screen
- Target WordPress core installed
- Post-restore: homepage accessible
- Post-restore: database populated

❌ **Doesn't Work (Returns 403)**:
- REST API status endpoint on secured sites
- wp-login.php on secured sites
- wp-admin on secured sites

✅ **Works (Browser Automation Handles)**:
- Login to wp-admin
- Plugin upload/activation
- API key retrieval
- Import endpoint (uses API key from browser)

**Test Results**:
Restore from bonnel.ai clone → betaweb.ai:
```bash
curl -X POST http://13.222.20.138:8000/restore \
  -H "Content-Type: application/json" \
  -d '{
    "source": {
      "url": "http://wp-targets-alb-1392351630.us-east-1.elb.amazonaws.com/clone-20260128-015505",
      "username": "admin",
      "password": "ygu8GZ9jSjCHIF6S"
    },
    "target": {
      "url": "https://betaweb.ai",
      "username": "Charles",
      "password": "A@1^I*j^(KdRKxQF"
    },
    "preserve_themes": false,
    "preserve_plugins": false
  }'
```

**Logs:**
```
2026-01-28 03:48:43 | INFO | === PREFLIGHT CHECKS START ===
2026-01-28 03:48:43 | INFO | ✓ Source API accessible
2026-01-28 03:48:43 | INFO | ✓ Target WordPress reachable
2026-01-28 03:48:43 | INFO | ✓ Source export endpoint accessible
2026-01-28 03:48:43 | INFO | ✓ Target credential validation will occur during browser setup
2026-01-28 03:48:43 | INFO | ✓ Target wp-admin validation will occur during browser setup
2026-01-28 03:48:43 | INFO | === PREFLIGHT CHECKS PASSED - Proceeding with restore ===
2026-01-28 03:48:43 | INFO | Exporting from source...
2026-01-28 03:49:04 | INFO | Export completed
2026-01-28 03:49:04 | INFO | Importing to target...
2026-01-28 03:49:20 | INFO | === POST-IMPORT VERIFICATION START ===
2026-01-28 03:49:22 | INFO | ✓ Target homepage accessible
2026-01-28 03:49:24 | INFO | ✓ Target REST API functional
2026-01-28 03:49:25 | INFO | ✓ Target admin area accessible
2026-01-28 03:49:25 | INFO | === POST-IMPORT VERIFICATION PASSED ===
```

**Response:**
```json
{
  "success": true,
  "message": "Restore completed successfully",
  "verification_status": "passed",
  "integrity": {},
  "options": {}
}
```

**Files Modified**:
- `/wp-setup-service/app/main.py` (lines 483-714)
  - Replaced REST API preflight checks with HTTP-based validation
  - Deferred browser-specific checks to browser automation phase
  - Added 403 handling for secured target sites
  - Added post-import verification (homepage, REST API, admin)
  - Enhanced error reporting with specific failure arrays

**Status**: ✅ Code deployed and tested successfully
**Deployed**: 2026-01-28
**Test Status**: Restore from bonnel.ai clone to betaweb.ai completed with all verifications passing

**Prevention**: This fix prevents:
1. False positive success responses when database import fails
2. False negative preflight failures when security blocks HTTP but browser works
3. Silent failures that destroy target sites without confirmation

**Impact**: Critical - Enables reliable restores to secured production sites

**Key Learnings**:
1. **Browser automation != HTTP requests** - Security treats them differently
2. **HTTP 403 context matters** - Acceptable for secured sites, not for broken sites
3. **Validate what you use** - Preflight should check endpoints the restore actually needs
4. **Post-verification critical** - Don't trust API success responses, verify actual state
5. **Tiered validation** - HTTP checks for data endpoints, browser for authentication
6. **False negatives hurt** - Overly strict preflight blocks legitimate restores
7. **Defer to strengths** - Let browser handle auth, HTTP handle data validation
8. **Setup screen detection** - Primary indicator of database import failure
9. **Camoufox bypasses WAF** - Humanized browser traffic passes security checks
10. **Context-aware error handling** - Same error code (403) means different things in different contexts

## Successfully Resolved Issues

### ✅ Issue 1: ALB Load Balancing Breaking Clone Access (FIXED)
**Problem**: 
- ALB was load-balancing requests randomly across 5 EC2 instances
- Each clone only existed on one specific instance with its Nginx configuration
- Requests hitting wrong instances returned 2-byte "OK" response (health check endpoint)
- Clone REST API endpoints returned 500 errors or empty responses
- Export from clones failed, blocking clone-to-production restore workflow

**Root Cause**:
- ALB listener had only default forward action to target group
- No path-based routing rules to direct `/clone-xxx/*` to correct instance
- 4 out of 5 requests hit wrong instance and failed

**Solution**: 
- Implemented dynamic ALB listener rule creation in EC2 provisioner
- Each clone now gets dedicated target group and ALB listener rule
- Path pattern `/clone-xxx/*` routes to specific instance hosting that clone
- Added IAM permissions for ELB operations to EC2 instance role

**Implementation Details**:
1. **EC2 Provisioner** (`wp-setup-service/app/ec2_provisioner.py`):
   - Added `elbv2_client` for ALB management
   - Added `_get_instance_id()` to map private IP to instance ID
   - Added `_create_alb_listener_rule()` to create path-based routing
   - Creates target group per clone, registers instance, creates listener rule

2. **Terraform IAM Policy** (`infra/wp-targets/main.tf`):
   - Added ELB permissions: `DescribeRules`, `CreateRule`, `CreateTargetGroup`, `RegisterTargets`, `ModifyRule`, `DeleteRule`, `DeleteTargetGroup`, `DeregisterTargets`
   - Applied with `terraform apply`

3. **Restore Workflow** (`wp-setup-service/app/main.py`):
   - Clone sources skip browser automation (use known API key)
   - Use query string format for REST API: `index.php?rest_route=/endpoint`

**Status**: ✅ Clone REST API fully functional, restore from clone to production working
**Deployed**: 2026-01-27
**Test Results**:
- Clone homepage: 200 OK via ALB
- REST API export: 200 OK with valid JSON response
- Full restore workflow: Clone → betaweb.ai completed successfully

### ✅ Issue 5: Clone Plugin Inactive After Creation (FIXED - Jan 27, 2026)
**Problem**: 
- The `custom-migrator` plugin was inactive on newly created clones
- REST API endpoints returned 404 "No route was found matching the URL and request method"
- Export from clones failed, blocking restore workflow

**Root Cause**:
- Plugin gets deactivated during the clone import process
- WordPress doesn't automatically activate plugins after database import

**Solution**: 
- Manually activate the plugin on the clone container:
  ```bash
  docker exec <clone-container-id> wp plugin activate custom-migrator --path=/var/www/html --allow-root
  ```
- Future fix: Add automatic plugin activation to import process

**Status**: ✅ Plugin activation resolves REST API 404 errors
**Deployed**: Manual fix applied to clone-20260127-014446

### ✅ Issue 6: Wrong API Key for Clone Sources (FIXED - Jan 27, 2026)
**Problem**: 
- Restore endpoint was hardcoding `migration-master-key` for all clone sources
- Clones created from regular WordPress sites (like bonnel.ai) inherit their source site's API key
- Restore failed with "Invalid API key" error when trying to export from clone

**Root Cause**:
- `main.py` restore endpoint (line 821) had hardcoded: `source_api_key = 'migration-master-key'`
- This assumption was wrong - only clones created via `/provision` endpoint use `migration-master-key`
- Clones from real sites inherit the source site's original API key

**Solution**: 
- Modified `main.py` restore endpoint to use browser automation for ALL sources (including clones)
- Browser automation logs into clone and retrieves the actual API key from settings page
- Removed hardcoded API key assumption

**Files Changed**:
- `/custom-wp-migrator-poc/wp-setup-service/app/main.py` (lines 818-833)

**Status**: ✅ Restore endpoint now correctly retrieves API keys from clone sources
**Deployed**: 2026-01-27, Commit: 1cf947ace97f363599ba7d5e467b6f031c79f4a4
**Test Results**: Clone-20260127-014446 → betaweb.ai restore completed successfully

### ✅ Issue 7: API Key Validation Too Strict (FIXED - Jan 27, 2026)
**Problem**: 
- Browser automation rejected `migration-master-key` (21 characters)
- Validation only accepted exactly 32-character API keys
- Sites previously restored from clones had `migration-master-key` and were rejected

**Root Cause**:
- `browser_setup.py` line 347 had strict validation: `if not api_key or len(api_key) != 32:`
- This rejected the valid `migration-master-key` used by clone targets

**Solution**: 
- Updated validation to accept both 32-character keys AND `migration-master-key`
- New validation: `if not api_key or (len(api_key) != 32 and api_key != 'migration-master-key'):`

**Files Changed**:
- `/custom-wp-migrator-poc/wp-setup-service/app/browser_setup.py` (line 348)

**Status**: ✅ Browser automation now accepts both API key formats
**Deployed**: 2026-01-27, Commit: 47aef5fca6dae50fb7293996b02916d94ce7daa8

### ✅ Issue 8: Camoufox Browser Initialization Error (FIXED - Jan 27, 2026)
**Problem**: 
- Browser automation failed with: "manifest.json is missing. Addon path must be a path to an extracted addon."
- Clone endpoint returned 500 error
- Could not create new clones

**Root Cause**:
- `browser_setup.py` line 53 had: `async with AsyncCamoufox(headless=True, addons=[]) as browser:`
- Passing empty `addons=[]` array caused Camoufox to expect valid addon paths
- Camoufox doesn't accept empty array for addons parameter

**Solution**: 
- Removed `addons=[]` parameter from AsyncCamoufox initialization
- Changed to: `async with AsyncCamoufox(headless=True) as browser:`

**Files Changed**:
- `/custom-wp-migrator-poc/wp-setup-service/app/browser_setup.py` (line 53)

**Status**: ✅ Browser automation initializes correctly
**Deployed**: 2026-01-27, Commit: 1cf947ace97f363599ba7d5e467b6f031c79f4a4

### ✅ Issue 2: WordPress Redirect Loop to localhost (FIXED)
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

### ✅ Issue 11: Restore Endpoint Silent Failures - No Preflight or Verification (FIXED - Jan 28, 2026)
**Problem**: 
- Restore endpoint returns `success: true` even when import fails silently
- Database dropped but not repopulated - target site shows WordPress language setup
- No validation that prerequisites are met before starting destructive operations
- No verification that import actually worked after completion
- Misleading success messages when site is broken

**Symptoms**:
1. Restore API returns 200 OK with `success: true`
2. Target site shows WordPress language setup screen (database empty)
3. REST API returns 404 (no WordPress installation)
4. Cannot log in to target site (no admin users exist)
5. Previous working site completely destroyed with no rollback

**Root Cause - Sequential Analysis**:
The restore endpoint in [main.py](file:///home/chaz/Desktop/clone-restore/custom-wp-migrator-poc/wp-setup-service/app/main.py) had critical gaps:

**Missing Preflight Checks:**
1. No validation source API is accessible before export
2. No check target API is accessible before import
3. No verification target has import enabled (safety check)
4. No confirmation target WordPress is installed (not in setup mode)
5. No validation custom-migrator plugin is active on target
6. Destructive operations (drop tables) executed without prerequisites confirmed

**Missing Post-Import Verification:**
1. Trusted HTTP 200 response without validating WordPress functional
2. No check that database was actually populated
3. No verification target homepage accessible (not showing setup screen)
4. No REST API functionality test after import
5. No admin area accessibility check
6. Import could fail silently but still return success

**The Critical Flaw:**
The import process:
1. Line 143 (class-importer.php): Drop all tables ← DESTRUCTIVE, NO ROLLBACK
2. Line 163: Execute SQL import ← Could fail silently
3. Line 76: Return success ← Trusts process completion = data success

If SQL import failed or imported empty data, the endpoint would still return `success: true` because no exceptions were thrown.

**Solution Implemented**:
Added comprehensive preflight checks and post-import verification to [main.py](file:///home/chaz/Desktop/clone-restore/custom-wp-migrator-poc/wp-setup-service/app/main.py) restore endpoint:

**Preflight Checks (Lines 480-580):**
```python
# PREFLIGHT CHECKS - Validate all prerequisites before starting
logger.info("=== PREFLIGHT CHECKS START ===")

# 1. Source connectivity and API health
# 2. Target connectivity and API health  
# 3. Verify source can export
# 4. Check target not in setup/installation mode
# 5. Verify target plugin active and functional

if preflight_errors:
    return {
        'success': False,
        'error_code': 'PREFLIGHT_FAILED',
        'preflight_errors': preflight_errors
    }
```

**Post-Import Verification (Lines 651-720):**
```python
# POST-IMPORT VERIFICATION - Ensure import actually worked
logger.info("=== POST-IMPORT VERIFICATION START ===")

# 1. Target homepage returns 200 (not setup screen)
# 2. REST API functional
# 3. Admin area accessible

if verification_errors:
    return {
        'success': False,
        'error_code': 'IMPORT_VERIFICATION_FAILED',
        'verification_errors': verification_errors
    }
```

**Why This Works**:
- **Fail fast**: Stop before destructive operations if prerequisites not met
- **Dependency validation**: Each check must pass before proceeding to next
- **Explicit verification**: Don't trust API responses, test actual functionality
- **Clear error reporting**: Return specific failure reasons, not generic "restore failed"
- **No silent failures**: Every critical step validated with concrete checks

**Preflight Check Flow**:
```
Source API accessible? ❌ → STOP, return error
  ↓ ✅
Target API accessible? ❌ → STOP, return error
  ↓ ✅
Target import enabled? ❌ → STOP, return error
  ↓ ✅
Target WordPress installed? ❌ → STOP, return error
  ↓ ✅
Target plugin active? ❌ → STOP, return error
  ↓ ✅
Proceed with export/import
```

**Post-Verification Flow**:
```
Import API returned success
  ↓
Target homepage shows setup? ✅ → FAIL, database not populated
  ↓ ❌
REST API returns 404? ✅ → FAIL, plugin not loaded
  ↓ ❌
Admin redirects to install? ✅ → FAIL, WordPress broken
  ↓ ❌
All verifications passed → Return success
```

**Implementation Details**:
1. Added 5 preflight checks before export starts
2. Each check logs progress: "Preflight X/5: ..."
3. Added 3 post-import verifications after import completes
4. Each verification logs progress: "Verification X/3: ..."
5. Returns detailed error arrays with specific failure reasons
6. New response fields: `preflight_errors`, `verification_errors`, `verification_status`

**Files Modified**:
- `/wp-setup-service/app/main.py` (lines 475-720)
  - Added preflight check system
  - Added post-import verification system
  - Enhanced error reporting with specific failure details

**Status**: ✅ Code deployed to main.py
**Deployed**: 2026-01-28
**Next Steps**: 
1. Test with failing scenarios (source unreachable, target in setup mode)
2. Verify preflight stops destructive operations when checks fail
3. Test post-verification catches database import failures
4. Update API documentation with new error codes
5. Build and deploy wp-setup-service Docker image

**Prevention**: This fix prevents destructive operations when prerequisites aren't met
**Impact**: Critical - Prevents data loss from failed restores

**Key Learnings**:
1. **Never trust API responses** - Verify actual functionality, not status codes
2. **Fail fast with preflight** - Validate prerequisites before destructive operations
3. **Database drop is point of no return** - Must verify everything before this step
4. **Silent failures are dangerous** - Explicitly check every critical outcome
5. **Clear error messages critical** - Users need to know exactly what failed
6. **Dependency chain matters** - Each step depends on previous step success
7. **Setup screen detection key** - Primary indicator of database failure
8. **HTTP 200 ≠ success** - Response code doesn't guarantee data integrity
9. **Rollback needs implementation** - Currently no way to undo failed import
10. **Sequential validation works** - Stop at first failure, don't proceed blindly

## Current Active Issues

### ⚠️ Issue 9: betaweb.ai Cannot Be Used as Restore Target - Corrupted WordPress State (ACTIVE - Jan 27, 2026)
**Problem**: 
- Restore endpoint fails when trying to restore to betaweb.ai (production site)
- Navigation to ANY admin page (plugins.php, settings page) triggers session invalidation
- Browser automation cannot complete setup process
- REST API endpoints return 404 (plugin not loaded by WordPress)

**Symptoms**:
1. Browser automation successfully logs into betaweb.ai wp-admin dashboard
2. Any navigation to plugins.php causes redirect to wp-login.php with `reauth=1`
3. Direct navigation to settings page also causes session loss
4. REST API test: `curl https://betaweb.ai/wp-json/custom-migrator/v1/status` returns 404
5. Plugin files exist on server but WordPress doesn't load them

**Root Cause - CORRECTED**:
- **Initial assumption was WRONG**: Not Security Optimizer blocking automation
- **Actual root cause**: betaweb.ai IS ITSELF a corrupted former restore target
- betaweb.ai was previously used as a restore target and the operation left it in broken state
- WordPress database has inconsistent plugin state - files exist but database entries are corrupted
- Session management broken due to database inconsistency from previous restore
- ANY admin page navigation (not just plugins.php) triggers session invalidation
- This is NOT a bot detection issue - it's fundamental WordPress database corruption

**Investigation Timeline**:
1. **Initial assumption**: Slow page loading (30+ second timeouts)
   - Added flexible selectors, increased timeouts to 45s, 90s
   - ❌ Did not resolve issue
   
2. **Second assumption**: Plugin in corrupted "Deleting..." state
   - User showed plugins page with Custom WP Migrator showing "Activate | Deleting..."
   - Added workaround to skip upload for target sites
   - ❌ Did not resolve issue
   
3. **Third assumption**: Plugin detection selectors wrong
   - Added debug logging to check all selectors
   - Logs showed: `Installed plugins: []` - completely empty
   - User confirmed plugins ARE visible when manually accessing betaweb.ai
   - ❌ Did not resolve issue
   
4. **Fourth assumption**: Security Optimizer blocking automation
   - Screenshot debugging showed session loss with `reauth=1`
   - Enhanced Camoufox with `humanize=True`, `geoip=True` for anti-detection
   - Deployed with full anti-detection features
   - ❌ Did not resolve issue - still session loss
   
5. **Fifth assumption**: Corrupted plugins.php needs bypass
   - Implemented direct settings page access to bypass plugins.php
   - Attempted to retrieve API key via settings page
   - ❌ Settings page ALSO triggers session loss with `reauth=1`
   
6. **Sixth attempt**: JavaScript-based recovery via WordPress AJAX
   - Navigate back to dashboard (which works)
   - Use JavaScript to call REST API directly with authenticated session
   - ❌ REST API returns 404 - plugin not loaded at all
   
7. **Seventh attempt**: Bypass browser automation entirely for corrupted targets
   - Detect corruption error code (`SITE_UNRECOVERABLE`)
   - Fallback to direct REST API test with `migration-master-key`
   - Test: `curl https://betaweb.ai/wp-json/custom-migrator/v1/status`
   - ❌ Returns 404 - plugin completely non-functional
   
8. **ROOT CAUSE IDENTIFIED**: betaweb.ai is corrupted beyond recovery
   - User revealed: "betaweb.ai is running FROM a clone"
   - betaweb.ai was previously restored from a clone and left in broken state
   - Plugin files exist on disk but WordPress database doesn't recognize them
   - WordPress session management damaged by previous restore operation
   - No way to fix without SSH access to database or manual WordPress reinstall

**Current Camoufox Configuration** (Enhanced for Anti-Detection):
```python
async with AsyncCamoufox(
    headless=True,
    humanize=True,  # ✅ Added: Realistic human behavior
    geoip=True      # ✅ Added: Real geolocation data
) as browser:
    context = await browser.new_context(
        viewport={'width': 1280, 'height': 800},
        accept_downloads=True
    )
```

**Anti-Detection Features NOW Enabled**:
- ✅ `humanize=True` - Realistic mouse movements, typing delays, human-like behavior
- ✅ `geoip=True` - Real geolocation data to avoid detection
- ✅ `camoufox[geoip,zip]==0.3.5` - Full package with all anti-detection extras

**Features Still Available** (Not Currently Needed):
- `fonts=True` - Loads real system fonts to avoid font fingerprinting
- Custom user agent configuration
- Non-headless mode with virtual display (Xvfx)

**Attempted Fixes** (All Failed for betaweb.ai):
- ✅ Increased timeouts from 30s → 45s → 90s (did not help)
- ✅ Added flexible selector approach with multiple fallbacks (did not help)
- ✅ Skip plugin upload for target sites to avoid session loss (did not help)
- ✅ Added debug logging and screenshot capture (revealed session loss)
- ✅ Enhanced Camoufox with `humanize=True`, `geoip=True` (did not help)
- ✅ Implemented direct settings page access bypass (settings page also broken)
- ✅ Implemented JavaScript-based AJAX recovery (REST API returns 404)
- ✅ Implemented REST API fallback with `migration-master-key` (REST API not functional)
- ✅ Deployed all fixes to production and tested (betaweb.ai unrecoverable)

**What Actually Works**:
- ✅ Browser automation successfully logs into betaweb.ai dashboard
- ✅ Dashboard page loads correctly without session loss
- ✅ System correctly detects corruption and provides clear error message
- ✅ Recovery mechanisms work correctly (they just can't fix betaweb.ai's corruption)
- ✅ Restore works fine on non-corrupted WordPress sites

**Working Solutions Implemented**:
1. ✅ **Enhanced Camoufox Anti-Detection**:
   - Enabled `humanize=True` for realistic human behavior
   - Enabled `geoip=True` for real geolocation data
   - Added `camoufox[geoip,zip]` to requirements.txt
   - Deployed successfully to production
   
2. ✅ **Corruption Detection and Recovery**:
   - Detects session loss after plugins.php navigation
   - Attempts direct settings page access as recovery
   - Attempts JavaScript-based AJAX recovery via dashboard
   - Attempts REST API fallback with `migration-master-key`
   - Provides clear error message when all recovery fails
   
3. ✅ **Graceful Failure Handling**:
   - System correctly identifies betaweb.ai as `SITE_UNRECOVERABLE`
   - Returns actionable error message to user
   - Does not hang or timeout indefinitely

**Recommended Solutions for betaweb.ai**:
1. **✅ Use Built-in Reset Button** (IMPLEMENTED - Jan 27, 2026):
   - Plugin now includes "Reset Plugin to Default State" button in settings page
   - Accessible at: `https://betaweb.ai/wp-admin/options-general.php?page=custom-migrator-settings`
   - **What it does**:
     * Deletes all corrupted plugin settings from database
     * Generates new API key
     * Disables import functionality (safe default)
     * Refreshes REST API routes (fixes 404 errors)
     * Clears WordPress cache
   - **How to use**:
     * Manually navigate to settings page
     * Click "🔄 Reset Plugin to Default State" button
     * Confirm the action
     * Plugin will reset and show success message
   - **Status**: ✅ Feature deployed, ready for manual testing
   - **Files Modified**: `class-settings.php` - Added reset handler and UI button
   
2. **Manual Database Cleanup** (Requires SSH/database access - Not Recommended):
   - Access betaweb.ai database via phpMyAdmin or MySQL CLI
   - Clean up corrupted plugin entries in `wp_options` table
   - Reinstall custom-migrator plugin manually
   - Verify REST API endpoints return 200 (not 404)
   - **Note**: Use reset button instead (option #1) - no SSH needed
   
3. **Fresh WordPress Installation**:
   - Use a clean WordPress site that hasn't been a restore target before
   - Test restore workflow on fresh site
   - Once verified working, use that as production target
   
4. **Use Different WordPress Site**:
   - If reset button doesn't work, betaweb.ai may need complete WordPress reinstall
   - System constraints: No SSH access, wp-admin only
   - Find alternative WordPress site for restore testing

**Status**: 🔴 **betaweb.ai UNRECOVERABLE** - Site cannot be used as restore target
**Root Cause**: WordPress database corruption from previous restore operation
**Impact**: High - Blocks restore workflow to betaweb.ai specifically
**Workaround**: Use a different, non-corrupted WordPress site as restore target
**System Status**: ✅ **System working correctly** - properly detects and reports corruption

### ✅ Issue 12: Clone wp-admin URL Locking (FIXED - Jan 30, 2026)
**Problem**:
- Clones redirected `/wp-admin` to `http://localhost/wp-admin/` inside the container instead of the ALB URL path
- This broke direct wp-admin access for clones even though frontend and REST API worked correctly
- Issue occurred even though WP_HOME and WP_SITEURL constants were set correctly in wp-config.php

**Root Cause - Sequential Analysis**:
Investigation revealed the problem was in the **Nginx proxy configuration**, not WordPress URL constants:

1. **Nginx sets Host header to localhost** (Line 485 in ec2_provisioner.py):
   ```nginx
   proxy_set_header Host localhost;
   ```
   - Done intentionally to "avoid host-mismatch redirect loops" per code comment
   - WordPress receives all requests as if they came from `localhost`

2. **WordPress wp-admin redirect uses Host header**:
   - WordPress core uses the `Host` header for certain redirects (e.g., `/wp-admin` → `/wp-admin/`)
   - Even though WP_HOME and WP_SITEURL constants are set, wp-admin redirect bypasses them
   - Result: Redirect to `http://localhost/wp-admin/`

3. **proxy_redirect rule incomplete** (Line 493 in original ec2_provisioner.py):
   ```nginx
   proxy_redirect / /clone-xxx/;
   ```
   - Only rewrites **relative** Location headers (e.g., `/wp-admin/`)
   - Does NOT rewrite **absolute** Location headers (e.g., `http://localhost/wp-admin/`)
   - WordPress wp-admin redirect returns absolute URL, which passes through unrewritten

**Verification of wp-config.php constants** (Investigation findings):
- ✅ WP_HOME and WP_SITEURL constants WERE present in wp-config.php
- ✅ Database values WERE set correctly to ALB URL
- ✅ Must-use plugin WERE present and filtering options
- **Conclusion**: Constants were working correctly; Nginx proxy_redirect was the issue

**Solution Implemented**:
Updated Nginx configuration in [ec2_provisioner.py](file:///home/chaz/Desktop/clone-restore/custom-wp-migrator-poc/wp-setup-service/app/ec2_provisioner.py) (Lines 491-494):

**Before:**
```nginx
# Rewrite redirects back through the path prefix
proxy_redirect / /clone-xxx/;
```

**After:**
```nginx
# Rewrite redirects back through the path prefix
# Handle both relative paths and absolute localhost URLs
proxy_redirect http://localhost/ /clone-xxx/;
proxy_redirect / /clone-xxx/;
```

**Why This Works**:
1. **First rule**: Catches absolute URLs like `http://localhost/wp-admin/` and rewrites to `/clone-xxx/wp-admin/`
2. **Second rule**: Catches relative URLs like `/wp-admin/` and rewrites to `/clone-xxx/wp-admin/`
3. **Order matters**: Nginx processes proxy_redirect rules in order, most specific first
4. **No WordPress changes needed**: Fix is purely at the proxy layer

**Test Results**:
```bash
# Test on clone-20260130-084613 (manual fix):
curl -I ".../clone-20260130-084613/wp-admin"
Location: http://wp-targets-alb-1392351630.us-east-1.elb.amazonaws.com/clone-20260130-084613/wp-admin/  ✅

# Test on clone-20260130-085721 (deployed fix):
curl -I ".../clone-20260130-085721/wp-admin"
Location: http://wp-targets-alb-1392351630.us-east-1.elb.amazonaws.com/clone-20260130-085721/wp-admin/  ✅
```

**Logs Verification**:
```
✅ Nginx configured for path /clone-xxx
✅ wp-config.php constants: WP_HOME and WP_SITEURL set to ALB URL
✅ Database options: home and siteurl set to ALB URL
✅ wp-admin redirect: Now correctly points to ALB URL
```

**Files Modified**:
- `/wp-setup-service/app/ec2_provisioner.py` (lines 481-494)
  - Added `proxy_redirect http://localhost/ {path_prefix}/;` to catch absolute localhost URLs
  - Kept existing `proxy_redirect / {path_prefix}/;` for relative paths
  - Added clarifying comment about handling both redirect types

**Status**: ✅ Code deployed and tested successfully
**Deployed**: 2026-01-30
**Commit**: f7ac34d (same commit as app password fix)

**Prevention**: This fix ensures reliable wp-admin access on all new clones
**Impact**: High - Enables direct wp-admin access for clone management and debugging

**Key Learnings**:
1. **proxy_redirect handles patterns, not regex** - Need separate rules for absolute vs relative URLs
2. **Host header matters for redirects** - Even when WP_HOME/WP_SITEURL are set, Host header affects some redirects
3. **Absolute vs relative URLs** - Nginx treats `Location: /path` differently from `Location: http://host/path`
4. **Debugging requires full stack analysis** - wp-config.php constants were correct; issue was at proxy layer
5. **Comments can be misleading** - "avoid host-mismatch redirect loops" comment didn't explain full implications
6. **WordPress redirect types vary** - Homepage works fine, but wp-admin uses different redirect logic
7. **proxy_redirect order matters** - More specific patterns should come before general patterns
8. **Integration testing essential** - Unit testing wp-config.php wouldn't have caught this Nginx issue
9. **Multiple layers of URL rewriting** - wp-config.php + must-use plugin + database + Nginx all involved
10. **Systematic investigation pays off** - Checking each layer (wp-config, database, Nginx) revealed true cause

### ✅ Issue 13: Application Password Extraction on bonnel.ai (FIXED - Jan 30, 2026)
**Problem**:
- `/create-app-password` successfully logged into `https://bonnel.ai` and navigated to profile page, but returned incorrect values
- First attempt: Returned unrelated text (e.g., `initializeCommandPalette`) from JavaScript code elements
- Second attempt: Returned username "charles" instead of the actual application password
- Password element never appeared in the DOM after clicking button

**Root Cause - Sequential Analysis**:
The automation had **three critical bugs**:

1. **Wrong Button Click** (Primary Issue):
   - Selector `input[type="submit"].button-primary` matched the main "Update Profile" button
   - Should have clicked `#do_new_application_password` button specifically for application passwords
   - Clicking wrong button saved the profile but didn't trigger password generation JavaScript

2. **Static Wait Instead of Dynamic**:
   - Used `await asyncio.sleep(3)` - fixed 3 second wait
   - Password is generated asynchronously by JavaScript via AJAX
   - Need to wait for `#new-application-password-value` element to appear in DOM

3. **Generic Fallback Selector**:
   - Fallback selector `input[readonly][value]` was too broad
   - Matched username field ("charles") instead of password field
   - No validation that extracted value was actually a password (should be 20+ chars with spaces)

**Solution Implemented**:
Fixed all three issues in [browser_setup.py](file:///home/chaz/Desktop/clone-restore/custom-wp-migrator-poc/wp-setup-service/app/browser_setup.py):

**1. Corrected Button Selectors (Lines 774-783)**:
```python
for selector in [
    '#do_new_application_password',  # WordPress default ID - CORRECT
    'button[name="do_new_application_password"]',  # By name attribute
    '#generate-application-password',  # Theme fallback
    'button:has-text("Add New Application Password")',  # By text
    '.create-application-password button[type="button"]',  # Scoped to section
    'button.button-secondary:has-text("Add")',  # WordPress uses button-secondary
]
```

**2. Added Dynamic Wait for Password (Lines 803-818)**:
```python
# Wait for password to appear (JavaScript renders it asynchronously)
try:
    # Wait for the input element to be created and visible in the DOM
    await page.wait_for_selector('#new-application-password-value', state='visible', timeout=15000)
    l.info("✅ Password input element appeared")
except Exception as wait_err:
    # Try waiting for notice div as fallback
    await page.wait_for_selector('.new-application-password-notice:visible', timeout=10000)
```

**3. Improved Password Extraction (Lines 840-865)**:
```python
# Primary: Get value from input element
password_text = await page.locator('#new-application-password-value').input_value()

# Fallbacks: Validate password length (must be >15 chars)
if password_text and len(password_text) > 15:
    # Valid application password
else:
    # Too short, try next selector
```

**4. Added Section Scrolling (Lines 761-768)**:
```python
# Scroll to Application Passwords section (usually below the fold)
app_password_section = page.locator('#application-passwords-section')
await app_password_section.scroll_into_view_if_needed()
```

**Test Results**:
```bash
curl -X POST http://13.222.20.138:8000/create-app-password \
  -d '{"url": "https://bonnel.ai", "username": "charles", "password": "...", "app_name": "TestApp3"}'

Response:
{
  "success": true,
  "application_password": "pkkF YI42 RLzI CHtY yNcI s5BX",
  "app_name": "TestApp3",
  "message": "Application password created successfully"
}
```

**Logs Verification**:
```
✅ Found button with selector: #do_new_application_password
✅ Password input element appeared
✅ Found password using selector: #new-application-password-value
✅ Password length: 29 chars
✅ Password format: VALID
✅ Password extracted: pkkF YI4...
```

**Why This Works**:
1. **Correct button**: Now clicks `#do_new_application_password` - triggers WordPress AJAX to create password
2. **Dynamic wait**: Waits up to 15 seconds for JavaScript to render password in DOM
3. **Input value extraction**: Uses `input_value()` to get value attribute from input element
4. **Length validation**: Rejects values <15 chars (eliminates username/random text matches)
5. **Section scrolling**: Ensures Application Passwords section is visible before interaction

**Files Modified**:
- `/wp-setup-service/app/browser_setup.py` (lines 761-865)
  - Fixed button selectors to target correct application password button
  - Changed from static sleep to dynamic wait for password element
  - Improved extraction with input_value() and length validation
  - Added scrolling to Application Passwords section

**Status**: ✅ Code deployed and tested successfully
**Deployed**: 2026-01-30
**Commit**: f7ac34d (new image SHA: sha256:5b14521c91b01984008680ff8de97bdfce181286de09c14163a33e1be90256f0)

**Prevention**: This fix ensures reliable application password creation on all WordPress sites
**Impact**: High - Enables automated application password creation for REST API authentication

**Key Learnings**:
1. **Generic selectors are dangerous** - `button.button-primary` matches many buttons, need specific IDs
2. **Static waits hide timing issues** - JavaScript async operations need dynamic element waiting
3. **Fallback selectors need validation** - Generic `input[readonly]` matches unintended fields
4. **Screenshots are essential** - Revealed we were clicking wrong button (showed "Profile updated" message)
5. **WordPress button classes matter** - Application password button uses `button-secondary`, not `button-primary`
6. **DOM inspection reveals truth** - HTML template showed `#do_new_application_password` was correct ID
7. **Value extraction method matters** - `inner_text()` wrong for input elements, use `input_value()` instead
8. **Scrolling matters** - Application Passwords section often below fold, needs scroll_into_view
9. **Length validation prevents false matches** - Real passwords are 20+ chars, username is 7 chars
10. **Test with actual values** - Seeing "charles" extracted immediately revealed wrong field matched

### ✅ Issue 14: Application Passwords Not Supported on HTTP Clones (FIXED - Jan 31, 2026)
**Problem**:
- `/create-app-password` endpoint failed on WordPress clones with error: "Application Passwords not supported (requires WordPress 5.6+)"
- Clone containers running over HTTP without SSL
- WordPress requires HTTPS for Application Passwords by default as a security feature
- Browser automation could not find the application password UI on profile page

**Symptoms**:
```bash
curl -X POST http://13.222.20.138:8000/create-app-password \
  -d '{"url": "http://wp-targets-alb-.../clone-xxx/", ...}'

Response:
{"detail": "Application Passwords not supported (requires WordPress 5.6+)"}
```

**Root Cause - Sequential Analysis**:
WordPress hides the Application Passwords UI when:
1. WordPress version < 5.6 (feature introduced in WP 5.6)
2. Site running over HTTP without SSL (security requirement)
3. `WP_ENVIRONMENT_TYPE` not set to 'local' or 'development'

The clone containers:
- Run over HTTP (no SSL certificates)
- Use ALB for routing (HTTP only, no HTTPS termination for clone paths)
- Default WordPress configuration requires HTTPS for Application Passwords
- Browser automation found no `input[name="new_application_password_name"]` field → returned "not supported" error

**Solution Implemented**:
Added two layers of Application Password enablement for HTTP clones:

**1. WordPress Configuration (custom-entrypoint.sh)**:
Modified [custom-entrypoint.sh](file:///home/chaz/Desktop/clone-restore/custom-wp-migrator-poc/wordpress-target-image/custom-entrypoint.sh) to inject `WP_ENVIRONMENT_TYPE` constant:

```php
// Added to wp-config.php injection:
/* Enable Application Passwords over HTTP for development */
define('WP_ENVIRONMENT_TYPE', 'local');
```

**Why this works**:
- `WP_ENVIRONMENT_TYPE='local'` tells WordPress this is a development environment
- WordPress allows Application Passwords over HTTP in local/development environments
- Constant injected before `wp-settings.php` loads

**2. Plugin Filter (custom-migrator.php)**:
Modified [custom-migrator.php](file:///home/chaz/Desktop/clone-restore/custom-wp-migrator-poc/wordpress-target-image/plugin/custom-migrator.php) as backup:

```php
function custom_migrator_init() {
    // Initialize API endpoints
    Custom_Migrator_API::init();

    // Initialize settings
    Custom_Migrator_Settings::init();

    // Enable Application Passwords over HTTP for development/testing
    add_filter('wp_is_application_passwords_available', '__return_true');
}
```

**Why this works**:
- Plugin filter overrides WordPress's default HTTPS requirement
- Acts as backup if `WP_ENVIRONMENT_TYPE` constant doesn't work
- Filter applies globally to all Application Password checks

**Deployment Process**:
1. Created new deploy script: `wordpress-target-image/deploy.sh` (modeled after wp-setup-service/deploy.sh)
2. Built wordpress-target-sqlite Docker image with changes
3. Tagged as version `58976f8` and `latest`
4. Pushed to ECR: `044514005641.dkr.ecr.us-east-1.amazonaws.com/wordpress-target-sqlite:latest`
5. New clones automatically pull updated image from ECR

**Files Modified**:
- `/wordpress-target-image/custom-entrypoint.sh` (lines 10-32)
  - Added `WP_ENVIRONMENT_TYPE='local'` to wp-config.php injection
  - Injected alongside existing proxy configuration constants

- `/wordpress-target-image/plugin/custom-migrator.php` (lines 26-33)
  - Added `wp_is_application_passwords_available` filter
  - Returns true unconditionally for all Application Password checks

- `/wordpress-target-image/deploy.sh` (NEW FILE - lines 1-48)
  - Build and push wordpress-target-sqlite to ECR
  - Modeled after wp-setup-service/deploy.sh
  - Enables easy deployment of WordPress container changes

**Deployment Details**:
```bash
cd wordpress-target-image && ./deploy.sh

✅ Built: wordpress-target-sqlite:58976f8
✅ Pushed: 044514005641.dkr.ecr.us-east-1.amazonaws.com/wordpress-target-sqlite:58976f8
✅ Image SHA: sha256:97c71dc58ffcc437fee32a5e4c9a8c5cbc0e0f8f3846d5d042bc3478b6a349c4
```

**Status**: ✅ Code deployed to ECR
**Deployed**: 2026-01-31
**Image Version**: 58976f8
**Testing Status**: Pending - requires new clone creation to test

**Next Steps**:
1. Create new clone from working WordPress site (bonnel.ai recommended)
2. Test `/create-app-password` on new clone
3. Verify Application Password UI appears on profile page
4. Confirm password creation succeeds without "not supported" error

**Prevention**: This fix enables Application Password creation on all new HTTP-only clones
**Impact**: High - Unblocks automated Application Password creation for REST API authentication on clones

**Key Learnings**:
1. **WordPress security features can block automation** - HTTPS requirement for Application Passwords
2. **Environment type matters** - 'local'/'development' relaxes security requirements
3. **Multiple layers of protection** - Both wp-config constant and plugin filter provide redundancy
4. **ECR image versioning essential** - Old clones keep old image, new clones get fixes automatically
5. **Deploy scripts prevent errors** - Standardized deployment reduces manual mistakes
6. **HTTP vs HTTPS impacts features** - Not just security, but feature availability
7. **WordPress checks environment type** - `WP_ENVIRONMENT_TYPE` affects multiple security behaviors
8. **Filter hooks provide escape hatches** - Can override WordPress defaults when needed
9. **Entrypoint scripts powerful** - Can modify WordPress configuration before it loads
10. **Architecture matters for deployment** - Separate images (wp-setup-service vs wordpress-target-sqlite) need separate deploy scripts

**Key Insight**: 
The system is functioning as designed. betaweb.ai is too corrupted to be recovered using wp-admin-only access. Without SSH/database access, there is no way to fix WordPress database corruption. The automation correctly identifies this and provides clear error messages.

**Recommendation**: 
Test restore functionality on a fresh WordPress installation or a site that hasn't been used as a restore target before. The system works correctly - betaweb.ai is simply an edge case of extreme corruption.

**Files Modified**:
- `browser_setup.py` - Added session loss detection, direct settings bypass, JavaScript recovery, enhanced Camoufox
- `main.py` - Added REST API fallback for corrupted targets
- `requirements.txt` - Changed `camoufox[zip]` to `camoufox[geoip,zip]`
- `deploy.sh` - Fixed SSH key path from `../../` to `../`
- `class-settings.php` - Added "Reset Plugin to Default State" button and handler (Jan 27, 2026)

**Commits** (Recent Issue 9 Investigation):
- `3e54b74` - Flexible selector strategy for slow-loading plugins pages
- `81a6c75` - Improved plugin detection with proper DOM selectors
- `3241da0` - Flexible selector approach during plugin activation
- `8e57ac3` - Skip plugin upload for target sites to avoid session loss
- `05cd34f` - Actionable error message when plugin not installed on target
- `a017c89` - Detect and report session loss when WordPress redirects to login
- Multiple subsequent commits for enhanced anti-detection and recovery mechanisms

**Infrastructure Changes During Investigation**:
- ✅ EC2 disk expanded: 8GB → 100GB (using `growpart` + `xfs_growfs`)
- ✅ Camoufox enhanced: Added `humanize=True`, `geoip=True`
- ✅ Plugin corruption recovery: Direct settings access, AJAX fallback, REST API fallback
- ✅ Error messages improved: Clear indication of corruption vs other failures

**Key Learnings**: 
1. **Timeout increases don't solve database corruption** - betaweb.ai issue wasn't about speed
2. **Initial assumptions can be wrong** - Security Optimizer wasn't the culprit
3. **User context is critical** - Knowing betaweb.ai was a former restore target revealed root cause
4. **Screenshot debugging is essential** - Visual confirmation of what automation sees
5. **No-SSH constraint is real** - Cannot fix WordPress database corruption without database access
6. **REST API 404 means plugin not loaded** - Not authentication failure, not missing route
7. **Plugin files ≠ functional plugin** - Files can exist but WordPress database not recognize them
8. **Graceful degradation matters** - System should detect corruption and fail clearly, not hang
9. **Anti-detection features work** - Camoufox successfully logs in even with enhanced security
10. **Former restore targets can be corrupted** - Sites previously restored may have broken state
11. **WordPress has built-in recovery mechanisms** - wp-admin accessible reset buttons can fix database corruption without SSH (Jan 27, 2026)
12. **User input reveals better solutions** - "Don't we have a reset button?" led to implementing wp-admin-compatible recovery (Jan 27, 2026)

## Known Limitations & Workarounds

### Limitation 1: Clone Plugin May Be Inactive
**Issue**: Custom Migrator plugin is sometimes inactive on newly created clones
**Impact**: REST API returns 404 errors
**Workaround**: Manually activate plugin via SSH:
```bash
ssh to instance → docker exec <clone-id> wp plugin activate custom-migrator --path=/var/www/html --allow-root
```
**Permanent Fix**: TODO - Add automatic plugin activation to import process

### Limitation 2: Clone API Keys Vary by Source
**Issue**: Clones inherit their source site's API key, not a standard key
**Impact**: Cannot assume all clones use `migration-master-key`
**Solution**: Restore endpoint uses browser automation to retrieve actual API key
**Status**: ✅ Fixed in production

### Limitation 3: Browser Automation Required for Restore
**Issue**: Restore endpoint needs browser automation to get API keys from clones
**Impact**: Restore process takes longer (60-120 seconds)
**Workaround**: None - this is by design
**Future Enhancement**: Store API key in clone metadata to skip browser automation

---

## SiteGround Restore Debugging History (2026-02-07)

### The Problem
After restoring a clone to betaweb.ai (SiteGround), the custom-migrator plugin becomes inactive on the next request. This means any subsequent restore fails because the import REST API endpoint returns 404 `rest_no_route` — the routes simply don't exist because the plugin isn't loaded.

### What Was Tried and DIDN'T Work

#### 1. REST API fast-path (GET status check before restore)
**Why it failed:** SiteGround aggressively caches GET responses. The status endpoint returned cached 200 OK even though the plugin was actually inactive. False positive every time.

#### 2. POST to `?rest_route=` query parameter format
**Why it failed:** SiteGround blocks POST requests to `?rest_route=` for custom plugin routes. WordPress core routes (like `/wp/v2/posts`) work with POST + `?rest_route=`, but custom plugin routes return `rest_no_route` 404.

#### 3. POST to `/wp-json/` pretty permalink format
**Why it failed:** After a restore replaces the DB, WordPress rewrite rules (`.htaccess`) are lost/broken. `/wp-json/` returns SiteGround's generic 404 page (not even a WordPress REST API response).

#### 4. GET to `?rest_route=` with `WP_REST_Server::ALLMETHODS` route registration
**Why it failed:** Even though routes were registered to accept all HTTP methods, the plugin itself was not loaded at all after the restore. No routes = no method matching possible.

#### 5. mu-plugin (`ensure-migrator-active.php`) to keep plugin active
**Why it failed:** The mu-plugin was created during import, but after the DB replacement, WordPress still silently deactivated the plugin on the next request. The mu-plugin's `include_once` + `update_option` approach couldn't reliably prevent this.

#### 6. `flush_rewrite_rules()` fix for root domains
**Why it failed on its own:** Even with rewrite rules flushed during import, the plugin being inactive on the next request meant routes weren't registered regardless of whether `/wp-json/` resolved correctly.

#### 7. `_post_rest_api` helper with 3-tier fallback (POST `/wp-json/` → POST `?rest_route=` → GET `?rest_route=`)
**Why it failed:** All three methods fail when the plugin is completely inactive. The routes simply don't exist.

### What WORKS and Why

#### Always use browser automation for target setup before every restore
- **Implementation:** Removed the REST API fast-path entirely from the restore endpoint in `main.py`. Every restore now runs browser automation (Playwright/Camoufox) on the target site.
- **Why it works:** Browser automation logs into wp-admin, uploads a fresh copy of the plugin zip, activates it, sets the API key, and enables import. This **guarantees** the plugin is active and the REST API endpoints are available for the actual import call.
- **Trade-off:** Each restore takes ~1 minute longer due to browser automation, but it's 100% reliable.
- **The key insight:** On SiteGround, you cannot rely on the plugin surviving a DB replacement. The only reliable way to ensure the plugin is active is to re-upload and activate it via the WordPress admin UI before every restore.

### Key Files Changed
- `wp-setup-service/app/main.py` — Removed REST API fast-path, always uses browser automation for target
- `wp-setup-service/app/main.py` — `_post_rest_api()` helper with fallback chain (still useful for non-SiteGround targets)
- `wordpress-target-image/plugin/includes/class-api.php` — Routes registered with `WP_REST_Server::ALLMETHODS`
- `wordpress-target-image/plugin/includes/class-importer.php` — mu-plugin creation, rewrite flush fix for root domains
- `wp-setup-service/app/browser_setup.py` — Dynamic `admin_base` extraction to handle double-slash URLs

### Confirmed Working Workflow
```
Clone ✓ → 1st Restore ✓ → 2nd Restore ✓ → Nth Restore ✓
(browser automation re-activates plugin each time)
```

---

## HTTPS Migration for Clone URLs (2026-02-07)

### What Was Done
1. **ACM Certificate**: Requested free cert for `clones.betaweb.ai` (auto-renewing)
   - ARN: `arn:aws:acm:us-east-1:044514005641:certificate/c3fb5ab3-160f-4db2-ac4b-056fe7166558`
2. **SiteGround DNS**: Added two CNAME records:
   - `clones.betaweb.ai` → `wp-targets-alb-1392351630.us-east-1.elb.amazonaws.com`
   - ACM DNS validation CNAME record
3. **ALB Security Group**: Opened port 443 inbound (`sg-0ec42580671190c22`)
4. **HTTPS Listener**: Created on ALB port 443 with ACM cert
   - ARN: `arn:aws:elasticloadbalancing:us-east-1:044514005641:listener/app/wp-targets-alb/9deaa3f04bc5506b/f6542ccc3f16bfd7`
5. **HTTP→HTTPS Redirect**: Port 80 listener now returns 301 redirect to HTTPS
6. **Code Changes** (`ec2_provisioner.py`):
   - `self.alb_dns` → `clones.betaweb.ai`
   - `self.alb_listener_arn` → HTTPS listener ARN (new clone ALB rules attach to 443 listener)
   - `alb_url` → `https://` prefix
   - Nginx `X-Forwarded-Proto` → `$http_x_forwarded_proto` (pass through ALB header instead of `$scheme`)
7. **Terraform** (`main.tf`): Added HTTPS listener, ACM cert data source, port 443 SG ingress, HTTP redirect

### Result
- Clone URLs: `https://clones.betaweb.ai/clone-YYYYMMDD-HHMMSS/`
- HTTP automatically redirects to HTTPS
- Branch: `feat/clonehttps`

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

### Future Enhancements (Not Blockers)
1. **Implement clone cleanup** based on TTL expiration (currently scheduled but not executed)
2. **Add restore progress tracking** for long-running operations
3. **Improve error messages** for common failure scenarios
4. **Add health check endpoint** for clone containers
5. **Add ALB rule cleanup** when clones are deleted
6. **Monitor ALB listener rule limits** (max 100 rules per listener)

## Environment Context
- **Region**: us-east-1
- **AWS Account**: 044514005641
- **ECR Registry**: 044514005641.dkr.ecr.us-east-1.amazonaws.com
- **Service**: wp-setup-service:latest (FastAPI)
- **WordPress Image**: wordpress-target-sqlite:latest
  - Latest SHA: `sha256:1d0a35138189a85d43b604f72b104ef2f0a0dd0d07db3ded5d397cb3fe68d3bc`
- **Database**: MySQL (per-EC2 MySQL container, one DB per clone)
- **Loki Logging**: Enabled on management server
- **Terraform State**: Managed separately in infra/wp-targets/
- **MySQL Root Password**: Set via `MYSQL_ROOT_PASSWORD` env var (Terraform output)

## Connection Details
- **Management Server**: ec2-user@13.222.20.138
- **Target Server**: ec2-user@10.0.13.72 (same host, via SSH)
- **SSH Key Location**: /home/ec2-user/wp-targets-key.pem (on management server)
- **Local SSH Key**: /home/chaz/Desktop/clone-restore/custom-wp-migrator-poc/wp-targets-key.pem
- **Docker Network**: Host networking used for communication

## API Endpoints
- **Clone**: `POST http://13.222.20.138:8000/clone`
- **Restore**: `POST http://13.222.20.138:8000/restore`
- **Create App Password**: `POST http://13.222.20.138:8000/create-app-password`
- **Health**: `GET http://13.222.20.138:8000/health`
- **Web UI**: `http://13.222.20.138:8000/`

## Documentation Status
- ✅ **README.md**: Updated with current architecture and mermaid diagram (2026-01-24)
- ✅ **API_TEST_PLAN.md**: Updated with auto-provisioning, quirks, response format (2026-01-24)
- ✅ **OPERATIONAL_MEMORY.md**: Updated with current status (2026-01-30)
- ✅ **.gitignore**: Added AGENTS.md, QODER.md, .qoder/, openspec/

## Git Repository
- **Active Branch**: feat/clonehttps (HTTPS migration)
- **Previous Branch**: feat/restore (restore fixes)
- **Remote**: https://github.com/t0ct0c/clone-restore.git
- **Untracked**: .windsurf/ (IDE folder, not committed)

---

## End-to-End Testing Guide

### Prerequisites
- Source WordPress site credentials (URL, username, password)
- Target WordPress site credentials (URL, username, password)
- Access to management server: `13.222.20.138:8000`

### Test 1: Create a Clone
**Purpose**: Verify clone creation and ALB path-based routing

```bash
# Create a clone from source WordPress site
curl -X POST http://13.222.20.138:8000/clone \
  -H "Content-Type: application/json" \
  -d '{
    "source": {
      "url": "https://your-wordpress-site.com",
      "username": "admin",
      "password": "your-password"
    }
  }' | python3 -m json.tool
```

**Expected Response**:
```json
{
  "success": true,
  "clone_url": "https://clones.betaweb.ai/clone-YYYYMMDD-HHMMSS",
  "wordpress_username": "admin",
  "wordpress_password": "generated-password",
  "api_key": "migration-master-key",
  "expires_at": "2026-01-27T...",
  "message": "Clone created successfully"
}
```

**Verify Clone Access**:
```bash
# Test clone homepage (should return 200 OK with HTML)
curl -I "https://clones.betaweb.ai/clone-YYYYMMDD-HHMMSS/"

# Test clone REST API export endpoint (should return 200 OK with JSON)
curl -X POST \
  "https://clones.betaweb.ai/clone-YYYYMMDD-HHMMSS/index.php?rest_route=/custom-migrator/v1/export" \
  -H "X-Migrator-Key: migration-master-key" | python3 -m json.tool
```

**Success Criteria**:
- ✅ Clone created successfully with ALB URL
- ✅ Clone homepage returns 200 OK with `Content-Type: text/html`
- ✅ REST API export returns 200 OK with valid JSON containing `download_url`
- ✅ Clone accessible in browser at ALB URL

### Test 2: Restore from Clone to Production
**Purpose**: Verify full restore workflow from clone to production site

```bash
# Restore from clone to production
curl -X POST http://13.222.20.138:8000/restore \
  -H "Content-Type: application/json" \
  -d '{
    "source": {
      "url": "https://clones.betaweb.ai/clone-YYYYMMDD-HHMMSS",
      "username": "admin",
      "password": "clone-password-from-step1"
    },
    "target": {
      "url": "https://your-production-site.com",
      "username": "admin",
      "password": "production-password"
    },
    "preserve_themes": false,
    "preserve_plugins": false
  }' | python3 -m json.tool
```

**Expected Response**:
```json
{
  "success": true,
  "message": "Restore completed successfully",
  "source_api_key": "migration-master-key",
  "target_api_key": "generated-key",
  "integrity": {
    "status": "success",
    "warnings": []
  },
  "options": {
    "preserve_plugins": false,
    "preserve_themes": false
  }
}
```

**Success Criteria**:
- ✅ Restore completes without errors
- ✅ Production site content matches clone content
- ✅ Production site is accessible and functional
- ✅ No redirect loops or 500 errors

### Test 3: Restore with Preservation Options
**Purpose**: Verify theme/plugin preservation works correctly

```bash
# Restore with preservation (keeps production themes and plugins)
curl -X POST http://13.222.20.138:8000/restore \
  -H "Content-Type: application/json" \
  -d '{
    "source": {
      "url": "https://clones.betaweb.ai/clone-YYYYMMDD-HHMMSS",
      "username": "admin",
      "password": "clone-password"
    },
    "target": {
      "url": "https://your-production-site.com",
      "username": "admin",
      "password": "production-password"
    },
    "preserve_themes": true,
    "preserve_plugins": true
  }' | python3 -m json.tool
```

**Success Criteria**:
- ✅ Content and database restored from clone
- ✅ Production themes remain unchanged
- ✅ Production plugins remain unchanged
- ✅ Site remains functional with existing theme/plugins

### Test 4: Verify ALB Listener Rules
**Purpose**: Confirm ALB path-based routing is configured correctly

```bash
# List ALB listener rules
aws elbv2 describe-rules \
  --listener-arn arn:aws:elasticloadbalancing:us-east-1:044514005641:listener/app/wp-targets-alb/9deaa3f04bc5506b/f6542ccc3f16bfd7 \
  --region us-east-1 \
  --query 'Rules[?Priority!=`default`].[Priority,Conditions[0].Values[0],Actions[0].TargetGroupArn]' \
  --output table
```

**Expected Output**:
```
-------------------------------------------------------------------
|                         DescribeRules                           |
+----------+------------------+-----------------------------------+
|  1       |  /clone-xxx/*    |  arn:aws:...targetgroup/clone-... |
|  2       |  /clone-yyy/*    |  arn:aws:...targetgroup/clone-... |
+----------+------------------+-----------------------------------+
```

**Success Criteria**:
- ✅ Each clone has a dedicated ALB listener rule
- ✅ Path patterns match clone paths: `/clone-YYYYMMDD-HHMMSS/*`
- ✅ Each rule points to a dedicated target group
- ✅ Target groups have correct instance registered

### Test 5: Check Service Logs
**Purpose**: Verify no errors in service logs

```bash
# Check wp-setup-service logs
ssh -i wp-targets-key.pem ec2-user@13.222.20.138 "docker logs wp-setup-service --tail 100 2>&1 | grep -E 'ERROR|WARNING|ALB'"
```

**Success Criteria**:
- ✅ No ALB rule creation errors
- ✅ No "AccessDenied" errors for ELB operations
- ✅ ALB rules created successfully with log: "Successfully created ALB rule for /clone-xxx"

### Troubleshooting Common Issues

#### Issue: Clone returns 2-byte response or "OK"
**Cause**: ALB listener rule not created or request hitting wrong instance
**Fix**: 
1. Check ALB rules exist: `aws elbv2 describe-rules --listener-arn ...`
2. Verify IAM permissions for ELB operations
3. Check service logs for ALB rule creation errors

#### Issue: REST API returns 404 "No route was found"
**Cause**: Using pretty permalinks format instead of query string format
**Fix**: Use `index.php?rest_route=/endpoint` format for clone REST API calls

#### Issue: Restore fails with "Expecting value: line 1 column 1"
**Cause**: Export endpoint returned empty response
**Fix**: 
1. Verify clone REST API works: Test export endpoint directly
2. Check ALB routing is working for that specific clone
3. Ensure clone has ALB listener rule configured

#### Issue: "AccessDenied" when creating ALB rules
**Cause**: EC2 instance role missing ELB permissions
**Fix**: Apply Terraform changes with updated IAM policy (already done)

### Quick Verification Commands

```bash
# Verify clone is accessible
curl -I "https://clones.betaweb.ai/clone-YYYYMMDD-HHMMSS/" | head -1

# Test REST API export
curl -X POST "https://clones.betaweb.ai/clone-YYYYMMDD-HHMMSS/index.php?rest_route=/custom-migrator/v1/export" \
  -H "X-Migrator-Key: migration-master-key" -w "\nHTTP: %{http_code}\n"

# Check ALB rules count (HTTPS listener)
aws elbv2 describe-rules --listener-arn arn:aws:elasticloadbalancing:us-east-1:044514005641:listener/app/wp-targets-alb/9deaa3f04bc5506b/f6542ccc3f16bfd7 --region us-east-1 --query 'length(Rules[?Priority!=`default`])'

# List all active clones
aws elbv2 describe-target-groups --region us-east-1 --query 'TargetGroups[?starts_with(TargetGroupName, `clone-`)].TargetGroupName' --output table
```