# Async Clone/Restore - Implementation Tasks (Dramatiq + Redis)

**Created**: 2026-02-20  
**Status**: PLANNING  
**Timeline**: 3 weeks (reduced from 4 - Dramatiq is simpler than Celery)  
**Architecture**: Dramatiq workers in same pods as FastAPI  
**Broker**: Redis (Bitnami Helm chart)  
**Related**: [proposal.md](./proposal.md), [design.md](./design.md)

---

## Phase 1: Infrastructure Setup (Week 1)

### Task 1.0: Deploy Observability Stack (Grafana + Loki + Tempo)

**Priority**: HIGH  
**Effort**: 3 hours  
**Dependencies**: None  
**Cost**: ~$40/month (EBS storage + EC2 for EKS pods)

**Steps**:

1. Create observability namespace and add Helm repos
   ```bash
   kubectl create namespace observability
   helm repo add grafana https://grafana.github.io/helm-charts
   helm repo update
   ```

2. Deploy Loki (log aggregation)
   ```bash
   helm install loki grafana/loki \
     --namespace observability \
     -f kubernetes/manifests/base/observability/loki-values.yaml
   ```

3. Deploy Tempo (distributed tracing)
   ```bash
   helm install tempo grafana/tempo \
     --namespace observability \
     -f kubernetes/manifests/base/observability/tempo-values.yaml
   ```

4. Deploy Grafana (visualization)
   ```bash
   helm install grafana grafana/grafana \
     --namespace observability \
     -f kubernetes/manifests/base/observability/grafana-values.yaml
   ```

5. Verify all components running
   ```bash
   kubectl get pods -n observability
   # Expected: loki-*, tempo-*, grafana-* all 1/1 Ready
   ```

6. Get Grafana admin password
   ```bash
   kubectl get secret grafana -n observability -o jsonpath='{.data.admin-password}' | base64 -d
   ```

7. Port-forward to access Grafana
   ```bash
   kubectl port-forward -n observability svc/grafana 3000:80
   # Access: http://localhost:3000 (admin/admin)
   ```

**Acceptance Criteria**:
- [ ] Loki pods running (backend, read, write, gateway)
- [ ] Tempo pods running (ingester, compactor, gateway)
- [ ] Grafana pod running (1/1 Ready)
- [ ] Grafana can access Loki data source
- [ ] Grafana can access Tempo data source
- [ ] Pre-configured dashboards imported

**Files Created**:
- `kubernetes/manifests/base/observability/loki-values.yaml`
- `kubernetes/manifests/base/observability/tempo-values.yaml`
- `kubernetes/manifests/base/observability/grafana-values.yaml`
- `kubernetes/manifests/base/observability/README.md`

---

### Task 1.1: Deploy Redis to Cluster

**Priority**: HIGH  
**Effort**: 2 hours  
**Dependencies**: None

**Steps**:
1. Add Redis Helm repository
   ```bash
   helm repo add bitnami https://charts.bitnami.com/bitnami
   helm repo update
   ```

2. Create Redis values file
   ```bash
   mkdir -p kubernetes/manifests/base/redis
   cat > kubernetes/manifests/base/redis/values.yaml <<EOF
   architecture: standalone
   auth:
     enabled: true
     password: "$(openssl rand -base64 32)"
   master:
     persistence:
       enabled: false
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
   EOF
   ```

3. Deploy Redis
   ```bash
   helm install redis bitnami/redis -n wordpress-staging -f kubernetes/manifests/base/redis/values.yaml
   ```

4. Verify deployment
   ```bash
   kubectl get pods -n wordpress-staging -l app.kubernetes.io/name=redis
   kubectl get svc -n wordpress-staging redis-headless
   ```

**Acceptance Criteria**:
- [ ] Redis pod running (1/1 Ready)
- [ ] Redis service accessible from wp-k8s-service pod
- [ ] Metrics endpoint working (port 9127)

---

### Task 1.2: Create Jobs Database Table

**Priority**: HIGH  
**Effort**: 1 hour  
**Dependencies**: Task 1.1

**Steps**:
1. Connect to shared RDS instance
   ```bash
   kubectl run mysql-client --image=mysql:8.0 -n wordpress-staging -it --rm --restart=Never -- \
     mysql -h wordpress-staging-shared.xxx.us-east-1.rds.amazonaws.com -u admin -p
   ```

2. Create jobs table
   ```sql
   USE wordpress_staging_shared;
   
   CREATE TABLE jobs (
       job_id VARCHAR(36) PRIMARY KEY,
       type ENUM('clone', 'restore', 'delete') NOT NULL,
       status ENUM('pending', 'running', 'completed', 'failed', 'cancelled') NOT NULL,
       progress INT DEFAULT 0,
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

3. Create database user for job_store
   ```sql
   CREATE USER 'job_store'@'%' IDENTIFIED BY '<generated_password>';
   GRANT SELECT, INSERT, UPDATE ON wordpress_staging_shared.jobs TO 'job_store'@'%';
   FLUSH PRIVILEGES;
   ```

4. Store credentials in Kubernetes Secret
   ```bash
   kubectl create secret generic job-store-config \
     --from-literal=database_url="mysql+aiomysql://job_store:<password>@wordpress-staging-shared.xxx.rds.amazonaws.com/jobs" \
     -n wordpress-staging
   ```

**Acceptance Criteria**:
- [ ] Jobs table created with correct schema
- [ ] Database user has correct permissions
- [ ] Secret created in wordpress-staging namespace
- [ ] Can connect from wp-k8s-service pod

---

### Task 1.3: Update Requirements.txt

**Priority**: HIGH  
**Effort**: 30 minutes  
**Dependencies**: None

**Steps**:
1. Add new dependencies to `kubernetes/wp-k8s-service/requirements.txt`
   ```
   # Existing dependencies
   fastapi>=0.109.0
   uvicorn>=0.27.0
   kubernetes>=29.0.0
   pydantic>=2.0.0
   loguru>=0.7.0
   pymysql>=1.1.0
   requests>=2.31.0
   opentelemetry-api>=1.20.0
   opentelemetry-sdk>=1.20.0
   opentelemetry-exporter-otlp>=1.20.0
   opentelemetry-instrumentation-fastapi>=0.41.0
   opentelemetry-instrumentation-requests>=0.41.0
   
   # NEW: Dramatiq async job queue
   dramatiq[redis,watch]>=2.0.0
   redis>=5.0.0
   sqlalchemy[asyncio]>=2.0.0
   aiomysql>=0.2.0
   ```

2. Update Dockerfile to install new dependencies
   ```dockerfile
   # kubernetes/wp-k8s-service/Dockerfile
   COPY requirements.txt .
   RUN pip install --no-cache-dir -r requirements.txt
   ```

**Acceptance Criteria**:
- [ ] All new packages install without errors
- [ ] Docker build succeeds
- [ ] No dependency conflicts

---

### Task 1.4: Create Dramatiq OTLP Middleware (Observability)

**Priority**: MEDIUM  
**Effort**: 2 hours  
**Dependencies**: Task 1.0 (Observability stack)

**Steps**:

1. Create Dramatiq middleware for OpenTelemetry tracing
   ```python
   # app/dramatiq_otel.py
   import dramatiq
   from opentelemetry import trace
   from opentelemetry.trace import Status, StatusCode
   from loguru import logger
   
   @dramatiq.middleware.Middleware
   class OpenTelemetryMiddleware:
       def after_process_boot(self, broker):
           self.tracer = trace.get_tracer("dramatiq")
           logger.info("Dramatiq OpenTelemetry middleware initialized")
       
       def before_process_message(self, broker, message):
           actor_name = message.actor_name
           job_id = message.args[0] if message.args else "unknown"
           
           span = self.tracer.start_span(f"process_{actor_name}")
           span.set_attribute("job_id", job_id)
           span.set_attribute("dramatiq.actor", actor_name)
           span.set_attribute("dramatiq.message_id", message.message_id)
           
           logger.info(f"📬 Starting task {actor_name} (job_id={job_id})")
           self.current_span = span
       
       def after_process_message(self, broker, message, *, result=None, exception=None):
           if exception:
               self.current_span.set_status(Status(StatusCode.ERROR))
               self.current_span.record_exception(exception)
               logger.error(f"❌ Task failed: {message.actor_name} (job_id={message.args[0]})")
           else:
               self.current_span.set_status(Status(StatusCode.OK))
               logger.info(f"✅ Task completed: {message.actor_name} (job_id={message.args[0]})")
           
           self.current_span.end()
   
   # Register middleware
   dramatiq.middleware.MiddlewareManager.add_middleware(OpenTelemetryMiddleware)
   ```

2. Import middleware in main.py
   ```python
   # app/main.py
   from .dramatiq_otel import OpenTelemetryMiddleware
   ```

3. Configure structured logging with job_id correlation
   ```python
   # app/main.py
   from loguru import logger
   import sys
   
   # Configure JSON logging for Loki
   logger.remove()
   logger.add(
       sys.stdout,
       format="{time:ISO8601} | {level:8} | {name} | {function} | {message}",
       level="INFO"
   )
   
   # Add job_id to context
   def add_job_id_to_logs(job_id: str):
       logger.contextualize(job_id=job_id)
   ```

**Acceptance Criteria**:
- [ ] Dramatiq tasks create spans in Tempo
- [ ] Logs include job_id for correlation
- [ ] Traces visible in Grafana Tempo datasource
- [ ] Logs visible in Grafana Loki datasource
- [ ] Can correlate traces with logs by job_id

---

### Task 1.5: Update wp-k8s-service Deployment (Dramatiq Sidecar)

**Priority**: HIGH  
**Effort**: 2 hours  
**Dependencies**: Tasks 1.0, 1.1, 1.2, 1.3, 1.4

**Note**: Dramatiq workers run as sidecar containers in the same pods as FastAPI (not separate deployment)

**Steps**:
1. Update deployment to add Dramatiq sidecar container
   ```yaml
   # kubernetes/manifests/base/wp-k8s-service/deployment.yaml
   apiVersion: apps/v1
   kind: Deployment
   metadata:
     name: wp-k8s-service
     namespace: wordpress-staging
   spec:
     replicas: 2
     selector:
       matchLabels:
         app: wp-k8s-service
     template:
       metadata:
         labels:
           app: wp-k8s-service
       spec:
         serviceAccountName: wp-k8s-service
         containers:
         - name: fastapi
           image: 044514005641.dkr.ecr.us-east-1.amazonaws.com/wp-k8s-service:latest
           command: ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
           ports:
           - containerPort: 8000
           env:
           - name: REDIS_URL
             value: "redis://:$(REDIS_PASSWORD)@redis-headless.redis:6379/0"
           - name: DATABASE_URL
             valueFrom:
               secretKeyRef:
                 name: job-store-config
                 key: database_url
           - name: OTEL_EXPORTER_OTLP_ENDPOINT
             value: "http://otel-collector.observability.svc.cluster.local:4318/v1/traces"
           resources:
             requests:
               cpu: "500m"
               memory: "512Mi"
             limits:
               cpu: "1000m"
               memory: "1Gi"
         - name: dramatiq-worker
           image: 044514005641.dkr.ecr.us-east-1.amazonaws.com/wp-k8s-service:latest
           command: ["dramatiq", "app.main", "--processes", "2", "--threads", "2"]
           env:
           - name: REDIS_URL
             value: "redis://:$(REDIS_PASSWORD)@redis-headless.redis:6379/0"
           - name: DATABASE_URL
             valueFrom:
               secretKeyRef:
                 name: job-store-config
                 key: database_url
           - name: OTEL_EXPORTER_OTLP_ENDPOINT
             value: "http://otel-collector.observability.svc.cluster.local:4318/v1/traces"
           resources:
             requests:
               cpu: "500m"
               memory: "512Mi"
             limits:
               cpu: "1000m"
               memory: "1Gi"
   ```

2. Deploy updated wp-k8s-service
   ```bash
   kubectl apply -f kubernetes/manifests/base/wp-k8s-service/deployment.yaml
   ```

3. Verify both containers running
   ```bash
   kubectl get pods -n wordpress-staging -l app=wp-k8s-service -o wide
   kubectl logs -n wordpress-staging -l app=wp-k8s-service -c dramatiq-worker --tail=20
   ```

**Acceptance Criteria**:
- [ ] 2/2 pods running with 2 containers each (fastapi + dramatiq-worker)
- [ ] Dramatiq worker connected to Redis (check logs)
- [ ] Dramatiq worker connected to database
- [ ] OpenTelemetry traces exported to Tempo
- [ ] Structured logs exported to Loki
- [ ] No crash loops
- [ ] HPA configured for combined resource usage
- [ ] HPA configured for combined resource usage

---

## Phase 2: Code Implementation (Week 2)

### Task 2.1: Implement Job Store (`job_store.py`)

**Priority**: HIGH  
**Effort**: 4 hours  
**Dependencies**: Task 1.2

**Steps**:
1. Create SQLAlchemy models
   ```python
   # kubernetes/wp-k8s-service/app/models.py
   from sqlalchemy import Column, String, Integer, Enum, DateTime, JSON, Text
   from sqlalchemy.ext.declarative import declarative_base
   from datetime import datetime
   import enum
   
   Base = declarative_base()
   
   class JobStatus(enum.Enum):
       PENDING = "pending"
       RUNNING = "running"
       COMPLETED = "completed"
       FAILED = "failed"
       CANCELLED = "cancelled"
   
   class JobType(enum.Enum):
       CLONE = "clone"
       RESTORE = "restore"
       DELETE = "delete"
   
   class Job(Base):
       __tablename__ = "jobs"
       
       job_id = Column(String(36), primary_key=True)
       type = Column(Enum(JobType), nullable=False)
       status = Column(Enum(JobStatus), nullable=False, default=JobStatus.PENDING)
       progress = Column(Integer, default=0)
       request_payload = Column(JSON, nullable=False)
       result = Column(JSON, nullable=True)
       error = Column(Text, nullable=True)
       created_at = Column(DateTime, default=datetime.utcnow)
       updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
       completed_at = Column(DateTime, nullable=True)
   ```

2. Implement JobStore class
   ```python
   # kubernetes/wp-k8s-service/app/job_store.py
   from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
   from sqlalchemy import select
   from .models import Job, JobStatus
   from typing import Optional, Dict, Any
   import os
   
   class JobStore:
       def __init__(self, database_url: str = None):
           self.database_url = database_url or os.getenv("DATABASE_URL")
           self.engine = create_async_engine(self.database_url)
           self.session_factory = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
       
       async def create(self, job_id: str, type: str, request_payload: Dict[str, Any]) -> Job:
           async with self.session_factory() as session:
               job = Job(
                   job_id=job_id,
                   type=type,
                   status=JobStatus.PENDING,
                   request_payload=request_payload
               )
               session.add(job)
               await session.commit()
               await session.refresh(job)
               return job
       
       async def get(self, job_id: str) -> Optional[Job]:
           async with self.session_factory() as session:
               result = await session.execute(select(Job).where(Job.job_id == job_id))
               return result.scalar_one_or_none()
       
       async def update_status(self, job_id: str, status: str, progress: int = None, 
                              result: Dict = None, error: str = None) -> Job:
           async with self.session_factory() as session:
               job = await self.get(job_id)
               job.status = status
               if progress is not None:
                   job.progress = progress
               if result is not None:
                   job.result = result
               if error is not None:
                   job.error = error
               await session.commit()
               await session.refresh(job)
               return job
   ```

**Acceptance Criteria**:
- [ ] JobStore class implemented
- [ ] Can create job records
- [ ] Can query job by ID
- [ ] Can update job status/progress
- [ ] Unit tests passing

---

### Task 2.2: Implement Celery Tasks (`celery_tasks.py`)

**Priority**: HIGH  
**Effort**: 6 hours  
**Dependencies**: Tasks 1.1, 1.4, 2.1

**Steps**:
1. Create Celery app configuration
   ```python
   # kubernetes/wp-k8s-service/app/celery_tasks.py
   from celery import Celery
   import os
   
   celery_app = Celery(
       'wp_clone_tasks',
       broker=os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
       backend=os.getenv('REDIS_URL', 'redis://localhost:6379/0')
   )
   
   celery_app.conf.update(
       task_serializer='json',
       accept_content=['json'],
       result_serializer='json',
       timezone='UTC',
       enable_utc=True,
       task_track_started=True,
       task_time_limit=600,  # 10 minute timeout
       task_soft_time_limit=540,  # 9 minute soft timeout
   )
   ```

2. Implement provision_clone task
   ```python
   @celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
   def provision_clone(self, job_id: str, request_data: dict):
       from .job_store import JobStore
       from .k8s_provisioner import K8sProvisioner
       
       job_store = JobStore()
       provisioner = K8sProvisioner(namespace='wordpress-staging')
       
       try:
           # Update: running (10%)
           job_store.update_status(job_id, "running", progress=10)
           
           # Extract parameters
           customer_id = request_data.get('customer_id')
           ttl_minutes = request_data.get('ttl_minutes', 60)
           source_url = request_data.get('source_url')
           
           # Update: creating database (20%)
           job_store.update_status(job_id, "running", progress=20, 
                                  status_message="Creating database...")
           
           # Create database
           db_password = provisioner._generate_password(32)
           provisioner._create_database_on_shared_rds(customer_id, db_password)
           
           # Update: creating Job (40%)
           job_store.update_status(job_id, "running", progress=40,
                                  status_message="Creating WordPress pod...")
           
           # Create Kubernetes Job
           provisioner._create_job(customer_id, ttl_minutes)
           
           # Update: waiting for pod (60%)
           job_store.update_status(job_id, "running", progress=60,
                                  status_message="Waiting for pod to be ready...")
           
           # Wait for pod
           provisioner._wait_for_pod_ready(customer_id, timeout=300)
           
           # Update: creating Service/Ingress (80%)
           job_store.update_status(job_id, "running", progress=80,
                                  status_message="Configuring networking...")
           
           # Create Service and Ingress
           provisioner._create_service(customer_id)
           provisioner._create_ingress(customer_id)
           
           # Update: configuring WordPress (90%)
           job_store.update_status(job_id, "running", progress=90,
                                  status_message="Configuring WordPress...")
           
           # Wait for WordPress and update URLs
           provisioner._wait_for_wordpress_ready(customer_id, timeout=180)
           provisioner.update_wordpress_urls(customer_id, 
                                            f"https://{customer_id}.clones.betaweb.ai")
           
           # Update: completed (100%)
           result = {
               "clone_url": f"https://{customer_id}.clones.betaweb.ai",
               "username": "admin",
               "password": "...",  # Retrieve from secret
               "expires_at": "..."
           }
           job_store.update_status(job_id, "completed", progress=100, result=result,
                                  status_message="Clone ready!")
           
           return {"success": True, "job_id": job_id, "result": result}
           
       except Exception as exc:
           # Retry logic
           if self.request.retries < self.max_retries:
               job_store.update_status(job_id, "running", 
                                      status_message=f"Retry {self.request.retries + 1}/3...")
               raise self.retry(exc=exc, countdown=2 ** self.request.retries)
           
           # Final failure
           job_store.update_status(job_id, "failed", error=str(exc),
                                  status_message=f"Failed: {str(exc)}")
           return {"success": False, "job_id": job_id, "error": str(exc)}
   ```

**Acceptance Criteria**:
- [ ] Celery task defined and registered
- [ ] Progress updates working (check database)
- [ ] Retry logic working (test with forced exception)
- [ ] Task completes successfully end-to-end
- [ ] Failed tasks marked as failed in database

---

### Task 2.3: Update FastAPI Endpoints (`main.py`)

**Priority**: HIGH  
**Effort**: 4 hours  
**Dependencies**: Tasks 2.1, 2.2

**Steps**:
1. Add async clone endpoint
   ```python
   # kubernetes/wp-k8s-service/app/main.py
   import uuid
   from .celery_tasks import provision_clone
   from .job_store import JobStore
   
   job_store = JobStore()
   
   @app.post("/api/v2/clone", response_model=JobResponse)
   async def clone_endpoint_async(request: CloneRequest):
       """
       Create WordPress clone (async, returns immediately)
       """
       job_id = f"clone-{uuid.uuid4().hex[:12]}"
       
       # Create job record
       await job_store.create(
           job_id=job_id,
           type="clone",
           request_payload=request.dict()
       )
       
       # Queue Celery task
       provision_clone.delay(job_id, request.dict())
       
       return JobResponse(
           job_id=job_id,
           status="pending",
           status_url=f"/api/v2/jobs/{job_id}"
       )
   
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
           type=job.type.value,
           status=job.status.value,
           progress=job.progress,
           created_at=job.created_at,
           updated_at=job.updated_at,
           result=job.result,
           error=job.error
       )
   
   @app.post("/api/v2/restore", response_model=JobResponse)
   async def restore_endpoint_async(request: RestoreRequest):
       """
       Restore WordPress clone (async, returns immediately)
       """
       # Similar implementation to clone_endpoint_async
   ```

2. Add Pydantic schemas
   ```python
   # kubernetes/wp-k8s-service/app/schemas.py
   from pydantic import BaseModel
   from typing import Optional, Dict, Any
   from datetime import datetime
   
   class JobResponse(BaseModel):
       job_id: str
       status: str
       status_url: str
       created_at: datetime = None
   
   class JobStatusResponse(BaseModel):
       job_id: str
       type: str
       status: str
       progress: int
       created_at: datetime
       updated_at: datetime
       result: Optional[Dict[str, Any]] = None
       error: Optional[str] = None
   ```

**Acceptance Criteria**:
- [ ] POST /api/v2/clone returns immediately (<100ms)
- [ ] GET /api/v2/jobs/{job_id} returns correct status
- [ ] Job appears in database immediately after POST
- [ ] Status updates as Celery task progresses
- [ ] Final result available when task completes

---

### Task 2.4: Add Pydantic Schemas (`schemas.py`)

**Priority**: MEDIUM  
**Effort**: 1 hour  
**Dependencies**: None

**Steps**:
1. Create all request/response schemas
   ```python
   # kubernetes/wp-k8s-service/app/schemas.py
   from pydantic import BaseModel, HttpUrl
   from typing import Optional, Dict, Any
   from datetime import datetime
   from enum import Enum
   
   class JobType(str, Enum):
       CLONE = "clone"
       RESTORE = "restore"
       DELETE = "delete"
   
   class JobStatusEnum(str, Enum):
       PENDING = "pending"
       RUNNING = "running"
       COMPLETED = "completed"
       FAILED = "failed"
       CANCELLED = "cancelled"
   
   # Request schemas
   class CloneRequest(BaseModel):
       source_url: HttpUrl
       ttl_minutes: int = 60
   
   class RestoreRequest(BaseModel):
       clone_id: str
       source_backup_url: HttpUrl
   
   # Response schemas
   class JobResponse(BaseModel):
       job_id: str
       type: JobType
       status: JobStatusEnum
       status_url: str
       created_at: datetime
   
   class JobStatusResponse(BaseModel):
       job_id: str
       type: JobType
       status: JobStatusEnum
       progress: int
       status_message: Optional[str] = None
       created_at: datetime
       updated_at: datetime
       completed_at: Optional[datetime] = None
       estimated_completion: Optional[datetime] = None
       result: Optional[Dict[str, Any]] = None
       error: Optional[str] = None
   ```

**Acceptance Criteria**:
- [ ] All schemas defined
- [ ] Type validation working
- [ ] API documentation shows correct schemas (Swagger UI)

---

## Phase 3: Testing (Week 3)

### Task 3.1: Unit Tests for Job Store

**Priority**: HIGH  
**Effort**: 3 hours  
**Dependencies**: Task 2.1

**Steps**:
1. Create test file
   ```python
   # tests/test_job_store.py
   import pytest
   from app.job_store import JobStore
   from app.models import JobStatus, JobType
   
   @pytest.mark.asyncio
   async def test_create_job():
       job_store = JobStore()
       job = await job_store.create(
           job_id="test-123",
           type="clone",
           request_payload={"source_url": "https://example.com"}
       )
       assert job.job_id == "test-123"
       assert job.status == JobStatus.PENDING
   
   @pytest.mark.asyncio
   async def test_get_job():
       job_store = JobStore()
       job = await job_store.get("test-123")
       assert job is not None
       assert job.type == JobType.CLONE
   
   @pytest.mark.asyncio
   async def test_update_status():
       job_store = JobStore()
       job = await job_store.update_status(
           job_id="test-123",
           status="running",
           progress=50
       )
       assert job.status == JobStatus.RUNNING
       assert job.progress == 50
   ```

2. Run tests
   ```bash
   cd kubernetes/wp-k8s-service
   pytest tests/test_job_store.py -v
   ```

**Acceptance Criteria**:
- [ ] All unit tests passing
- [ ] Code coverage >80%
- [ ] No database connection leaks

---

### Task 3.2: Integration Tests for Celery Tasks

**Priority**: HIGH  
**Effort**: 4 hours  
**Dependencies**: Tasks 2.2, 3.1

**Steps**:
1. Create integration test
   ```python
   # tests/test_celery_tasks.py
   import pytest
   from app.celery_tasks import provision_clone
   from app.job_store import JobStore
   
   @pytest.mark.asyncio
   async def test_provision_clone_success():
       job_id = "test-clone-success"
       request_data = {
           "customer_id": job_id,
           "ttl_minutes": 60
       }
       
       # Execute task synchronously for testing
       result = provision_clone(job_id, request_data)
       
       assert result["success"] == True
       assert result["job_id"] == job_id
       
       # Verify job status in database
       job_store = JobStore()
       job = await job_store.get(job_id)
       assert job.status == "completed"
       assert job.progress == 100
   ```

2. Run integration tests
   ```bash
   pytest tests/test_celery_tasks.py -v --integration
   ```

**Acceptance Criteria**:
- [ ] Integration tests passing
- [ ] Celery task completes successfully
- [ ] Job status updated correctly in database

---

### Task 3.3: Load Test - 20 Concurrent Clones

**Priority**: HIGH  
**Effort**: 4 hours  
**Dependencies**: Tasks 3.1, 3.2

**Steps**:
1. Create load test script
   ```python
   # tests/load_test_async.py
   import asyncio
   import aiohttp
   import time
   
   API_BASE = "http://localhost:8000"
   
   async def create_clone(session, clone_id):
       start = time.time()
       async with session.post(f"{API_BASE}/api/v2/clone", 
                               json={"source_url": "https://betaweb.ai", "ttl_minutes": 60}) as resp:
           data = await resp.json()
           elapsed = time.time() - start
           return {
               "clone_id": clone_id,
               "job_id": data["job_id"],
               "response_time_ms": elapsed * 1000,
               "status": data["status"]
           }
   
   async def poll_job_status(session, job_id):
       while True:
           async with session.get(f"{API_BASE}/api/v2/jobs/{job_id}") as resp:
               data = await resp.json()
               if data["status"] in ["completed", "failed"]:
                   return data
               await asyncio.sleep(5)
   
   async def main():
       async with aiohttp.ClientSession() as session:
           # Create 20 clones concurrently
           tasks = [create_clone(session, f"load-test-{i}") for i in range(20)]
           results = await asyncio.gather(*tasks)
           
           print(f"Average response time: {sum(r['response_time_ms'] for r in results) / len(results):.2f}ms")
           print(f"All jobs created: {len([r for r in results if r['status'] == 'pending'])}/20")
           
           # Poll all jobs to completion
           status_tasks = [poll_job_status(session, r["job_id"]) for r in results]
           final_statuses = await asyncio.gather(*status_tasks)
           
           completed = len([s for s in final_statuses if s["status"] == "completed"])
           failed = len([s for s in final_statuses if s["status"] == "failed"])
           print(f"Completed: {completed}/20, Failed: {failed}/20")
   
   asyncio.run(main())
   ```

2. Run load test
   ```bash
   python tests/load_test_async.py
   ```

**Acceptance Criteria**:
- [ ] All 20 clone requests accepted (<100ms response time)
- [ ] At least 18/20 clones complete successfully
- [ ] No database connection errors
- [ ] No Redis connection errors
- [ ] Celery workers scale appropriately

---

### Task 3.4: Chaos Test - Kill Worker Mid-Operation

**Priority**: MEDIUM  
**Effort**: 2 hours  
**Dependencies**: Task 3.3

**Steps**:
1. Start a clone operation
   ```bash
   curl -X POST http://localhost:8000/api/v2/clone \
     -H "Content-Type: application/json" \
     -d '{"source_url": "https://betaweb.ai", "ttl_minutes": 60}'
   ```

2. While operation is running, kill a Celery worker pod
   ```bash
   kubectl delete pod -n wordpress-staging -l app=celery-workers --random
   ```

3. Verify job recovers and completes
   ```bash
   watch -n 2 'curl -s http://localhost:8000/api/v2/jobs/{job_id} | python3 -m json.tool'
   ```

**Acceptance Criteria**:
- [ ] Job status remains "running" after pod deletion
- [ ] Celery retries the task automatically
- [ ] Job completes successfully despite worker failure
- [ ] No data loss in job_store

---

## Phase 4: Rollout (Week 4)

### Task 4.1: Deploy to Staging

**Priority**: HIGH  
**Effort**: 2 hours  
**Dependencies**: All Phase 3 tasks

**Steps**:
1. Build and push new Docker image
   ```bash
   cd kubernetes/wp-k8s-service
   docker build -t 044514005641.dkr.ecr.us-east-1.amazonaws.com/wp-k8s-service:async-v1 .
   docker push 044514005641.dkr.ecr.us-east-1.amazonaws.com/wp-k8s-service:async-v1
   ```

2. Update deployment manifests
   ```bash
   kubectl set image deployment/wp-k8s-service wp-k8s-service=044514005641.dkr.ecr.us-east-1.amazonaws.com/wp-k8s-service:async-v1 -n wordpress-staging
   kubectl set image deployment/celery-workers celery-worker=044514005641.dkr.ecr.us-east-1.amazonaws.com/wp-k8s-service:async-v1 -n wordpress-staging
   ```

3. Verify deployment
   ```bash
   kubectl rollout status deployment/wp-k8s-service -n wordpress-staging
   kubectl rollout status deployment/celery-workers -n wordpress-staging
   ```

**Acceptance Criteria**:
- [ ] wp-k8s-service deployment successful
- [ ] Celery workers deployment successful
- [ ] No pod crash loops
- [ ] Health endpoint returns 200

---

### Task 4.2: Run Bulk Clone Test in Staging

**Priority**: HIGH  
**Effort**: 3 hours  
**Dependencies**: Task 4.1

**Steps**:
1. Update bulk create script for async API
   ```python
   # scripts/bulk-create-clones-async.py
   import asyncio
   import aiohttp
   
   async def create_clone_async(session, clone_id):
       async with session.post("http://localhost:8000/api/v2/clone",
                               json={"source_url": "https://betaweb.ai", "ttl_minutes": 60}) as resp:
           return await resp.json()
   
   # Run 20 clones
   async with aiohttp.ClientSession() as session:
       tasks = [create_clone_async(session, f"bulk-async-{i}") for i in range(20)]
       results = await asyncio.gather(*tasks)
   ```

2. Execute bulk test
   ```bash
   python3 scripts/bulk-create-clones-async.py
   ```

3. Monitor progress
   ```bash
   kubectl get jobs -n wordpress-staging -w
   kubectl get pods -n wordpress-staging -w
   ```

**Acceptance Criteria**:
- [ ] 20 clones created successfully
- [ ] Average API response time <100ms
- [ ] All jobs reach "completed" status
- [ ] No resource quota violations

---

### Task 4.3: Monitor for 1 Week

**Priority**: HIGH  
**Effort**: 1 hour/day  
**Dependencies**: Task 4.2

**Monitoring Checklist**:
- [ ] Check Celery queue depth daily (should be <10)
- [ ] Verify job success rate >95%
- [ ] Monitor Redis memory usage (<80%)
- [ ] Check for any failed jobs in database
- [ ] Review Celery worker logs for errors
- [ ] Verify HPA scaling correctly

**Grafana Dashboards to Create**:
1. Async Jobs Overview
   - Jobs created per hour
   - Job success/failure rate
   - Average job duration
2. Celery Workers
   - Queue depth over time
   - Task execution time (P50, P95, P99)
   - Worker pod CPU/memory
3. Redis
   - Memory usage
   - Connection count
   - Command rate

---

### Task 4.4: Production Rollout

**Priority**: HIGH  
**Effort**: 4 hours  
**Dependencies**: Task 4.3

**Rollout Plan**:

**Day 1: 10% Traffic**
```bash
# Update ingress to route 10% to async endpoints
kubectl patch ingress wp-k8s-service -n wordpress-staging --type='json' -p='[{"op": "replace", "path": "/metadata/annotations/traefik.ingress.kubernetes.io~1router.priority", "value": "10"}]'
```

**Day 3: 50% Traffic**
```bash
# Increase to 50%
kubectl patch ingress wp-k8s-service -n wordpress-staging --type='json' -p='[{"op": "replace", "path": "/metadata/annotations/traefik.ingress.kubernetes.io~1router.priority", "value": "50"}]'
```

**Day 7: 100% Traffic**
```bash
# Full rollout
kubectl patch ingress wp-k8s-service -n wordpress-staging --type='json' -p='[{"op": "replace", "path": "/metadata/annotations/traefik.ingress.kubernetes.io~1router.priority", "value": "100"}]'
```

**Acceptance Criteria**:
- [ ] 10% traffic for 2 days with no issues
- [ ] 50% traffic for 4 days with no issues
- [ ] 100% traffic with success rate >99%
- [ ] No performance degradation
- [ ] Rollback plan tested and ready

---

## Rollback Plan

If issues occur during rollout:

1. **Immediate Rollback** (<5 minutes)
   ```bash
   kubectl rollout undo deployment/wp-k8s-service -n wordpress-staging
   kubectl rollout undo deployment/celery-workers -n wordpress-staging
   ```

2. **Database Cleanup**
   ```sql
   DELETE FROM jobs WHERE status IN ('pending', 'running') AND created_at < NOW() - INTERVAL 1 HOUR;
   ```

3. **Redis Flush** (if queue corrupted)
   ```bash
   kubectl exec -n wordpress-staging redis-master-0 -- redis-cli FLUSHDB
   ```

---

## Definition of Done

- [ ] All 14 tasks completed
- [ ] Unit tests passing (>80% coverage)
- [ ] Integration tests passing
- [ ] Load test: 20 concurrent clones successful
- [ ] Chaos test: Worker failure recovery verified
- [ ] Staging deployment successful
- [ ] Production rollout complete (100% traffic)
- [ ] Monitoring dashboards created
- [ ] Runbook documented
- [ ] Team trained on new architecture

---

## Timeline Summary

| Phase | Duration | Tasks | Status |
|-------|----------|-------|--------|
| **Phase 1: Infrastructure** | Week 1 | 1.1-1.4 | PLANNING |
| **Phase 2: Code Implementation** | Week 2 | 2.1-2.4 | PLANNING |
| **Phase 3: Testing** | Week 3 | 3.1-3.4 | PLANNING |
| **Phase 4: Rollout** | Week 4 | 4.1-4.4 | PLANNING |

**Total Effort**: ~50 hours  
**Total Duration**: 4 weeks  
**Risk Level**: Medium (mitigated by gradual rollout)
