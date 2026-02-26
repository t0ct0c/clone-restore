# Start Here Tomorrow - WordPress Clone System

**Date**: 2026-02-27
**Status**: ✅ System optimized and ready for testing
**Last Session**: Queue reliability investigation and performance tuning

---

## Quick Summary - What We Achieved Today

### 🎯 Main Goal
Fix the "lost messages" issue for 50-clone bulk test

### ✅ What We Found
**Messages were NEVER lost!** They were sitting in Redis queue, just processing slowly.

### 🔧 Fixes Applied

1. **Scaled Workers: 4 → 8 concurrent**
   - Before: ~1.3-2 clones/minute
   - Now: ~3-4 clones/minute (2x faster)
   - Configuration: 2 processes × 4 threads

2. **Fixed Memory Issues**
   - Problem: 16 workers used 2.5GB but only requested 1Gi → pod evictions
   - Solution: 8 workers + 2Gi memory request = stable (no evictions)

3. **Implemented TTL Extension**
   - Jobs now get +60 minutes when processing starts
   - Prevents expiration while waiting in queue

4. **Discovered Karpenter Limit**
   - Cluster maxes out at 30 nodes
   - 30 clones simultaneously = cluster saturation
   - **Recommendation**: Test with 10 clones tomorrow

---

## Current System State

### Deployed Images
- **wp-k8s-service**: `ttl-fix-20260226-230812`
- **Clone image**: `final-fix-20260226-104040` (unchanged)

### Worker Configuration
```yaml
Workers: 8 concurrent (2 processes × 4 threads)
Memory: Request 2Gi, Limit 4Gi
CPU: Request 500m, Limit 2
```

### Redis Queue
- ✅ Empty (0 messages)
- ✅ Persistence enabled (AOF)
- ✅ Eviction policy: noeviction

### Cleanup Status
- ✅ All test clones deleted
- ✅ Redis queue cleared
- ✅ wp-k8s-service healthy (2/2 Running, 0 restarts)

---

## Tomorrow's Testing Plan

### Recommended Approach
1. **Start small**: Test with 10 clones first
2. **Monitor**: Watch worker memory usage and queue depth
3. **Verify**: All 10 clones complete successfully
4. **Scale up**: If stable, try 20 clones
5. **Document**: Record performance metrics

### Test Script
```bash
# Update script for 10 clones
cd /home/chaz/Desktop/clone-restore/scripts
# Edit bulk-create-clones.py: CLONE_COUNT = 10

# Run test
python3 bulk-create-clones.py

# Monitor in separate terminal
watch -n 5 'kubectl get pods -n wordpress-staging | grep load-test'
```

### What to Watch For
- ✅ **Good**: All clones reach 2/2 Running
- ✅ **Good**: Worker memory stays under 2Gi
- ✅ **Good**: Queue drains quickly (check with: `kubectl exec -n wordpress-staging redis-master-0 -- redis-cli -a $(kubectl get secret -n wordpress-staging redis -o jsonpath='{.data.redis-password}' | base64 -d) LLEN dramatiq:clone-queue`)
- ❌ **Bad**: Pod evictions (memory exceeded)
- ❌ **Bad**: Karpenter hitting node limit
- ❌ **Bad**: Clones stuck in pending state

---

## Key Files to Reference

- **OPERATIONAL_MEMORY.md**: Full investigation details and configuration
- **DEPLOYMENT_CHECKLIST.md**: Step-by-step deployment guide
- **VIDEO_TEST_GUIDE.md**: Instructions for demo video (50 clones)

---

## Important Reminders

1. **DON'T scale workers beyond 8 without increasing memory request**
   - 8 workers = ~1.2GB (safe)
   - 16 workers = ~2.5GB (causes evictions with 2Gi)

2. **DON'T submit 30+ clones simultaneously**
   - Karpenter has 30-node limit
   - Batch in groups of 10 instead

3. **DON'T rebuild clone image** (final-fix-20260226-104040)
   - It's correct as-is
   - Has HTTPS flag in entrypoint

---

## Quick Commands

```bash
# Check worker status
kubectl get pods -n wordpress-staging -l app=wp-k8s-service

# Check worker memory
kubectl top pod -n wordpress-staging wp-k8s-service-*

# Check queue depth
kubectl exec -n wordpress-staging redis-master-0 -- redis-cli -a $(kubectl get secret -n wordpress-staging redis -o jsonpath='{.data.redis-password}' | base64 -d) LLEN dramatiq:clone-queue

# Check clone pods
kubectl get pods -n wordpress-staging | grep load-test

# Check cluster nodes
kubectl get nodes

# Clean up all test clones
kubectl delete deployments,services,ingresses,secrets -n wordpress-staging -l 'clone-id'
```

---

## Next Steps (Priority Order)

1. ✅ **DONE**: Optimize worker performance
2. ✅ **DONE**: Fix queue reliability
3. ✅ **DONE**: Fix TTL expiration
4. 🎯 **NEXT**: Test with 10 clones (verify stability)
5. ⏭️  **THEN**: Test with 20 clones
6. ⏭️  **THEN**: Test with 30 clones (if cluster can handle it)
7. ⏭️  **FUTURE**: Implement HA (replicas: 2 + PDB)

---

Good luck tomorrow! The system is in great shape and ready for testing. 🚀
