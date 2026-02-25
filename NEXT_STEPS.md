# Next Steps - Resume Point for feat/kubernetes-restore

**Date**: 2026-02-25 22:45 UTC
**Branch**: feat/kubernetes-restore
**Deployed**: wp-k8s-service:use-working-image-20260225-223634

## What We Just Fixed (Complete)

### 1. TTL Cleaner Bug ✅
- **Problem**: Services, Ingresses, Secrets not being cleaned up when clones expired
- **Fix**: Added `ttl-expires-at` labels to all resources
- **Status**: FIXED and deployed
- **Evidence**: Cleaned up 17 services, 7 ingresses, 36 secrets

### 2. WordPress Image Bug ✅  
- **Problem**: Cold provision using wrong image (wordpress-target-sqlite:latest)
- **Fix**: Updated k8s_provisioner.py to use optimized-v14 (same as warm pool)
- **Status**: FIXED and deployed
- **Evidence**: Warm pool successfully uses optimized-v14, plugin installed & activated

## What to Do When You Return

### Step 1: Test Cold Provision (5 minutes)
```bash
# Create a test clone to verify cold provision works
curl -X POST https://clones.betaweb.ai/provision \
  -H "Content-Type: application/json" \
  -d '{"customer_id": "test-cold-'$(date +%s)'", "ttl_minutes": 30}'

# Wait for pod to be ready
kubectl wait --for=condition=ready pod -l clone-id=test-cold-* -n wordpress-staging --timeout=120s

# Test the custom-migrator REST API endpoint
curl -s http://test-cold-*.clones.betaweb.ai/wp-json/custom-migrator/v1/import

# Expected: Should NOT return 404 (plugin should be found)
```

### Step 2: Clean Up Test Clones (2 minutes)
```bash
# Delete all the test clones we created during debugging
kubectl delete deployment -n wordpress-staging absolute-final-1772029141
kubectl delete deployment -n wordpress-staging final-verify-1772029068
kubectl delete deployment -n wordpress-staging ultimate-test-1772028486
kubectl delete deployment -n wordpress-staging victory-test-1772028673
kubectl delete deployment -n wordpress-staging final-mysql-wait-1772028288
kubectl delete deployment -n wordpress-staging wpcli-test-1772028003

# Or use the cleanup script
python scripts/delete-clones.py
```

### Step 3: Continue Restore Implementation (Original Goal)
The async restore endpoint is already implemented but NOT tested:
- Endpoint: `POST /api/v2/restore`
- Test script: `scripts/restore-single.py`
- Documentation: `TEST_SCENARIO.md`

```bash
# Test the restore endpoint
python scripts/restore-single.py
```

## Important Reminders

### ❌ DON'T DO THESE
1. **Don't build new WordPress clone images** - optimized-v14 works perfectly
2. **Don't modify docker-entrypoint.sh** - it's working as-is in optimized-v14
3. **Don't add WP-CLI plugin activation code** - plugin already activated in image
4. **Don't assume something is broken** - check what's working first (warm pool)

### ✅ DO THESE
1. **Check warm pool first** when debugging - it's the working reference
2. **Use existing working images** instead of building new ones
3. **Test cold provision** after image changes
4. **Focus on restore implementation** - that's the actual goal

## Current Infrastructure State

**Working**:
- Warm pool: 2 pods using optimized-v14 ✅
- wp-k8s-service: deployed with correct image reference ✅
- TTL cleaner: fixed to clean all resources ✅

**To Verify**:
- Cold provision with optimized-v14 image
- Async restore endpoint functionality

## Files Modified This Session

1. `kubernetes/wp-k8s-service/app/k8s_provisioner.py`:
   - Line 47: Changed to optimized-v14
   - Line 197-198: Removed plugin activation call
   - Lines 855-881: Added TTL labels to Services
   - Lines 617-677: Added TTL labels to Ingresses
   - Lines 854-876: Added `_add_ttl_to_secret()` method

2. `kubernetes/wp-k8s-service/app/warm_pool_controller.py`:
   - Line 38: Already using optimized-v14 (no change needed)

3. `kubernetes/wp-k8s-service/app/ttl_cleaner.py`:
   - Lines 130-167: Enhanced to delete Service, Ingress, Secret

4. `kubernetes/manifests/base/wp-k8s-service/deployment.yaml`:
   - Updated to wp-k8s-service:use-working-image-20260225-223634

5. Created `scripts/cleanup-orphaned-resources.py`

## Commit History
```
13a153c - fix: use working optimized-v14 image for cold provision
95088b4 - Update warm_pool_controller to use WP-CLI WordPress image (REVERTED)
35d0bd3 - CRITICAL FIX: Activate custom-migrator plugin (NO LONGER NEEDED)
5cac52e - fix: update dramatiq-worker to new image and increase memory limits
3ca3639 - fix: add TTL labels to Services, Ingresses, and Secrets (KEEPER)
bd21674 - feat: add script to cleanup orphaned K8s resources (KEEPER)
```

Last 2 commits are the important ones. Middle commits were part of the circular troubleshooting.
