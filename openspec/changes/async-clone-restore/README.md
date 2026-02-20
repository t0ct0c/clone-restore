# Async Clone/Restore System

**Status**: ✅ PRODUCTION READY  
**Last Updated**: February 2026  

---

## What This Does

Creates WordPress clones **asynchronously** - you request a clone, get an instant confirmation, and the system builds it in the background. No more waiting 2-3 minutes for the API to respond!

### Before vs After

```
BEFORE (Synchronous):
User clicks "Clone" → Wait 60-180 seconds → Get result ❌

AFTER (Asynchronous):
User clicks "Clone" → Instant "Job Started" → Clone builds in background ✅
```

---

## Simple Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐     ┌──────────────┐
│   User API  │ ──→ │  Redis Queue │ ──→ │   Workers   │ ──→ │  Kubernetes  │
│  Request    │     │  (Job Queue) │     │  (Dramatiq) │     │   Clones     │
└─────────────┘     └──────────────┘     └─────────────┘     └──────────────┘
       │                                                            │
       │  "Job ID: abc123"                                          │
       │  (instant!)                                                │
       │                                                            │
       └────────────────── Poll Status ◀────────────────────────────┘
                          "Clone ready!"
```

### What Each Part Does

| Component | What It Does | Why We Need It |
|-----------|--------------|----------------|
| **Redis Queue** | Holds clone jobs waiting to be processed | Like a restaurant order queue - first come, first served |
| **Dramatiq Workers** | Process clone jobs one by one | Kitchen staff cooking orders |
| **Kubernetes** | Creates actual WordPress clone pods | The plates being prepared |
| **KEDA** | Auto-scales workers based on queue size | Hires more staff when queue gets long |
| **Karpenter** | Auto-scales server nodes when needed | Builds more kitchen space when full |

---

## How It Works (Step by Step)

### 1. User Requests Clone

```bash
curl -X POST http://api.clones.betaweb.ai/api/v2/clone \
  -H "Content-Type: application/json" \
  -d '{"source_url": "https://mysite.com", "ttl_minutes": 30}'
```

**Response (instant, <100ms):**
```json
{
  "job_id": "job-abc123",
  "status": "pending",
  "status_url": "/api/v2/job-status/job-abc123"
}
```

### 2. System Processes Clone

```
Queue: [job-abc123, job-def456, ...]
         ↑
    Worker picks up job
         ↓
    1. Create database
    2. Create WordPress pod
    3. Activate plugin
    4. Create ingress
         ↓
    Clone ready!
```

### 3. User Checks Status

```bash
curl http://api.clones.betaweb.ai/api/v2/job-status/job-abc123
```

**Response:**
```json
{
  "job_id": "job-abc123",
  "status": "completed",
  "progress": 100,
  "result": {
    "clone_url": "https://job-abc123.clones.betaweb.ai",
    "username": "admin",
    "password": "..."
  }
}
```

---

## Key Features

### 🚀 Auto-Scaling Workers (KEDA)

```
Queue Depth → Worker Count
0-10 jobs   → 2 workers (minimum)
10-50 jobs  → 5 workers
50-100 jobs → 10 workers
100+ jobs   → 20 workers (maximum)
```

**Why**: Save money when idle, handle load when busy.

### 🛡️ Warm Standby Nodes (Karpenter Buffer Pool)

```
2 t2.small nodes always running
  ↓
Ready to accept clone pods instantly
  ↓
No waiting for servers to start
```

**Cost**: ~$24/month for 2 nodes  
**Benefit**: First 20 clones start instantly (0 seconds pending)

### ⏰ Auto-Cleanup (TTL)

```
Clone created → 30 minutes later → Auto-deleted
```

**Why**: Prevents orphaned clones from running forever and costing money.

### 🔌 Plugin Activation

```
Pod starts → WordPress ready → Activate custom-migrator plugin → Clone functional
```

**Why**: Clones need the migrator plugin to work properly.

---

## Production Fixes Applied

### Problem 1: Secret/DB Password Mismatch
**Issue**: Secret existed but database user was dropped → CrashLoopBackOff  
**Fix**: Code now checks if user exists and syncs password automatically

### Problem 2: Can't Execute Commands in Pods
**Issue**: RBAC missing `pods/exec` permission → Plugin activation failed  
**Fix**: Added `pods/exec` to service account role

### Problem 3: Karpenter Nodes Won't Join
**Issue**: Nodes created but couldn't authenticate to cluster  
**Fix**: Added Karpenter node role to aws-auth ConfigMap

---

## Current Setup

### Infrastructure

```
Namespace: wordpress-staging

Components:
├── wp-k8s-service (2 replicas)
│   ├── FastAPI (port 8000)
│   └── Dramatiq Worker (sidecar)
├── Redis (1 master)
├── Buffer Pool (2 t2.small nodes)
├── General Pool (auto-scale, up to 100 CPU)
└── TTL Cleaner (CronJob, every 5 minutes)
```

### Resource Limits

| Resource | Limit |
|----------|-------|
| Max CPU | 100 cores |
| Max Memory | 200 GiB |
| Max Pods | 150 |
| Max Workers | 20 |
| Clone TTL | 30 minutes |

---

## Monitoring

### Check Clone Status

```bash
# How many clones running?
kubectl get pods -n wordpress-staging -l app=wordpress-clone

# Check job queue depth
kubectl exec -n wordpress-staging redis-master-0 -- \
  redis-cli -a dramatiq-broker-password LLEN dramatiq

# View worker logs
kubectl logs -n wordpress-staging -l app=wp-k8s-service -c dramatiq-worker
```

### Check Infrastructure

```bash
# Buffer nodes
kubectl get nodes -l karpenter.sh/nodepool=buffer-pool

# Karpenter scaling
kubectl get nodeclaims

# KEDA scaling
kubectl get scaledobject -n wordpress-staging
```

---

## Files

```
openspec/changes/async-clone-restore/
├── README.md              # This file - simple overview
├── proposal.md            # Problem, solution, alternatives
├── design.md              # Technical architecture details
└── tasks.md               # Implementation checklist

kubernetes/
├── manifests/base/wp-k8s-service/
│   ├── deployment.yaml           # FastAPI + Dramatiq sidecar
│   ├── keda-scaledobject.yaml    # Auto-scaling config
│   ├── keda-trigger-auth.yaml    # Redis auth for KEDA
│   ├── keda-redis-secret.yaml    # Redis password secret
│   └── clone-ttl-cleaner-cronjob.yaml  # Auto-cleanup
├── manifests/base/namespaces/
│   └── staging-namespace-quota.yaml  # Resource limits
└── wp-k8s-service/app/
    ├── main.py              # FastAPI endpoints
    ├── tasks.py             # Dramatiq workers
    ├── job_store.py         # Database operations
    ├── k8s_provisioner.py   # Kubernetes operations
    ├── dramatiq_config.py   # Worker configuration
    └── dramatiq_otlp_middleware.py  # Tracing
```

---

## API Reference

### Create Clone

```bash
POST /api/v2/clone
Content-Type: application/json

{
  "source_url": "https://example.com",
  "source_username": "admin",
  "source_password": "secret",
  "customer_id": "my-clone-001",
  "ttl_minutes": 30
}
```

### Check Job Status

```bash
GET /api/v2/job-status/{job_id}

Response:
{
  "job_id": "...",
  "status": "pending|running|completed|failed",
  "progress": 0-100,
  "message": "Creating database...",
  "result": { ... }  # Only when completed
}
```

---

## Troubleshooting

### Clone Stuck in "Pending"

```bash
# Check if queue is backed up
kubectl exec -n wordpress-staging redis-master-0 -- \
  redis-cli -a dramatiq-broker-password LLEN dramatiq

# Check worker health
kubectl get pods -n wordpress-staging -l app=wp-k8s-service

# Check worker logs for errors
kubectl logs -n wordpress-staging -l app=wp-k8s-service -c dramatiq-worker
```

### Clone in CrashLoopBackOff

```bash
# Check pod logs
kubectl logs -n wordpress-staging <pod-name> -c wordpress

# Check if database user exists
kubectl exec -n wordpress-staging deployment/wp-k8s-service -c wp-k8s-service -- \
  python3 -c "import pymysql; c=pymysql.connect(...); print(c.query('SELECT 1'))"

# Delete and let worker recreate (fixes password mismatch)
kubectl delete deployment -n wordpress-staging <clone-name>
```

### Nodes Not Scaling

```bash
# Check Karpenter logs
kubectl logs -n karpenter -l app.kubernetes.io/name=karpenter

# Check NodeClaims
kubectl get nodeclaims

# Check if pods are pending
kubectl get pods -n wordpress-staging --field-selector=status.phase=Pending
```

---

## Cost

| Component | Monthly Cost |
|-----------|--------------|
| Buffer Nodes (2× t2.small spot) | ~$24 |
| General Pool (variable) | ~$50-100 |
| Redis | $0 (self-hosted) |
| **Total** | **~$74-124/month** |

---

## Success Metrics

| Metric | Before | After |
|--------|--------|-------|
| API Response Time | 60-180s | <100ms |
| Concurrent Clones | 1-2 | 50+ tested |
| Clone Success Rate | ~85% | >99% |
| Pending Time | N/A | 0s (buffer) / ~30s (scale) |

---

## Related Docs

- [Proposal](./proposal.md) - Why we built this
- [Design](./design.md) - Technical deep dive
- [Tasks](./tasks.md) - What was implemented
- [DRAMATIQ_SETUP.md](../../../kubernetes/wp-k8s-service/DRAMATIQ_SETUP.md) - Worker setup guide
