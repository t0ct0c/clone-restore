# WordPress Clone & Restore API

Simple API for cloning WordPress sites and restoring them to production.

## System Architecture

### Infrastructure Overview (Current Production)
- **Cluster:** EKS (wp-clone-restore) in us-east-1
- **Namespace:** wordpress-staging
- **Workers:** 4 concurrent (2 processes × 2 threads)
- **Load Balancer:** Traefik (TLS termination)
- **Queue:** Redis (async job processing via Dramatiq)
- **Storage:** Local MySQL sidecar per pod (no shared DB bottleneck)
- **Domain:** *.clones.betaweb.ai
- **Warm Pool:** 2-20 pods (dynamic scaling based on queue depth)

### Architecture Diagram

This diagram shows the complete clone workflow from user request to cleanup. Green boxes are API endpoints, blue is Redis queue, orange is worker operations, purple is decision points, navy is Kubernetes operations, and cyan is warm pool components.

```mermaid
flowchart TD
    Start([User Request]) --> CloneOrRestore{Operation Type?}
    
    %% Clone Flow
    CloneOrRestore -->|Clone| CloneAPI[POST /api/v2/clone<br/>Returns job_id immediately]
    CloneAPI --> CloneJob[Dramatiq Job Created]
    CloneJob --> RedisQueue[(Redis Queue)]
    RedisQueue --> Worker[Dramatiq Worker]
    
    Worker --> PoolCheck{Warm Pool<br/>Available?}
    
    %% Warm Pool Path (Fast: pre-configured pods)
    PoolCheck -->|Yes<br/>Pod ready| WarmAssign[Assign Warm Pod<br/>INSTANT ~2s<br/>Atomic label update]
    WarmAssign --> TagPod[Tag Pod with<br/>Clone ID + TTL + Assigned]
    TagPod --> CreateSecret[Create Secret<br/>Clone credentials]
    
    %% Cold Provision Path (Slow: create from scratch)
    PoolCheck -->|No<br/>Pool empty| ColdDeploy[Create K8s Resources<br/>Pod + Service + Ingress<br/>~60-80 seconds]
    ColdDeploy --> WaitReady[Wait for Pod Ready<br/>WordPress + MySQL init]
    WaitReady --> ConfigWP[Run wp-install<br/>Set admin password]
    ConfigWP --> CreateSecret
    
    %% Common Path (both warm & cold)
    CreateSecret --> CreateService[Create Service<br/>ClusterIP]
    CreateService --> CreateIngress[Create Ingress<br/>Traefik routing<br/>clone-id.clones.betaweb.ai]
    CreateIngress --> CheckCache{Source API Key<br/>Cached?}
    CheckCache -->|Yes| UseCache[Use Cached Key<br/>~1 second]
    CheckCache -->|No| BrowserSetup[Browser Automation<br/>Login + Upload Plugin<br/>Get API key<br/>~30-40 seconds]
    BrowserSetup --> CacheKey[Cache API Key<br/>24hr TTL]
    CacheKey --> Export[REST: Export from Source<br/>~15-20 seconds]
    UseCache --> Export
    Export --> Import[REST: Import to Clone<br/>MySQL + Files<br/>~15-20 seconds]
    Import --> PostClone[Post-clone fixes<br/>Set HTTPS flag<br/>Update wp-config]
    PostClone --> CloneComplete[Clone Complete<br/>Status: completed<br/>Progress: 100%]
    
    %% Restore Flow
    CloneOrRestore -->|Restore| RestoreAPI[POST /api/v2/restore<br/>Returns job_id immediately]
    RestoreAPI --> RestoreJob[Dramatiq Job Created]
    RestoreJob --> RedisQueue
    RedisQueue --> RestoreWorker[Dramatiq Worker]
    
    RestoreWorker --> SourceSetup[Setup Source Clone<br/>10% progress]
    SourceSetup --> SourceExport[Export from Clone<br/>30% progress]
    SourceExport --> TargetSetup[Setup Target Site<br/>50% progress]
    TargetSetup --> TargetImport[Import to Production<br/>70% progress]
    TargetImport --> RestoreComplete[Restore Complete<br/>100% progress]
    
    %% Monitoring & Cleanup
    CloneComplete --> Monitor[GET /api/v2/jobs/job-id<br/>Poll for status]
    RestoreComplete --> Monitor
    Monitor --> StatusCheck{Status?}
    StatusCheck -->|pending/running| Monitor
    StatusCheck -->|completed| GetCreds[kubectl get secret<br/>Get WordPress password]
    StatusCheck -->|failed| ShowError([Error Message])
    GetCreds --> Access[Access Clone<br/>https://id.clones.betaweb.ai]
    
    %% TTL Cleanup (Automatic)
    CloneComplete --> TTL[TTL Cleaner CronJob<br/>Runs every 5 minutes<br/>Checks ttl-timestamp labels]
    TTL --> CheckExpiry{Clone<br/>Expired?}
    CheckExpiry -->|Yes<br/>Past TTL| DeleteAll[Delete Resources:<br/>1. Service<br/>2. Ingress<br/>3. Clone Secret<br/>4. Pod<br/>5. Pod Secret]
    CheckExpiry -->|No<br/>Still valid| WaitNext[Wait 5 minutes]
    WaitNext --> TTL
    DeleteAll --> PoolReplenish[Warm Pool Controller<br/>Creates new pod<br/>to maintain baseline]
    
    %% Infrastructure Components (Current Deployment)
    subgraph EKS["EKS Cluster: wp-clone-restore (us-east-1)"]
        subgraph NS["Namespace: wordpress-staging"]
            WarmPod1[Warm Pod 1<br/>pool-type=warm<br/>Pre-configured<br/>WordPress + MySQL]
            WarmPod2[Warm Pod 2<br/>pool-type=warm<br/>Pre-configured<br/>WordPress + MySQL]
            ClonePods[Assigned Pods<br/>pool-type=assigned<br/>Clone ID labels<br/>WordPress + MySQL]
            RedisQueue[(Redis Queue<br/>dramatiq:clone-queue<br/>Job persistence)]
            Worker[Dramatiq Workers<br/>4 concurrent<br/>2 processes × 2 threads<br/>Memory: 1Gi-4Gi]
            WPAPI[wp-k8s-service API<br/>FastAPI<br/>Port 8000]
        end
        Traefik[Traefik Ingress<br/>TLS Termination<br/>*.clones.betaweb.ai]
    end
    
    Internet([Internet<br/>HTTPS]) --> Traefik
    Traefik --> ClonePods
    WPAPI --> RedisQueue
    
    %% Styling
    classDef apiClass fill:#4CAF50,stroke:#2E7D32,color:#fff
    classDef queueClass fill:#2196F3,stroke:#1565C0,color:#fff
    classDef workerClass fill:#FF9800,stroke:#E65100,color:#fff
    classDef decisionClass fill:#9C27B0,stroke:#6A1B9A,color:#fff
    classDef k8sClass fill:#326CE5,stroke:#1A4D8F,color:#fff
    classDef poolClass fill:#00BCD4,stroke:#006064,color:#fff
    
    class CloneAPI,RestoreAPI,Monitor,WPAPI apiClass
    class RedisQueue queueClass
    class Worker,RestoreWorker,WarmAssign,Export,Import,SourceSetup,SourceExport,TargetSetup,TargetImport,BrowserSetup,UseCache,CacheKey,PostClone,ConfigWP,WaitReady workerClass
    class CloneOrRestore,PoolCheck,StatusCheck,CheckExpiry,CheckCache decisionClass
    class TagPod,CreateService,CreateIngress,ColdDeploy,DeleteAll,CreateSecret k8sClass
    class WarmPod1,WarmPod2,PoolReplenish,ClonePods poolClass
```

## Quick Start

### 1. Create a Clone

```bash
curl -X POST https://clones.betaweb.ai/api/v2/clone \
  -H "Content-Type: application/json" \
  -d '{
    "source_url": "https://betaweb.ai",
    "source_username": "Charles@toctoc.com.au",
    "source_password": "your-password",
    "customer_id": "my-clone-123",
    "ttl_minutes": 60
  }'
```

**Response:**
```json
{
  "job_id": "abc-123-xyz",
  "type": "clone",
  "status": "pending",
  "progress": 0,
  "created_at": "2026-02-26T06:47:54.247391",
  "ttl_expires_at": "2026-02-26T07:47:54.247395"
}
```

**Important:** Save the `job_id` - you'll need it to check status and get credentials!

### 2. Check Clone Status and Get Credentials

```bash
# Replace abc-123-xyz with your job_id from step 1
curl https://clones.betaweb.ai/api/v2/jobs/abc-123-xyz
```

Keep polling every 5-10 seconds until `status: "completed"` (~60-80 seconds)

**Response when complete:**
```json
{
  "job_id": "abc-123-xyz",
  "type": "clone",
  "status": "completed",
  "progress": 100,
  "result": {
    "public_url": "https://my-clone-123.clones.betaweb.ai",
    "internal_url": "http://my-clone-123.wordpress-staging.svc.cluster.local"
  }
}
```

### 3. Get Clone Credentials

The clone credentials are stored in a Kubernetes secret. You need to retrieve them:

```bash
# Get the password from the Kubernetes secret
kubectl get secret my-clone-123-credentials -n wordpress-staging \
  -o jsonpath='{.data.wordpress-password}' | base64 -d && echo
```

**Clone credentials:**
- **URL:** `https://my-clone-123.clones.betaweb.ai/wp-admin`
- **Username:** `admin` (always)
- **Password:** (from command above)

### 4. Make Changes to the Clone

1. Open `https://my-clone-123.clones.betaweb.ai/wp-admin` in your browser
2. Login with username `admin` and the password from step 3
3. Make your changes (edit pages, posts, settings, etc.)
4. Save your changes

### 5. Restore Clone to Production

Once you've made changes and are ready to push them to production:

```bash
curl -X POST https://clones.betaweb.ai/api/v2/restore \
  -H "Content-Type: application/json" \
  -d '{
    "source_url": "https://my-clone-123.clones.betaweb.ai",
    "source_username": "admin",
    "source_password": "password-from-step-3",
    "target_url": "https://betaweb.ai",
    "target_username": "Charles@toctoc.com.au",
    "target_password": "your-production-password",
    "customer_id": "restore-from-clone-123"
  }'
```

**Note:** Remove trailing slashes from URLs

**Response:**
```json
{
  "job_id": "def-456-xyz",
  "type": "restore",
  "status": "pending",
  "progress": 0
}
```

**Important:** Save the restore `job_id` to monitor progress!

### 6. Monitor Restore Progress

```bash
# Replace def-456-xyz with your restore job_id from step 5
curl https://clones.betaweb.ai/api/v2/jobs/def-456-xyz
```

Keep polling until `status: "completed"` (~60-90 seconds)

**Progress indicators:**
- `10%` - Job received and queued
- `30%` - Source setup complete
- `50%` - Target setup complete
- `70%` - Export from clone complete
- `100%` - Import to production complete

**Done!** Your changes are now live on `https://betaweb.ai`

## Timing

- **Clone creation:** 60-80 seconds (warm pool) / 80-120 seconds (cold provision)
- **Restore:** 60-90 seconds
- **Poll interval:** Every 5-10 seconds
- **Clone TTL:** Configurable (default 60 minutes, auto-deleted after expiry)

## Important Notes

### Clone Credentials
- Clone credentials are **NOT** returned in the API response
- You must retrieve the password from the Kubernetes secret using `kubectl`
- Username is always `admin`
- Credentials are stored in a secret named `{customer_id}-credentials`

### Job IDs
- **Save your job_id** from the clone/restore response
- You need it to check status: `GET /api/v2/jobs/{job_id}`
- Job IDs are UUIDs (e.g., `abc-123-xyz`)

### URLs
- Remove trailing slashes from URLs in API requests
- Clone URLs: `https://{customer_id}.clones.betaweb.ai`
- Internal URLs: `http://{customer_id}.wordpress-staging.svc.cluster.local`

### TTL and Auto-Cleanup
- Clones auto-delete after TTL expires (default 60 minutes)
- TTL cleaner runs every 5 minutes
- Extend TTL by setting `ttl_minutes` parameter when creating clone

## API Reference

All endpoints return JSON with a `job_id` for async operations.

### POST /api/v2/clone
Create a WordPress clone (non-blocking)

**Request Body:**
```json
{
  "source_url": "https://betaweb.ai",
  "source_username": "username",
  "source_password": "password",
  "customer_id": "unique-clone-id",
  "ttl_minutes": 60
}
```

**Response:** Returns immediately with `job_id`

### POST /api/v2/restore
Restore a clone to production (non-blocking)

**Request Body:**
```json
{
  "source_url": "https://clone-id.clones.betaweb.ai",
  "source_username": "admin",
  "source_password": "clone-password",
  "target_url": "https://production-site.com",
  "target_username": "target-username",
  "target_password": "target-password",
  "customer_id": "restore-job-id"
}
```

**Response:** Returns immediately with `job_id`

### GET /api/v2/jobs/{job_id}
Check status of any job (clone or restore)

**Response:**
```json
{
  "job_id": "abc-123-xyz",
  "type": "clone",
  "status": "completed",
  "progress": 100,
  "result": {
    "public_url": "https://clone-id.clones.betaweb.ai"
  },
  "error": null,
  "created_at": "2026-02-26T06:47:54.247391",
  "completed_at": "2026-02-26T06:49:00.123456",
  "ttl_expires_at": "2026-02-26T07:47:54.247395"
}
```

**Status values:** `pending`, `running`, `completed`, `failed`

## Additional Documentation

See `/docs` folder for architecture and implementation details.
