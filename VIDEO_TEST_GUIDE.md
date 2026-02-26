# Video Test Guide - 50 Clone Load Test

## Overview
This guide helps you record a demonstration video showing the creation of 50 WordPress clones simultaneously, showcasing the EKS-based clone system performance.

## Prerequisites
- EKS cluster running: `wp-clone-restore` in us-east-1
- Namespace: `wordpress-staging`
- Warm pool: 2-3 pods ready
- kubectl configured with cluster access

## Relevant Scripts

### 1. Create 50 Clones
**Script:** `scripts/bulk-create-clones.py`

**What it does:**
- Creates 50 WordPress clones simultaneously
- Uses async v2 API (`POST /api/v2/clone`)
- Polls job status every 10 seconds
- Retrieves credentials from Kubernetes secrets
- Saves results to JSON files

**Configuration:**
- Source: `https://betaweb.ai`
- Clone count: 50 (configurable via `CLONE_COUNT`)
- TTL: 30 minutes (configurable via `TTL_MINUTES`)
- Poll interval: 10 seconds
- Clone IDs: `load-test-001` through `load-test-050`

**Usage:**
```bash
cd /home/chaz/Desktop/clone-restore
python3 scripts/bulk-create-clones.py
```

**Output files:**
- `bulk-clone-results-YYYYMMDD-HHMMSS.json` - Full test results
- `bulk-clone-credentials-YYYYMMDD-HHMMSS.json` - Clone credentials

**Expected timing:**
- Job submission: ~10-15 seconds (50 jobs at 0.2s interval)
- Clone completion: 60-120 seconds depending on warm pool availability
- Total test time: ~2-3 minutes

### 2. Cleanup After Testing
**Script:** `scripts/delete-clones.py`

**What it does:**
- Deletes clone pods, services, ingresses, and secrets
- Supports multiple deletion modes
- Captures credentials before deletion
- Parallel deletion (10 at a time)
- Cleans up JSON result files

**Usage options:**

```bash
# Delete clones from results file
python3 scripts/delete-clones.py bulk-clone-results-YYYYMMDD-HHMMSS.json

# Delete all test clones (load-test-*, bulk-test-*, test-*)
python3 scripts/delete-clones.py --all

# Delete clones matching pattern
python3 scripts/delete-clones.py --pattern "load-test"

# Kubernetes-only deletion (no API calls)
python3 scripts/delete-clones.py --k8s-only
```

**Expected timing:**
- Parallel deletion (10 workers): ~15-30 seconds for 50 clones

## Video Recording Steps

### Before Recording
1. Check warm pool status:
   ```bash
   kubectl get pods -n wordpress-staging -l pool-type=warm
   ```
   Expected: 2-3 pods at `2/2 Running`

2. Clear any existing test clones:
   ```bash
   python3 scripts/delete-clones.py --pattern "load-test"
   ```

### During Recording

**Phase 1: Introduction (30 seconds)**
- Show terminal/screen setup
- Explain what you're about to do (create 50 clones)
- Show warm pool status

**Phase 2: Start Clone Creation (5 seconds)**
```bash
python3 scripts/bulk-create-clones.py
```

**Phase 3: Job Submission (15 seconds)**
- Script submits all 50 jobs
- Show job IDs being created
- Show submission summary

**Phase 4: Progress Monitoring (2-3 minutes)**
- Script polls every 10 seconds
- Shows progress: pending → running → completed
- Displays completion messages as clones finish
- Shows final summary with timing

**Phase 5: Review Results (1 minute)**
- Show generated JSON files
- Display credentials file
- Show successful clone URLs
- Pick a few random clones to verify accessibility

**Phase 6: Verification (1 minute)**
```bash
# Check pods
kubectl get pods -n wordpress-staging -l app=wordpress-clone

# Check one clone URL
curl -I https://load-test-001.clones.betaweb.ai/
```

**Phase 7: Cleanup (30 seconds)**
```bash
python3 scripts/delete-clones.py --pattern "load-test"
```
- Show parallel deletion in action
- Show final cleanup summary

### After Recording
- Verify all resources deleted:
  ```bash
  kubectl get pods -n wordpress-staging -l app=wordpress-clone
  kubectl get ingress -n wordpress-staging | grep load-test
  ```

## Key Points to Highlight

### Performance Metrics
- **Warm pool advantage:** First 2-3 clones complete in ~60 seconds
- **Cold provision:** Additional clones in ~80-120 seconds
- **Parallel processing:** Redis queue + Dramatiq workers
- **Resource efficiency:** Local MySQL sidecars (no shared DB bottleneck)

### Architecture Features
- **Kubernetes-native:** All resources in EKS
- **Auto-scaling:** Warm pool automatically replenishes
- **TTL cleanup:** Clones auto-delete after 30 minutes
- **TLS termination:** Traefik load balancer with HTTPS
- **Health probes:** tcpSocket probes (not httpGet) for stability

### Common Issues (What NOT to Show)
- ❌ Don't show httpGet probes (causes CrashLoopBackOff)
- ❌ Don't remove HTTPS flag from entrypoint
- ❌ Don't show old API endpoints (`/job-status/` instead of `/jobs/`)

## Troubleshooting

### If warm pool is empty:
```bash
# Check warm pool controller logs
kubectl logs -n wordpress-staging -l app=wp-k8s-service -c dramatiq-worker --tail=50
```

### If clones fail to complete:
```bash
# Check specific pod
kubectl describe pod <pod-name> -n wordpress-staging

# Check pod logs
kubectl logs <pod-name> -n wordpress-staging -c wordpress
```

### If cleanup fails:
```bash
# Force delete specific resources
kubectl delete pod <pod-name> -n wordpress-staging --force --grace-period=0
kubectl delete ingress <clone-id> -n wordpress-staging
kubectl delete service <clone-id> -n wordpress-staging
kubectl delete secret <clone-id>-credentials -n wordpress-staging
```

## Expected Test Results

### Success Metrics
- ✅ 50/50 clones created successfully
- ✅ Success rate: 100%
- ✅ Average clone time: 70-90 seconds
- ✅ All clones accessible via HTTPS
- ✅ All clones have valid credentials
- ✅ wp-admin login works on sample clones

### Files Generated
- `bulk-clone-results-YYYYMMDD-HHMMSS.json` (~15-20 KB)
- `bulk-clone-credentials-YYYYMMDD-HHMMSS.json` (~8-10 KB)

### Kubernetes Resources Created (per clone)
- 1x Pod (2 containers: wordpress + mysql)
- 1x Service (ClusterIP)
- 1x Ingress (Traefik routing)
- 1x Secret (credentials)

**Total for 50 clones:** 200 Kubernetes resources

## Script Status

### ✅ Ready to Use
- `bulk-create-clones.py` - Updated to use `/api/v2/jobs/{job_id}`
- `delete-clones.py` - Fully functional for cleanup

### ⚠️ Not Needed for Video
- `clone-single.py` - Single clone creation (use for manual testing)
- `restore-single.py` - Restore testing (not part of this demo)
- `cleanup-orphaned-resources.py` - Manual K8s cleanup
- `cleanup-ecr-images.sh` - Docker image cleanup
- `manage-ecr-images.sh` - ECR management

## Quick Reference

### Pre-test checklist:
- [ ] Warm pool has 2-3 ready pods
- [ ] No existing load-test clones
- [ ] kubectl connected to cluster
- [ ] Terminal recording setup ready

### Post-test cleanup:
- [ ] Run delete script
- [ ] Verify no test clones remain
- [ ] Delete JSON result files
- [ ] Check warm pool replenished
