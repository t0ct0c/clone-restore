# WordPress Clone & Restore System

## Overview

This system creates **temporary WordPress clones** for safe testing, then **restores changes back to production**. All managed through a simple REST API.

### Quick Flow

```mermaid
flowchart LR
    User["User / API"] -->|POST /api/v2/clone| API["FastAPI Service"]
    API -->|Job queued| Redis["Redis Queue"]
    Redis -->|Process job| Worker["Dramatiq Worker"]
    Worker -->|Create clone| K8s["Kubernetes"]
    K8s -->|Clone ready| User
    User -->|POST /api/v2/restore| API
    API -->|Restore to prod| Target["Production WordPress"]
```

---

## Architecture (Current - Kubernetes)

```mermaid
flowchart TB
    subgraph "User Layer"
        User["User / API Client"]
    end
    
    subgraph "API Layer"
        ALB["AWS ALB<br/>api.clones.betaweb.ai"]
        Traefik["Traefik Ingress"]
        FastAPI["FastAPI Service<br/>wp-k8s-service"]
    end
    
    subgraph "Async Processing"
        Redis["Redis Broker<br/>Job Queue"]
        Dramatiq["Dramatiq Workers<br/>Auto-scaled by KEDA"]
    end
    
    subgraph "Clone Infrastructure"
        Karpenter["Karpenter<br/>Node Auto-Scaling"]
        BufferPool["Buffer Pool<br/>2 warm nodes"]
        Clones["WordPress Clones<br/>Pods with SQLite"]
    end
    
    subgraph "Cleanup"
        TTL["TTL Cleaner<br/>CronJob every 5min"]
    end
    
    User -->|1. POST /api/v2/clone| ALB
    ALB --> Traefik
    Traefik --> FastAPI
    FastAPI -->|2. Queue job| Redis
    Redis -->|3. Process| Dramatiq
    Dramatiq -->|4. Create clone| K8s
    K8s --> Karpenter
    Karpenter --> BufferPool
    Karpenter --> Clones
    Clones -->|5. Auto-delete after 30min| TTL
    
    style User fill:#e1f5ff
    style FastAPI fill:#fff4e1
    style Redis fill:#ffe1f5
    style Dramatiq fill:#ffe1f5
    style Clones fill:#e1ffe1
    style TTL fill:#ffe4e1
```

### What Each Component Does

| Component | Purpose |
|-----------|---------|
| **FastAPI** | REST API endpoints (`/api/v2/clone`, `/api/v2/restore`, `/api/v2/job-status`) |
| **Redis** | Job queue - holds clone requests waiting to be processed |
| **Dramatiq Workers** | Process clone jobs (create DB, deploy pod, activate plugin) |
| **KEDA** | Auto-scales workers based on queue depth (2-20 workers) |
| **Karpenter** | Auto-scales EC2 nodes when pods need capacity |
| **Buffer Pool** | 2 warm standby nodes for instant clone scheduling |
| **WordPress Clones** | Individual pods with SQLite (no MySQL container needed) |
| **TTL Cleaner** | Deletes clones after 30 minutes to save costs |

---

## API Endpoints

### v2 (Async - Current)

| Endpoint | Method | Description | Response Time |
|----------|--------|-------------|---------------|
| `/api/v2/clone` | POST | Create clone (returns job_id) | <100ms |
| `/api/v2/job-status/{job_id}` | GET | Check clone status | <50ms |
| `/api/v2/restore` | POST | Restore clone to production | <100ms |
| `/api/v2/delete/{clone_id}` | DELETE | Delete clone early | <50ms |

### v1 (Legacy - Deprecated)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/clone` | POST | Old sync clone (blocking) |
| `/restore` | POST | Restore to production |

---

## Usage Examples

### Create Clone (Async)

```bash
# 1. Request clone (instant response)
curl -X POST http://api.clones.betaweb.ai/api/v2/clone \
  -H "Content-Type: application/json" \
  -d '{
    "source_url": "https://mysite.com",
    "source_username": "admin",
    "source_password": "secret",
    "customer_id": "test-clone-001",
    "ttl_minutes": 30
  }'

# Response (instant):
{
  "job_id": "job-abc123",
  "status": "pending",
  "status_url": "/api/v2/job-status/job-abc123"
}

# 2. Poll for status
curl http://api.clones.betaweb.ai/api/v2/job-status/job-abc123

# Response (when ready):
{
  "status": "completed",
  "clone_url": "https://test-clone-001.clones.betaweb.ai",
  "username": "admin",
  "password": "..."
}
```

### Restore Clone

```bash
curl -X POST http://api.clones.betaweb.ai/api/v2/restore \
  -H "Content-Type: application/json" \
  -d '{
    "source": {
      "url": "https://test-clone-001.clones.betaweb.ai",
      "username": "admin",
      "password": "..."
    },
    "target": {
      "url": "https://production.com",
      "username": "admin",
      "password": "..."
    }
  }'
```

---

## Infrastructure

### Kubernetes Resources

```yaml
Namespace: wordpress-staging

Components:
├── wp-k8s-service (Deployment, 2 replicas)
│   ├── FastAPI container (port 8000)
│   └── Dramatiq worker sidecar
├── Redis (StatefulSet, 1 replica)
├── Traefik (Ingress Controller)
├── KEDA (ScaledObject for auto-scaling)
└── TTL Cleaner (CronJob, every 5min)

Node Pools:
├── Buffer Pool (2× t2.small spot, always warm)
└── General Pool (auto-scale, up to 100 CPU)
```

### Resource Limits

| Resource | Limit |
|----------|-------|
| Max CPU | 100 cores |
| Max Memory | 200 GiB |
| Max Pods | 150 |
| Max Workers | 20 |
| Clone TTL | 30 minutes (auto-delete) |

---

## How Cloning Works

```mermaid
sequenceDiagram
    participant User
    participant API as FastAPI
    participant Queue as Redis
    participant Worker as Dramatiq
    participant K8s as Kubernetes
    participant RDS as Shared MySQL

    User->>API: POST /api/v2/clone
    API->>Queue: Push job
    API-->>User: job_id (instant)
    
    loop Worker processes job
        Worker->>Queue: Pop job
        Worker->>RDS: Create database
        Worker->>K8s: Create Secret
        Worker->>K8s: Create Deployment
        K8s-->>Worker: Pod running
        Worker->>K8s: Exec (activate plugin)
        Worker->>K8s: Create Service
        Worker->>K8s: Create Ingress
        Worker->>Queue: Job complete
    end
    
    User->>API: GET /api/v2/job-status/{job_id}
    API-->>User: status: completed
```

### Step by Step

1. **User requests clone** → API responds instantly with `job_id`
2. **Job queued in Redis** → First-in, first-out processing
3. **Worker picks up job** → Creates database on shared RDS
4. **Kubernetes creates pod** → WordPress + SQLite container
5. **Plugin activated** → custom-migrator plugin enabled via `kubectl exec`
6. **Ingress created** → Clone accessible at `https://{customer_id}.clones.betaweb.ai`
7. **User polls status** → Gets `completed` when ready
8. **TTL expires (30min)** → CronJob auto-deletes clone

---

## Auto-Scaling Behavior

### Workers (KEDA)

```
Queue Depth  →  Worker Count
0-10 jobs    →  2 workers (minimum)
10-50 jobs   →  5 workers
50-100 jobs  →  10 workers
100+ jobs    →  20 workers (maximum)
```

### Nodes (Karpenter)

```
Pending Pods  →  New Nodes
1+ pods       →  Launch t2.small/t3.medium spot
Node full     →  Launch another node
Pods deleted  →  Consolidate after 10min idle
```

### Buffer Pool

- **2 t2.small nodes always running** (~$24/month)
- **Purpose**: Instant scheduling for first ~20 clones
- **No Pending time** for clones that fit in buffer

---

## Monitoring

### Check Clone Status

```bash
# Running clones
kubectl get pods -n wordpress-staging -l app=wordpress-clone

# Job queue depth
kubectl exec -n wordpress-staging redis-master-0 -- \
  redis-cli -a dramatiq-broker-password LLEN dramatiq

# Worker logs
kubectl logs -n wordpress-staging -l app=wp-k8s-service -c dramatiq-worker -f
```

### Check Infrastructure

```bash
# Buffer nodes
kubectl get nodes -l karpenter.sh/nodepool=buffer-pool

# Karpenter node claims
kubectl get nodeclaims

# KEDA scaling
kubectl get scaledobject -n wordpress-staging
```

---

## Cost

| Component | Monthly Cost |
|-----------|--------------|
| Buffer Nodes (2× t2.small spot) | ~$24 |
| General Pool (auto-scale) | ~$50-100 |
| Redis | $0 (self-hosted) |
| **Total** | **~$74-124/month** |

---

## Success Metrics

| Metric | Before (Sync) | After (Async) |
|--------|---------------|---------------|
| API Response Time | 60-180s | <100ms |
| Concurrent Clones | 1-2 | 50+ tested |
| Clone Success Rate | ~85% | >99% |
| Pending Time | N/A | 0s (buffer) / ~30s (scale) |

---

## Troubleshooting

### Clone Stuck in "Pending"

```bash
# Check queue depth
kubectl exec -n wordpress-staging redis-master-0 -- \
  redis-cli -a dramatiq-broker-password LLEN dramatiq

# Check workers
kubectl get pods -n wordpress-staging -l app=wp-k8s-service

# Check worker logs
kubectl logs -n wordpress-staging -l app=wp-k8s-service -c dramatiq-worker
```

### Clone in CrashLoopBackOff

```bash
# Check pod logs
kubectl logs -n wordpress-staging <pod-name> -c wordpress

# Delete deployment (worker will recreate with correct password)
kubectl delete deployment -n wordpress-staging <clone-name>
```

### Nodes Not Scaling

```bash
# Check Karpenter logs
kubectl logs -n karpenter -l app.kubernetes.io/name=karpenter

# Check pending pods
kubectl get pods --field-selector=status.phase=Pending
```

---

## Related Documentation

- [Async Clone-Restore Design](openspec/changes/async-clone-restore/README.md) - Detailed architecture
- [DRAMATIQ Setup](kubernetes/wp-k8s-service/DRAMATIQ_SETUP.md) - Worker configuration
- [Karpenter Buffer Pool](kubernetes/manifests/base/wp-k8s-service/karpenter-buffer-nodepool.yaml) - Warm standby config

---

## Postman Collection

Import the Postman collection from `Postman/` folder for pre-configured API requests.
