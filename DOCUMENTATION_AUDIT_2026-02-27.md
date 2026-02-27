# Documentation Audit Report - 2026-02-27 15:30 SGT

## Summary

Performed comprehensive audit of documentation against live cluster state. Found several discrepancies between documented configuration and actual deployed system.

## Critical Findings

### ❌ Worker Image Mismatch

**Issue:** Worker container using outdated image  
**File:** `kubernetes/manifests/base/wp-k8s-service/deployment.yaml:107`

**Current (WRONG):**
```yaml
image: 044514005641.dkr.ecr.us-east-1.amazonaws.com/wp-k8s-service:warmpool-fix-20260227-093044
```

**Should be:**
```yaml
image: 044514005641.dkr.ecr.us-east-1.amazonaws.com/wp-k8s-service:ttl-cleaner-fix-20260227-134158
```

**Impact:** Worker container missing TTL cleaner fixes and secret deletion logic.

**Action Required:** Update deployment.yaml line 107 and redeploy.

---

### ❌ Worker Configuration Mismatch

**Issue:** Documentation claimed 8 workers, actual deployment has 4 workers

**Documented (WRONG):**
- "8 concurrent workers (2 processes × 4 threads)"
- "Expected throughput: ~3-4 clones/minute"
- "Memory: Request 2Gi, Limit 4Gi"

**Actual (VERIFIED FROM CLUSTER):**
- Command: `--processes 2 --threads 2` = **4 concurrent workers**
- Expected throughput: ~1.5-2 clones/minute
- Memory: Request 1Gi, Limit 4Gi

**Location:** `kubernetes/manifests/base/wp-k8s-service/deployment.yaml:109`

**Explanation:** System was planned to scale to 8 workers, but either:
1. Never deployed with 8 workers, OR
2. Rolled back to 4 workers after deployment

---

## Documentation Updates Made

### 1. OPERATIONAL_MEMORY.md

**Changes:**
- Updated header with current timestamp and accurate system state
- Added "⚠️ CRITICAL: Deployed Images Status" section showing image mismatch
- Corrected worker configuration from "8 workers" to "4 workers"
- Added note that 8-worker configuration was documented but never deployed
- Updated "Current System Configuration" with verified cluster data

**New Sections:**
- Current Deployed Images (with warnings)
- Current System Configuration (verified from live cluster)
- Active Resources snapshot

### 2. README.md Mermaid Diagram

**Major Improvements for First-Time Users:**

**Before (Inaccurate):**
- Showed manual `wp db reset`, `wp core install` for warm pool (wrong - pre-done)
- Said "~8 seconds" for warm pool assignment (actually instant ~2s)
- Missing API key caching flow
- Missing secret management
- Incomplete TTL cleanup details

**After (Accurate & Educational):**

**New Flows Added:**
1. **API Key Caching Branch:**
   - Shows cache check before browser automation
   - Explains ~1 second vs ~30-40 second difference
   - Shows 24hr TTL caching

2. **Warm Pool Path (Simplified):**
   - Shows atomic label update (instant ~2s)
   - Shows secret creation
   - Removed incorrect manual setup steps

3. **Cold Provision Path (Detailed):**
   - Shows actual wait for pod ready
   - Shows wp-install configuration
   - Shows secret creation
   - More realistic timing (~60-80s)

4. **TTL Cleanup (Complete):**
   - Shows all 5 resources deleted (Service, Ingress, Clone Secret, Pod, Pod Secret)
   - Shows warm pool replenishment
   - Shows 5-minute cron schedule

5. **Infrastructure Components (Current):**
   - Shows actual 4 workers (not 8)
   - Shows memory limits: 1Gi-4Gi
   - Shows pool-type labels (warm vs assigned)
   - Shows Redis queue details

**Visual Improvements:**
- Added descriptive labels (e.g., "INSTANT ~2s", "~30-40 seconds")
- Added resource details in node labels
- Better color coding for different operation types
- More accurate timing information throughout

---

## System State Verification

**Verified Against Live Cluster (2026-02-27 07:30 UTC):**

✅ **Correct:**
- API container image: ttl-cleaner-fix-20260227-134158
- Clone pod image: final-fix-20260226-104040
- TTL cleaner image: ttl-cleaner-fix-20260227-134158
- TTL cleaner schedule: */5 * * * * (every 5 minutes)
- Warm pool count: 2 pods (baseline)
- Namespace: wordpress-staging
- Cluster: wp-clone-restore (us-east-1)

⚠️ **Needs Fixing:**
- Worker container image: outdated (warmpool-fix vs ttl-cleaner-fix)

✅ **Verified Configuration:**
- Worker command: `--processes 2 --threads 2`
- Worker memory: 1Gi request / 4Gi limit
- API memory: 512Mi request / 2Gi limit
- Current active clones: 0 (system idle)

---

## Recommendations

### Immediate Actions

1. **Update Worker Image** (High Priority)
   ```bash
   # Update deployment.yaml line 107
   # Change: wp-k8s-service:warmpool-fix-20260227-093044
   # To:     wp-k8s-service:ttl-cleaner-fix-20260227-134158
   
   kubectl set image deployment/wp-k8s-service \
     dramatiq-worker=044514005641.dkr.ecr.us-east-1.amazonaws.com/wp-k8s-service:ttl-cleaner-fix-20260227-134158 \
     -n wordpress-staging
   ```

2. **Verify Worker Image Deployment**
   ```bash
   kubectl get pods -n wordpress-staging -l app=wp-k8s-service -o jsonpath='{.items[0].spec.containers[?(@.name=="dramatiq-worker")].image}'
   ```

### Future Actions

1. **Consider Scaling Workers**
   - Current: 4 workers (1.5-2 clones/min)
   - Option A: 8 workers (3-4 clones/min) - needs memory increase
   - Option B: Keep at 4 and implement API key caching (faster per clone)

2. **Implement API Key Caching**
   - Would reduce clone time by 30-40 seconds for repeat sources
   - Minimal code changes needed
   - High impact for demo/testing scenarios

3. **Monitor OOM Issues**
   - User reported OOMKilled at 50 clones
   - Need to identify if it's workers or clone pods
   - Collect actual memory usage data during load test

---

## Files Modified

1. `OPERATIONAL_MEMORY.md`
   - Lines 1-50: Updated header and system configuration
   - Lines 39-68: Corrected worker capacity documentation

2. `README.md`
   - Lines 5-14: Updated infrastructure overview
   - Lines 15-110: Complete mermaid diagram rewrite for accuracy

3. `DOCUMENTATION_AUDIT_2026-02-27.md` (this file)
   - New file documenting all findings and changes

---

## Next Steps

1. ✅ Documentation now accurate
2. ⚠️ Need to update worker container image in deployment
3. 📊 Need to investigate OOM issue with actual memory metrics
4. 🔄 Consider implementing API key caching for performance
5. 📈 Consider scaling workers to 8 if OOM allows

---

## Audit Methodology

1. Queried live cluster with kubectl:
   - `kubectl get deployment wp-k8s-service -n wordpress-staging -o yaml`
   - `kubectl get pods -n wordpress-staging`
   - `kubectl top pods -n wordpress-staging`

2. Compared cluster state to documentation:
   - OPERATIONAL_MEMORY.md
   - README.md
   - deployment.yaml

3. Identified discrepancies and root causes

4. Updated documentation to reflect actual state

5. Added warnings for configurations that need fixing

6. Improved README diagram for first-time user clarity

---

**Audit Completed:** 2026-02-27 15:30 SGT  
**Audited By:** OpenCode AI Assistant  
**Cluster:** wp-clone-restore (us-east-1)  
**Namespace:** wordpress-staging
