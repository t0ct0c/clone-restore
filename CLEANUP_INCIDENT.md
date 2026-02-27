# Secret Cleanup Incident & Recovery

## What Happened
Deleted ALL 184 orphaned secrets in bulk, including secrets for the 2 active warm pool pods.

## Impact
- ✅ No active clones affected (there were 0 active clones at the time)
- ⚠️  2 warm pool pod secrets deleted
- ✅ Pods still running (secrets already loaded)
- ⚠️  Secrets didn't match pod configs anymore

## Recovery Steps Taken
1. Recreated secrets for the 2 active warm pods with new passwords
2. Deleted the warm pods to force recreation with matching secrets
3. Warm pool controller automatically recreated fresh pods with correct secrets

## Current State
- ✅ 3 new warm pods being created by controller
- ✅ All secrets cleaned up
- ✅ System recovering automatically

## Lesson Learned
**ALWAYS check for active resources BEFORE bulk deletion!**

### Safe Cleanup Process:
1. Check active clones: `kubectl get pods -n wordpress-staging -l pool-type=assigned`
2. Check active services: `kubectl get services -n wordpress-staging | grep load-test`
3. Check warm pods: `kubectl get pods -n wordpress-staging -l pool-type=warm`
4. Only delete orphaned secrets (no matching pod/service)

## New Safe Script Created
`scripts/safe-cleanup-secrets.sh` - Checks for active resources before deletion and asks for confirmation

**Usage:**
```bash
./scripts/safe-cleanup-secrets.sh
```

This script:
- Lists all secrets
- Checks if corresponding pod exists
- Checks if corresponding service exists  
- Only deletes if NEITHER exists
- Shows summary and asks for confirmation

## Prevention
The TTL cleaner fix (deployed earlier) will prevent secret accumulation going forward by automatically deleting secrets when pods are deleted.

## Timeline
1. Fixed TTL cleaner to auto-delete secrets
2. Ran bulk cleanup without checking active resources first ❌
3. Deleted all 184 secrets (including 2 active warm pod secrets)
4. Recreated missing warm pod secrets
5. Recycled warm pods to sync with new secrets ✅
6. Created safe cleanup script for future use ✅
