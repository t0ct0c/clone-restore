# Clone Optimization - Phase 1: Local DB + Warm Pod Pool

**Status**: PLANNING  
**Created**: 2026-02-21  
**Target**: Reduce clone time from 180s to 60s  

---

## Problem

Current clone flow takes 180-240 seconds:
- Shared RDS user creation: 5-10s
- Pod startup: 30-60s  
- WordPress initialization: 30-60s
- Plugin activation: 10-20s
- Clone import: 30-120s

Shared RDS also creates bottlenecks:
- Connection limits (max 100-200 concurrent)
- Single point of failure
- Cost: $50-100/month

---

## Solution

### 1. Local MySQL per Pod (Sidecar)

Replace shared RDS with MySQL sidecar container in each WordPress pod:

```
WordPress Pod
├── WordPress Container (port 80)
└── MySQL Container (port 3306, localhost only)
```

**Benefits**:
- No RDS cost ($0/month)
- No connection limits
- No network latency (localhost)
- Isolated failures

### 2. Warm Pod Pool (2 pods always ready)

Maintain 2 pre-initialized WordPress pods with empty databases:

```
Warm Pool Controller
├── Monitors pool size (target: 2 pods)
├── Creates new warm pods when count drops
└── Returns pods to pool after TTL reset
```

**Pod Lifecycle**:
```
WARM (empty, ready) → ASSIGNED (importing) → READY (serving) → RESETTING → WARM
```

**Benefits**:
- Skip pod startup (30-60s saved)
- Skip WordPress initialization (30-60s saved)
- Clone time: 35-65s (vs 180-240s)

### 3. Pod Reuse After TTL

Instead of deleting pods after 30min TTL:
1. Reset database (DROP + CREATE)
2. Clean filesystem (uploads, plugins)
3. Return to warm pool

**Benefits**:
- No pod creation overhead for next clone
- Consistent 60s clone times
- Lower K8s API load

---

## Expected Results

| Metric | Current | Target | Improvement |
|--------|---------|--------|-------------|
| Clone time | 180-240s | 35-65s | 65-75% faster |
| RDS cost | $50-100/month | $0 | 100% savings |
| Warm pod cost | $0 | $21/month | -$21/month |
| **Total cost** | **$124-224/month** | **$95-166/month** | **$29-58/month savings** |
| Concurrent capacity | 100 (RDS limit) | Unlimited | No bottlenecks |

---

## Implementation Phases

### Phase 1: Local DB + Warm Pool (3-4 days)
- WordPress + MySQL sidecar deployment
- Warm pool controller
- Pod reset logic
- Integration with clone flow

### Phase 2: Parallel Execution (1 day)
- Run browser automation + pod assignment simultaneously
- Plugin status cache (Redis)

### Phase 3: Go K8s Sidecar (1 week)
- Go service for K8s operations
- Event-based pod watching (vs polling)

---

## Files to Create/Modify

**New Files**:
- `kubernetes/wp-k8s-service/wordpress-clone/Dockerfile` (WordPress + MySQL)
- `kubernetes/wp-k8s-service/wordpress-clone/docker-entrypoint.sh`
- `kubernetes/wp-k8s-service/app/warm_pool_controller.py`
- `kubernetes/manifests/base/wp-k8s-service/warm-pool-deployment.yaml`

**Modified Files**:
- `kubernetes/wp-k8s-service/app/k8s_provisioner.py` (remove RDS, use localhost)
- `kubernetes/wp-k8s-service/app/main.py` (parallel execution)
- `kubernetes/wp-k8s-service/requirements.txt` (if needed)

---

## Testing Plan

1. **Unit Tests**
   - Warm pool controller (maintain pool size)
   - Pod reset logic (clean state)
   - MySQL sidecar connectivity

2. **Integration Tests**
   - Clone with warm pod assignment
   - Clone with cold provision (overflow)
   - Pod return to pool after TTL

3. **Load Tests**
   - 10 concurrent clones
   - 50 clones/hour sustained
   - Warm pool scaling

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| MySQL sidecar crashes | Pod unusable | Liveness probe, auto-restart |
| Warm pool empty | Cold provision fallback | Karpenter auto-scale |
| Pod reset incomplete | Dirty state for next clone | Thorough cleanup, validation |
| Resource contention | Slower clones | Resource limits per container |

---

## Success Criteria

- Clone time: < 65s (p95)
- Warm pool: Always 1-2 pods ready
- Cost: < $166/month (23%+ savings vs current)
- Success rate: > 99% (same as current)
