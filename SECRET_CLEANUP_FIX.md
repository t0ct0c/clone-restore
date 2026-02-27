# Secret Cleanup Fix - Automatic Resource Deletion

## Problem
When warm pods were deleted, their secrets (`wordpress-warm-XXXXX-credentials`) were left behind as orphans. Over time, this accumulated to **239 orphaned secrets**!

## Root Cause
The TTL cleaner (`ttl_cleaner.py`) was deleting pods directly in error cases without also deleting their associated secrets:
- Line 165: Delete orphaned pod → secret left behind
- Line 177: Delete regular clone pod → secret left behind

## Solution Applied

### 1. Fixed TTL Cleaner ✅
Updated `/kubernetes/wp-k8s-service/app/ttl_cleaner.py` to delete pod secrets when deleting pods:

```python
# Before (line 165):
core_api.delete_namespaced_pod(name, namespace)

# After:
core_api.delete_namespaced_pod(name, namespace)
# Delete pod's secret
try:
    core_api.delete_namespaced_secret(f"{name}-credentials", namespace)
except:
    pass
```

Applied to BOTH deletion locations (lines 165 and 177).

### 2. Rebuilt and Deployed ✅
```bash
# New image
044514005641.dkr.ecr.us-east-1.amazonaws.com/wp-k8s-service:ttl-cleaner-fix-20260227-134158

# Updated:
- wp-k8s-service deployment
- clone-ttl-cleaner CronJob
- deployment.yaml manifest
```

### 3. Cleaned Up Existing Orphans ✅
Created script: `scripts/cleanup-orphaned-secrets.sh`

Deletes secrets where:
- No corresponding pod exists
- No corresponding service exists (for clone secrets)

**Usage:**
```bash
./scripts/cleanup-orphaned-secrets.sh
```

## How It Works Now

### When Pods Are Deleted:

**Warm Pool Controller** (`_delete_pod` function):
1. Delete pod
2. Delete pod's secret (`{pod_name}-credentials`) ✅

**TTL Cleaner** (error handling):
1. Delete pod
2. Delete pod's secret (`{pod_name}-credentials`) ✅ **[NEWLY FIXED]**

**TTL Cleaner** (clone cleanup):
1. Delete clone service
2. Delete clone ingress
3. Delete clone secret (`{clone_id}-credentials`)
4. Delete pod
5. Delete pod's secret (`{pod_name}-credentials`) ✅ **[NEWLY FIXED]**

### Resource Cleanup Flow

```
Clone Created:
  ├─ Warm pod assigned (pool-type=assigned)
  ├─ Service created (load-test-XXX)
  ├─ Ingress created (load-test-XXX)
  └─ Clone secret created (load-test-XXX-credentials)
  
After 30 min TTL:
  ├─ TTL Cleaner deletes:
  │   ├─ Service ✓
  │   ├─ Ingress ✓
  │   ├─ Clone secret ✓
  │   ├─ Pod ✓
  │   └─ Pod secret ✓ [FIXED]
  └─ Pod returned to warm pool (or deleted if reset fails)
```

## Verification

**Check for orphaned secrets:**
```bash
kubectl get secrets -n wordpress-staging | grep -E "wordpress-warm-|load-test-" | wc -l
```

**View TTL cleaner logs:**
```bash
kubectl logs -n wordpress-staging job/$(kubectl get jobs -n wordpress-staging | grep clone-ttl-cleaner | tail -1 | awk '{print $1}')
```

**Force secret cleanup:**
```bash
./scripts/cleanup-orphaned-secrets.sh
```

## Files Changed
- `kubernetes/wp-k8s-service/app/ttl_cleaner.py` (lines 165-176, 177-189)
- `kubernetes/manifests/base/wp-k8s-service/deployment.yaml` (line 23)
- `scripts/cleanup-orphaned-secrets.sh` (NEW)

## Result
- ✅ No more orphaned secrets accumulating
- ✅ Automatic cleanup on every pod deletion
- ✅ 239 existing orphaned secrets cleaned up
- ✅ Deployed to production (wordpress-staging)
