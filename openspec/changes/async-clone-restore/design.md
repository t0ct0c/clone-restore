# Async Clone/Restore - Technical Design

**Created**: 2026-02-20  
**Status**: DRAFT  
**Related**: [proposal.md](./proposal.md)

---

## Architecture Overview

```
┌──────────────┐     ┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Client     │────▶│  FastAPI    │────▶│    Redis      │────▶│   Celery    │
│  (Browser)   │◀────│  (API Layer)│◀────│  (Job Queue)  │◀────│  (Workers)  │
└──────────────┘     └─────────────┘     └──────────────┘     └─────────────┘
       │                    │                                        │
       │ GET /jobs/{id}     │ Query Job Status                       │ Execute Clone
       │───────────────────▶│                                        │ Tasks
       │                    │                                        │
       │◀───────────────────│                                        │
       │  Job Status JSON   │                                        │
       │                    │                                        │
       │                    │                                        ▼
       │                    │                              ┌─────────────────┐
       │                    │                              │  K8sProvisioner │
       │                    │                              │  (Async Tasks)  │
       │                    │                              └─────────────────┘
       │                    │                                        │
       │                    │                                        ▼
       │                    │                              ┌─────────────────┐
       │                    │                              │  Kubernetes     │
       │                    │                              │  (Jobs/Pods)    │
       │                    │                              └─────────────────┘
```

---

## Component Design

### 1. FastAPI Layer (`main.py`)

#### New Endpoints

```python
# POST /api/v2/clone (async)
@app.post("/api/v2/clone", response_model=JobResponse)
async def clone_endpoint_async(request: CloneRequest):
    """
    Create WordPress clone (async, returns immediately)
    """
    job_id = f"clone-{uuid.uuid4().hex[:12]}"
    
    # Create job record in database
    await job_store.create(
        job_id=job_id,
        type="clone",
        status="pending",
        request_payload=request.dict()
    )
    
    # Queue Celery task
    celery_tasks.provision_clone.delay(job_id, request.dict())
    
    return JobResponse(
        job_id=job_id,
        status="pending",
        status_url=f"/api/v2/jobs/{job_id}"
    )

# GET /api/v2/jobs/{job_id}
@app.get("/api/v2/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    """
    Get job status and progress
    """
    job = await job_store.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    
    return JobStatusResponse(
        job_id=job.job_id,
        type=job.type,
        status=job.status,
        progress=job.progress,
        created_at=job.created_at,
        updated_at=job.updated_at,
        result=job.result,
        error=job.error
    )

# POST /api/v2/restore (async)
@app.post("/api/v2/restore", response_model=JobResponse)
async def restore_endpoint_async(request: RestoreRequest):
    """
    Restore WordPress clone (async, returns immediately)
    """
    # Similar pattern to clone_endpoint_async
```

#### Backward Compatibility Layer

```python
# Keep existing sync endpoints for gradual migration
@app.post("/api/v1/clone", response_model=CloneResponse)
async def clone_endpoint_sync(request: CloneRequest, async_mode: bool = False):
    """
    Create WordPress clone (sync for backward compatibility)
    If async_mode=true, delegates to async endpoint
    """
    if async_mode:
        return await clone_endpoint_async(request)
    
    # Existing synchronous implementation
    provisioner = K8sProvisioner()
    result = await provisioner.provision_target(customer_id, ttl_minutes)
    return CloneResponse(**result)
```

### 2. Job Store (`job_store.py`)

#### Database Schema (MySQL on RDS)

```sql
CREATE TABLE jobs (
    job_id VARCHAR(36) PRIMARY KEY,
    type ENUM('clone', 'restore', 'delete') NOT NULL,
    status ENUM('pending', 'running', 'completed', 'failed', 'cancelled') NOT NULL,
    progress INT DEFAULT 0,  -- 0-100
    request_payload JSON NOT NULL,
    result JSON NULL,
    error TEXT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    completed_at TIMESTAMP NULL,
    ttl_expires_at TIMESTAMP NULL,
    
    INDEX idx_status (status),
    INDEX idx_type (type),
    INDEX idx_created_at (created_at)
);
```

#### Python Interface

```python
# app/job_store.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import select

class JobStore:
    def __init__(self, database_url: str):
        self.engine = create_async_engine(database_url)
    
    async def create(self, job_id: str, type: str, status: str, request_payload: dict):
        """Create new job record"""
        async with AsyncSession(self.engine) as session:
            job = Job(
                job_id=job_id,
                type=type,
                status=status,
                request_payload=request_payload
            )
            session.add(job)
            await session.commit()
    
    async def get(self, job_id: str) -> Optional[Job]:
        """Get job by ID"""
        async with AsyncSession(self.engine) as session:
            result = await session.execute(select(Job).where(Job.job_id == job_id))
            return result.scalar_one_or_none()
    
    async def update_status(self, job_id: str, status: str, progress: int = None, result: dict = None, error: str = None):
        """Update job status and progress"""
        async with AsyncSession(self.engine) as session:
            job = await self.get(job_id)
            job.status = status
            if progress is not None:
                job.progress = progress
            if result is not None:
                job.result = result
            if error is not None:
                job.error = error
            await session.commit()
```

### 3. Celery Workers (`celery_tasks.py`)

#### Task Definitions

```python
# app/celery_tasks.py
from celery import Celery, current_task
from .k8s_provisioner import K8sProvisioner
from .job_store import JobStore

celery_app = Celery(
    'wp_clone_tasks',
    broker='redis://redis:6379/0',
    backend='redis://redis:6379/0'
)

job_store = JobStore()
provisioner = K8sProvisioner()

@celery_app.task(bind=True, max_retries=3)
def provision_clone(self, job_id: str, request_data: dict):
    """
    Provision WordPress clone (Celery task with progress tracking)
    """
    try:
        # Update status: running
        job_store.update_status(job_id, "running", progress=10)
        
        # Step 1: Create credentials (10%)
        customer_id = request_data.get('customer_id')
        ttl_minutes = request_data.get('ttl_minutes', 60)
        job_store.update_status(job_id, "running", progress=20)
        
        # Step 2: Create database (20-40%)
        db_password = provisioner._generate_password(32)
        provisioner._create_database_on_shared_rds(customer_id, db_password)
        job_store.update_status(job_id, "running", progress=40)
        
        # Step 3: Create Kubernetes Job (40-60%)
        provisioner._create_job(customer_id, ttl_minutes)
        job_store.update_status(job_id, "running", progress=60)
        
        # Step 4: Wait for pod ready (60-80%)
        provisioner._wait_for_pod_ready(customer_id, timeout=300)
        job_store.update_status(job_id, "running", progress=80)
        
        # Step 5: Create Service and Ingress (80-90%)
        provisioner._create_service(customer_id)
        provisioner._create_ingress(customer_id)
        job_store.update_status(job_id, "running", progress=90)
        
        # Step 6: Configure WordPress (90-100%)
        provisioner._wait_for_wordpress_ready(customer_id, timeout=180)
        provisioner.update_wordpress_urls(customer_id, public_url)
        job_store.update_status(job_id, "running", progress=100)
        
        # Complete
        result = {
            "clone_url": f"https://{customer_id}.clones.betaweb.ai",
            "username": "admin",
            "password": "...",  # From secret
            "expires_at": "..."
        }
        job_store.update_status(job_id, "completed", progress=100, result=result)
        
        return {"success": True, "job_id": job_id, "result": result}
        
    except Exception as exc:
        # Retry with exponential backoff
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)
    
    except Exception as exc:
        # Final failure after retries
        job_store.update_status(job_id, "failed", error=str(exc))
        return {"success": False, "job_id": job_id, "error": str(exc)}

@celery_app.task(bind=True)
def restore_clone(self, job_id: str, request_data: dict):
    """
    Restore WordPress clone (similar pattern)
    """
    # Implementation similar to provision_clone
```

#### Progress Tracking

```python
# Update progress throughout operation
job_store.update_status(job_id, "running", progress=25)  # 25% complete
job_store.update_status(job_id, "running", progress=50)  # 50% complete
job_store.update_status(job_id, "running", progress=75)  # 75% complete
```

### 4. Kubernetes Deployment (`deployment.yaml`)

#### Celery Worker Deployment

```yaml
# kubernetes/manifests/base/celery-workers/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: celery-workers
  namespace: wordpress-staging
spec:
  replicas: 3
  selector:
    matchLabels:
      app: celery-workers
  template:
    metadata:
      labels:
        app: celery-workers
    spec:
      serviceAccountName: wp-k8s-service
      containers:
      - name: celery-worker
        image: 044514005641.dkr.ecr.us-east-1.amazonaws.com/wp-k8s-service:latest
        command: ["celery", "-A", "app.celery_tasks.celery_app", "worker", "--loglevel=info", "--concurrency=4"]
        env:
        - name: REDIS_URL
          value: "redis://redis-headless.redis:6379/0"
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: shared-rds-config
              key: database_url
        resources:
          requests:
            cpu: "500m"
            memory: "512Mi"
          limits:
            cpu: "2000m"
            memory: "2Gi"
```

#### HPA for Celery Workers

```yaml
# kubernetes/manifests/base/celery-workers/hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: celery-workers-hpa
  namespace: wordpress-staging
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: celery-workers
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Pods
    pods:
      metric:
        name: celery_queue_depth
      target:
        type: AverageValue
        averageValue: "10"
```

### 5. Redis Configuration

#### Helm Chart Values

```yaml
# kubernetes/manifests/base/redis/values.yaml
architecture: standalone
auth:
  enabled: true
  password: "<generated>"
master:
  persistence:
    enabled: false  # Queue doesn't need persistence
  resources:
    requests:
      cpu: "100m"
      memory: "128Mi"
    limits:
      cpu: "500m"
      memory: "512Mi"
metrics:
  enabled: true
  serviceMonitor:
    enabled: true
```

---

## API Response Schemas

### JobResponse (immediate)

```json
{
  "job_id": "clone-a1b2c3d4e5f6",
  "type": "clone",
  "status": "pending",
  "status_url": "/api/v2/jobs/clone-a1b2c3d4e5f6",
  "created_at": "2026-02-20T10:30:00Z"
}
```

### JobStatusResponse (polling)

```json
{
  "job_id": "clone-a1b2c3d4e5f6",
  "type": "clone",
  "status": "running",
  "progress": 45,
  "status_message": "Creating WordPress database...",
  "created_at": "2026-02-20T10:30:00Z",
  "updated_at": "2026-02-20T10:30:15Z",
  "estimated_completion": "2026-02-20T10:32:00Z",
  "result": null,
  "error": null
}
```

### JobStatusResponse (completed)

```json
{
  "job_id": "clone-a1b2c3d4e5f6",
  "type": "clone",
  "status": "completed",
  "progress": 100,
  "status_message": "Clone ready",
  "created_at": "2026-02-20T10:30:00Z",
  "updated_at": "2026-02-20T10:32:00Z",
  "completed_at": "2026-02-20T10:32:00Z",
  "result": {
    "clone_url": "https://clone-a1b2c3d4e5f6.clones.betaweb.ai",
    "username": "admin",
    "password": "NpbdokYzSDkRttLg",
    "expires_at": "2026-02-20T11:30:00Z"
  },
  "error": null
}
```

---

## File Structure

```
kubernetes/wp-k8s-service/
├── app/
│   ├── main.py                    # FastAPI endpoints (modified)
│   ├── k8s_provisioner.py         # K8sProvisioner (async methods)
│   ├── celery_tasks.py            # NEW: Celery task definitions
│   ├── job_store.py               # NEW: Database job storage
│   ├── models.py                  # NEW: SQLAlchemy models
│   ├── schemas.py                 # NEW: Pydantic schemas
│   └── config.py                  # Configuration loader
├── kubernetes/manifests/
│   ├── base/
│   │   ├── wp-k8s-service/        # Existing API deployment
│   │   ├── celery-workers/        # NEW: Celery worker deployment
│   │   └── redis/                 # NEW: Redis Helm values
│   └── overlays/
│       └── staging/
├── requirements.txt               # Add: celery, redis, sqlalchemy
└── Dockerfile                     # Update: Celery worker command
```

---

## Migration Plan

### Phase 1: Infrastructure (Week 1)

1. Deploy Redis to wordpress-staging namespace
2. Create jobs table in shared RDS
3. Deploy Celery workers (2 replicas)
4. Test connectivity (API → Redis → Workers → K8s)

### Phase 2: Code Changes (Week 2)

1. Implement `job_store.py` with SQLAlchemy
2. Implement `celery_tasks.py` with progress tracking
3. Update `main.py` with async endpoints
4. Add `GET /api/v2/jobs/{job_id}` endpoint

### Phase 3: Testing (Week 3)

1. Unit tests for job_store
2. Integration tests for Celery tasks
3. Load test: 20 concurrent clone requests
4. Chaos test: Kill worker pod mid-operation

### Phase 4: Rollout (Week 4)

1. Deploy to staging environment
2. Run bulk clone test (`scripts/bulk-create-clones.py`)
3. Monitor for 1 week
4. Gradual production rollout (10% → 50% → 100%)

---

## Monitoring & Observability

### Celery Metrics (Prometheus)

```python
# Expose Celery metrics
from prometheus_client import Counter, Histogram

celery_tasks_total = Counter('celery_tasks_total', 'Total Celery tasks', ['task_name', 'status'])
celery_task_duration = Histogram('celery_task_duration_seconds', 'Task duration', ['task_name'])
celery_queue_depth = Gauge('celery_queue_depth', 'Current queue depth')
```

### Grafana Dashboard Panels

1. **Queue Depth Over Time**
2. **Task Success/Failure Rate**
3. **Task Duration (P50, P95, P99)**
4. **Worker Pod CPU/Memory**
5. **Redis Memory Usage**
6. **Concurrent Clone Operations**

### Alerts

- `celery_queue_depth > 50` for 5min → Scale workers
- `celery_task_failure_rate > 5%` for 10min → Page on-call
- `redis_memory_usage > 80%` → Investigate memory leak

---

## References

- [Celery Best Practices](https://docs.celeryq.dev/en/stable/userguide/best-practices.html)
- [FastAPI Async SQL](https://fastapi.tiangolo.com/tutorial/sql-databases/)
- [Kubernetes Jobs](https://kubernetes.io/docs/concepts/workloads/controllers/job/)
- Related: `kubernetes/wp-k8s-service/app/k8s_provisioner.py` (existing provisioner)
