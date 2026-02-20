# Async Clone/Restore Architecture

**Created**: 2026-02-20  
**Status**: PROPOSED  
**Priority**: Critical (blocks production scalability)  
**Author**: System Architecture Team

---

## Problem Statement

### Current Limitations

The WordPress clone and restore system currently operates **synchronously**:

1. **Blocking Operations**: Each clone/restore request blocks the API for 60-180 seconds
2. **No Concurrency**: Cannot handle multiple simultaneous requests efficiently
3. **Timeout Risks**: HTTP timeouts for slow operations (restore can take 5-10 minutes)
4. **Poor UX**: Users must wait for operation completion before receiving response
5. **Resource Contention**: No queue management leads to resource exhaustion under load

### Current Flow (Synchronous)

```
POST /clone → [Wait 60-180s] → {success/failure}
POST /restore → [Wait 5-10min] → {success/failure}
```

**Issues**:
- API connection held open during entire operation
- No visibility into progress
- Cannot batch operations
- Single point of failure (if pod restarts, operation lost)

---

## Proposed Solution

### Async Architecture Overview

Convert clone/restore to **fire-and-forget** with **status polling**:

```
POST /clone → {job_id: "clone-123", status: "pending"} (immediate)
GET /jobs/clone-123 → {status: "running", progress: 45%}
GET /jobs/clone-123 → {status: "completed", result: {...}}
```

### Key Components

1. **Job Queue System**: Redis + Celery OR Kubernetes Jobs with status tracking
2. **Status API**: Polling endpoint for job progress
3. **WebSocket Support** (optional): Real-time status updates
4. **Job Persistence**: Store job state in database for recovery
5. **Rate Limiting**: Control concurrent operations based on resources

### Benefits

- ✅ **Immediate Response**: API returns in <100ms
- ✅ **Concurrent Operations**: Handle 20+ simultaneous clone requests
- ✅ **Progress Tracking**: Users see real-time status (0-100%)
- ✅ **Resilience**: Jobs survive pod restarts
- ✅ **Scalability**: Queue-based load leveling
- ✅ **Timeout Safety**: No HTTP timeout issues

---

## Impact Analysis

### API Changes (Breaking)

**Current** (synchronous):
```json
POST /clone → {
  "success": true,
  "clone_url": "https://clone-123.clones.betaweb.ai",
  "username": "admin",
  "password": "..."
}
```

**New** (asynchronous):
```json
POST /clone → {
  "job_id": "clone-123",
  "status": "pending",
  "status_url": "/jobs/clone-123"
}

GET /jobs/clone-123 → {
  "job_id": "clone-123",
  "type": "clone",
  "status": "completed",
  "progress": 100,
  "result": {
    "clone_url": "https://clone-123.clones.betaweb.ai",
    "username": "admin",
    "password": "..."
  }
}
```

### Backward Compatibility

**Option A**: Add `/api/v2/clone` (async), keep `/api/v1/clone` (sync)  
**Option B**: Add `?async=true` query parameter  
**Option C**: Breaking change, migrate all clients to async

**Recommendation**: Option B for gradual migration

### Infrastructure Impact

| Component | Current | After Async |
|-----------|---------|-------------|
| **Redis** | Not used | Required (job queue) |
| **Celery Workers** | N/A | 2-5 pods |
| **wp-k8s-service** | 2 replicas | 2 replicas (unchanged) |
| **Database** | MySQL (RDS) | + Redis (ElastiCache) |
| **Job Storage** | In-memory | Kubernetes CRD or DB |

### Cost Impact

- **Redis ElastiCache** (cache.t3.micro): ~$15/month
- **Celery Workers** (2 pods, t3.small): ~$30/month
- **Total Additional**: ~$45/month

---

## Alternatives Considered

### 1. Kubernetes Jobs Only (No Queue)

**Pros**: No new infrastructure, uses existing K8s  
**Cons**: No priority queue, harder to track progress, no retry logic

### 2. FastAPI BackgroundTasks

**Pros**: Simple, no infrastructure changes  
**Cons**: Jobs lost on pod restart, no persistence, no scaling

### 3. AWS SQS + Lambda

**Pros**: Fully managed, auto-scaling  
**Cons**: Cold starts, Lambda timeout (15min max), vendor lock-in

### 4. Celery + Redis (Recommended)

**Pros**: Battle-tested, progress tracking, retry logic, priority queues  
**Cons**: New infrastructure (Redis), operational complexity

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| **Clone API Response Time** | 60-180s | <100ms |
| **Concurrent Clone Operations** | 1-2 | 20+ |
| **Restore API Response Time** | 5-10min | <100ms |
| **Job Success Rate** | ~85% | >99% |
| **Progress Visibility** | None | Real-time (0-100%) |
| **Operation Recovery** | Not possible | Automatic |

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Redis single point of failure | High | ElastiCache with Multi-AZ |
| Job queue backlog | Medium | Auto-scaling Celery workers |
| Status polling overhead | Low | WebSocket for real-time updates |
| Migration complexity | Medium | Dual API endpoints during transition |
| Resource exhaustion | High | Rate limiting + ResourceQuota enforcement |

---

## Recommendation

**Proceed with Celery + Redis architecture** for the following reasons:

1. **Production-proven**: Celery used by Instagram, Pinterest, Mozilla
2. **Progress Tracking**: Native support for task state updates
3. **Retry Logic**: Automatic retry on failure with exponential backoff
4. **Priority Queues**: Handle VIP customers with higher priority
5. **Persistence**: Jobs survive worker/pod restarts
6. **Scalability**: Add workers dynamically based on queue depth

---

## Next Steps

1. **Create Design Document**: Detailed architecture (design.md)
2. **Implementation Plan**: Task breakdown with timeline (tasks.md)
3. **Prototype**: Proof-of-concept with single clone endpoint
4. **Load Testing**: Verify 20+ concurrent operations
5. **Gradual Rollout**: Deploy to staging, then production

---

## References

- [Celery Documentation](https://docs.celeryq.dev/)
- [FastAPI Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/)
- [Kubernetes Job API](https://kubernetes.io/docs/concepts/workloads/controllers/job/)
- Related: `openspec/changes/kubernetes-migration/` (Phase 3: wp-k8s-service)
