# Async Clone/Restore - Quick Reference

**Status**: PLANNING  
**Timeline**: 4 weeks  
**Priority**: Critical

---

## Overview

Convert WordPress clone/restore from synchronous (blocking) to asynchronous (non-blocking) architecture to handle 20+ concurrent operations.

---

## Problem

**Current**: 
- Clone takes 60-180s, API blocks entire time
- Cannot handle concurrent requests
- HTTP timeouts for slow operations

**After**:
- API responds in <100ms with job_id
- Poll `/api/v2/jobs/{job_id}` for status
- Support 20+ concurrent clones

---

## Architecture

```
Client → FastAPI → Redis Queue → Celery Workers → Kubernetes
  │                                              │
  └────────── Poll Status ◀──────────────────────┘
```

**Components**:
- **Redis**: Job queue (Bitnami Helm chart)
- **Celery**: Task queue workers (3 replicas, auto-scale to 10)
- **FastAPI**: Async endpoints (`/api/v2/clone`, `/api/v2/jobs/{id}`)
- **MySQL**: Job status persistence (shared RDS)

---

## API Changes

### Before (Synchronous)

```bash
POST /api/v1/clone
# Wait 60-180s...
→ { "clone_url": "...", "username": "...", "password": "..." }
```

### After (Asynchronous)

```bash
# Create clone (immediate)
POST /api/v2/clone
→ { "job_id": "clone-abc123", "status": "pending", "status_url": "/api/v2/jobs/clone-abc123" }

# Poll status
GET /api/v2/jobs/clone-abc123
→ { "status": "running", "progress": 45, "status_message": "Creating database..." }

# Final result
GET /api/v2/jobs/clone-abc123
→ { "status": "completed", "progress": 100, "result": { "clone_url": "...", ... } }
```

---

## Files Created

```
openspec/changes/async-clone-restore/
├── README.md              # This file
├── proposal.md            # Problem, solution, impact analysis
├── design.md              # Technical architecture, schemas, code examples
└── tasks.md               # 14 implementation tasks with acceptance criteria
```

---

## Implementation Plan

### Week 1: Infrastructure
- [ ] 1.1 Deploy Redis (Helm)
- [ ] 1.2 Create jobs table (MySQL)
- [ ] 1.3 Update requirements.txt
- [ ] 1.4 Deploy Celery workers (K8s)

### Week 2: Code
- [ ] 2.1 Implement `job_store.py` (SQLAlchemy)
- [ ] 2.2 Implement `celery_tasks.py` (progress tracking)
- [ ] 2.3 Update `main.py` (async endpoints)
- [ ] 2.4 Create `schemas.py` (Pydantic)

### Week 3: Testing
- [ ] 3.1 Unit tests (job_store)
- [ ] 3.2 Integration tests (Celery tasks)
- [ ] 3.3 Load test (20 concurrent clones)
- [ ] 3.4 Chaos test (kill worker mid-operation)

### Week 4: Rollout
- [ ] 4.1 Deploy to staging
- [ ] 4.2 Bulk clone test
- [ ] 4.3 Monitor 1 week
- [ ] 4.4 Production rollout (10% → 50% → 100%)

---

## Cost Impact

| Component | Current | After | Delta |
|-----------|---------|-------|-------|
| **Redis ElastiCache** | $0 | $15/mo | +$15 |
| **Celery Workers** | $0 | $30/mo | +$30 |
| **Total** | $0 | $45/mo | **+$45/mo** |

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Clone API Response | 60-180s | <100ms |
| Concurrent Clones | 1-2 | 20+ |
| Job Success Rate | ~85% | >99% |
| Progress Visibility | None | Real-time |

---

## Quick Start (Once Implemented)

```bash
# Create clone
curl -X POST http://localhost:8000/api/v2/clone \
  -H "Content-Type: application/json" \
  -d '{"source_url": "https://betaweb.ai", "ttl_minutes": 60}'

# Response: {"job_id": "clone-abc123", "status": "pending"}

# Poll status
curl http://localhost:8000/api/v2/jobs/clone-abc123

# Response: {"status": "completed", "result": {...}}
```

---

## Monitoring

**Grafana Dashboards**:
1. Async Jobs Overview (created/completed/failed)
2. Celery Workers (queue depth, task duration)
3. Redis (memory, connections)

**Alerts**:
- `celery_queue_depth > 50` for 5min → Scale workers
- `celery_task_failure_rate > 5%` for 10min → Page on-call

---

## Rollback

```bash
# Revert to synchronous version
kubectl rollout undo deployment/wp-k8s-service -n wordpress-staging
kubectl rollout undo deployment/celery-workers -n wordpress-staging
```

---

## Related Documentation

- [Proposal](./proposal.md) - Problem statement, alternatives, recommendations
- [Design](./design.md) - Technical architecture, code examples, schemas
- [Tasks](./tasks.md) - Detailed implementation plan with acceptance criteria
- [Traefik Migration](../kubernetes-migration/tasks.md) - Phase 4.5 (completed)

---

## Contact

For questions about this change, refer to:
- OpenSpec location: `openspec/changes/async-clone-restore/`
- Code location: `kubernetes/wp-k8s-service/app/`
- MCP servers: Traefik MCP, code-index MCP (configured in `opencode.jsonc`)
