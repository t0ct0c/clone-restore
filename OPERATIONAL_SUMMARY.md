# Operational Summary - WordPress Clone System

**Last Updated**: February 27, 2026  
**Status**: ✅ Production Ready  
**Environment**: wordpress-staging namespace on AWS EKS

---

## System Overview

**Purpose**: Bulk WordPress clone system for demo/testing  
**Capacity**: 10 clones configured (scalable to 30+)  
**Architecture**: Warm pool + async job queue  
**Sources**: Dual-source (betaweb.ai + bonnel.ai)

---

## Current Configuration

### Warm Pool
- **Baseline**: 2-4 pods (low demand)
- **Burst**: Up to 20 pods (high demand)
- **Auto-scaling**: Based on Dramatiq queue depth
- **Image**: `wp-k8s-service:ttl-cleaner-fix-20260227-134158`

### Clone Settings
- **TTL**: 30 minutes
- **Auto-cleanup**: Every 5 minutes via CronJob
- **Sources**: Alternates 50/50 between betaweb.ai and bonnel.ai

### Infrastructure
- **VPC CNI**: Prefix delegation enabled
- **Pod Capacity**: 234 pods/node (xlarge+ instances)
- **Karpenter**: Constrained to xlarge or larger instances
- **Spot Instances**: Enabled for cost savings

---

## Key Files

### Scripts
- `scripts/bulk-create-clones.py` - Create 10 clones (dual-source)
- `scripts/cleanup-test-clones.sh` - Clean up test resources
- `scripts/safe-cleanup-secrets.sh` - Safe orphaned secret cleanup

### Code
- `kubernetes/wp-k8s-service/app/warm_pool_controller.py` - Warm pool logic
- `kubernetes/wp-k8s-service/app/ttl_cleaner.py` - TTL cleanup + secret deletion
- `kubernetes/wp-k8s-service/app/main.py` - API endpoints

### Deployment
- `kubernetes/manifests/base/wp-k8s-service/deployment.yaml` - Main deployment
- CronJob: `clone-ttl-cleaner` - Runs every 5 minutes

---

## Common Operations

### Run 10-Clone Test
```bash
cd /home/chaz/Desktop/clone-restore/scripts
python3 bulk-create-clones.py
```

**Output Files**:
- `bulk-clone-results-{timestamp}.json` - Full test results
- `bulk-clone-credentials-{timestamp}.json` - URLs and passwords

**Expected Time**: 2-3 minutes for 10 clones

### Clean Up Test Clones
```bash
# Clean up specific pattern
./scripts/cleanup-test-clones.sh load-test

# Clean up all test clones
./scripts/cleanup-test-clones.sh
```

**What It Deletes**:
- Services
- Ingresses
- Secrets
- Assigned pods

### Clean Up Orphaned Secrets
```bash
./scripts/safe-cleanup-secrets.sh
```

**Features**:
- Checks for active pods/services before deletion
- Shows summary
- Asks for confirmation

---

## Monitoring Commands

### Check Warm Pool
```bash
# Count warm pods
kubectl get pods -n wordpress-staging -l pool-type=warm --no-headers | wc -l

# Check warm pod status
kubectl get pods -n wordpress-staging -l pool-type=warm
```

### Check Active Clones
```bash
# Count active clones
kubectl get pods -n wordpress-staging -l pool-type=assigned --no-headers | wc -l

# List clone services
kubectl get services -n wordpress-staging | grep load-test
```

### Check Queue Depth
```bash
kubectl exec -n wordpress-staging redis-master-0 -- redis-cli -a $(kubectl get secret -n wordpress-staging redis -o jsonpath='{.data.redis-password}' | base64 -d) LLEN dramatiq:clone-queue
```

### Check Secrets
```bash
# Count orphaned secrets
kubectl get secrets -n wordpress-staging | grep -E "wordpress-warm-|load-test-" | wc -l

# List secrets
kubectl get secrets -n wordpress-staging | grep -E "wordpress-warm-|load-test-"
```

### Check TTL Cleaner
```bash
# View CronJob
kubectl get cronjob clone-ttl-cleaner -n wordpress-staging

# Check recent job
kubectl get jobs -n wordpress-staging | grep clone-ttl-cleaner | tail -1

# View logs
kubectl logs -n wordpress-staging job/$(kubectl get jobs -n wordpress-staging | grep clone-ttl-cleaner | tail -1 | awk '{print $1}')
```

---

## Troubleshooting

### Clones Not Starting
1. Check queue depth (should be > 0)
2. Check warm pool pods (should have ready pods)
3. Check wp-k8s-service logs: `kubectl logs -n wordpress-staging deployment/wp-k8s-service -c dramatiq-worker`

### Warm Pool Not Scaling
1. Verify queue detection: Check wp-k8s-service logs for "Queue depth:" messages
2. Check Redis connection: `kubectl exec -n wordpress-staging redis-master-0 -- redis-cli ping`
3. Restart controller: `kubectl rollout restart deployment/wp-k8s-service -n wordpress-staging`

### Secrets Accumulating
1. Check TTL cleaner CronJob is running
2. Check recent TTL cleaner logs for errors
3. Run safe cleanup script manually

### Script Stuck Polling
1. Verify API endpoint is responding: `curl -s https://clones.betaweb.ai/health`
2. Check wp-k8s-service is running: `kubectl get pods -n wordpress-staging -l app=wp-k8s-service`
3. Kill script and extract credentials manually (see DEMO_READY.md)

---

## Known Issues & Resolutions

### Issue: Warm Pool Shows More Than 20 Total Pods
**Status**: Not a bug - working as designed  
**Explanation**: `max_burst_pods=20` limits WARM pods only. Assigned pods (active clones) are separate. Total = warm + assigned can exceed 20.

### Issue: Clones Older Than 30 Minutes Still Running
**Status**: Check TTL timestamps  
**Resolution**: TTL cleaner runs every 5 minutes. Clones expire based on `ttl-expires-at` label timestamp, not pod age.

### Issue: Bulk Script Shows "N/A" for Passwords
**Status**: Fixed in latest version  
**Resolution**: Script now uses correct polling endpoint `/api/v2/job-status/{job_id}`

---

## Recent Changes

**2026-02-27**:
1. Fixed TTL cleaner to delete secrets when deleting pods
2. Fixed bulk script polling endpoint
3. Reduced test size to 10 clones for demo
4. Cleaned up 239 orphaned secrets
5. Created safe cleanup scripts

**Images Deployed**:
- wp-k8s-service: `ttl-cleaner-fix-20260227-134158`
- wp-k8s-service-clone: `final-fix-20260226-104040`

---

## Cost Estimate

**Staging Environment** (current): $140-170/month
- Spot instances with auto-scaling
- 2-4 baseline warm pods
- Bursts to 10-20 during testing

**Production** (estimated): $250-350/month
- Same configuration
- Higher utilization expected
- Still using Spot instances for cost savings

---

## Documentation

- **Full Issue History**: `SCALING_ISSUES_AND_FIXES.md`
- **Demo Guide**: `DEMO_READY.md`
- **Secret Cleanup**: `SECRET_CLEANUP_FIX.md`
- **Cleanup Incident**: `CLEANUP_INCIDENT.md`
- **Cost Analysis**: `costs/INFRASTRUCTURE_COSTS.md`
