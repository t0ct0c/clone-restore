# WordPress Clone & Restore API

Simple API for cloning WordPress sites and restoring them to production.

## System Architecture

```mermaid
flowchart TD
    Start([User Request]) --> CloneOrRestore{Operation Type?}
    
    %% Clone Flow
    CloneOrRestore -->|Clone| CloneAPI[POST /api/v2/clone]
    CloneAPI --> CloneJob[Create Dramatiq Job]
    CloneJob --> CloneQueue[(Redis Queue)]
    CloneQueue --> CloneWorker[Dramatiq Worker]
    
    CloneWorker --> WarmPool{Warm Pool\nAvailable?}
    WarmPool -->|Yes| AssignPod[Assign Pod from Pool<br/>~5 seconds]
    WarmPool -->|No| ColdProvision[Cold Provision New Pod<br/>~80 seconds]
    
    AssignPod --> SetupWP[Setup WordPress<br/>in Parallel]
    ColdProvision --> SetupWP
    
    SetupWP --> ImportData[Import Source Data<br/>~50 seconds]
    ImportData --> CloneReady[Clone Ready]
    CloneReady --> CloneURL[Return Clone URL<br/>customer-id.clones.betaweb.ai]
    
    %% Restore Flow
    CloneOrRestore -->|Restore| RestoreAPI[POST /api/v2/restore]
    RestoreAPI --> RestoreJob[Create Dramatiq Job]
    RestoreJob --> RestoreQueue[(Redis Queue)]
    RestoreQueue --> RestoreWorker[Dramatiq Worker]
    
    RestoreWorker --> ExportSource[Export from Clone<br/>10% progress]
    ExportSource --> SetupTarget[Setup Target Site<br/>30% progress]
    SetupTarget --> ImportTarget[Import to Target<br/>50% progress]
    ImportTarget --> Verify[Verify Import<br/>100% progress]
    Verify --> RestoreComplete[Restore Complete]
    
    %% Status Polling
    CloneURL --> PollStatus[Client Polls Status]
    RestoreComplete --> PollStatus
    PollStatus --> StatusAPI[GET /api/v2/job-status/job-id]
    StatusAPI --> StatusCheck{Status?}
    StatusCheck -->|pending| PollStatus
    StatusCheck -->|in_progress| PollStatus
    StatusCheck -->|completed| Done([Done])
    StatusCheck -->|failed| Error([Error])
    
    %% Styling
    classDef apiClass fill:#4CAF50,stroke:#2E7D32,color:#fff
    classDef queueClass fill:#2196F3,stroke:#1565C0,color:#fff
    classDef workerClass fill:#FF9800,stroke:#E65100,color:#fff
    classDef decisionClass fill:#9C27B0,stroke:#6A1B9A,color:#fff
    
    class CloneAPI,RestoreAPI,StatusAPI apiClass
    class CloneQueue,RestoreQueue queueClass
    class CloneWorker,RestoreWorker,AssignPod,ColdProvision,SetupWP,ImportData,ExportSource,SetupTarget,ImportTarget workerClass
    class CloneOrRestore,WarmPool,StatusCheck decisionClass
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
