# Restore Async Optimization - Implementation Tasks

## Phase 1: Core Implementation

### Task 1: Add JobType.restore enum
**File**: `kubernetes/wp-k8s-service/app/job_store.py`
**Estimated Time**: 5 minutes

- [ ] Add `restore = "restore"` to JobType enum
- [ ] Test job creation with restore type

### Task 2: Create AsyncRestoreRequest model
**File**: `kubernetes/wp-k8s-service/app/main.py`
**Estimated Time**: 10 minutes

```python
class AsyncRestoreRequest(BaseModel):
    source_url: HttpUrl
    source_username: str
    source_password: str
    target_url: HttpUrl
    target_username: str
    target_password: str
    preserve_plugins: bool = True
    preserve_themes: bool = False
    customer_id: Optional[str] = None  # Optional: auto-generate if not provided
```

- [ ] Add model definition
- [ ] Add validation
- [ ] Generate customer_id if not provided

### Task 3: Create /api/v2/restore endpoint
**File**: `kubernetes/wp-k8s-service/app/main.py`
**Estimated Time**: 15 minutes

```python
@app.post("/api/v2/restore", response_model=JobStatusResponse, tags=["Async V2"])
async def restore_async(request: AsyncRestoreRequest):
    """Restore WordPress asynchronously (non-blocking)."""
    from .tasks import restore_wordpress
    from .job_store import get_job_store, JobType
    
    # Generate customer_id if not provided
    if not request.customer_id:
        request.customer_id = f"restore-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    
    job_store = get_job_store()
    job = await job_store.create_job(
        job_type=JobType.restore,
        request_payload=request.dict(),
    )
    restore_wordpress.send(job.job_id)
    logger.info(f"Enqueued async restore job {job.job_id}")
    return JobStatusResponse(**job.to_dict())
```

- [ ] Add endpoint implementation
- [ ] Add error handling
- [ ] Add logging

### Task 4: Create restore_wordpress Dramatiq task
**File**: `kubernetes/wp-k8s-service/app/tasks.py`
**Estimated Time**: 60 minutes

```python
@dramatiq.actor(queue_name="default", max_retries=0, time_limit=600_000)
async def restore_wordpress(job_id: str) -> Dict:
    """Restore WordPress site asynchronously."""
    from .browser_setup import setup_wordpress_with_browser
    from .main import perform_restore  # Extract restore logic from restore_endpoint
    
    job_store = get_job_store()
    
    try:
        job = await job_store.get_job(job_id)
        if not job:
            return {"success": False, "error": "Job not found"}
        
        request = job.request_payload
        source_url = request.get("source_url")
        source_username = request.get("source_username")
        source_password = request.get("source_password")
        target_url = request.get("target_url")
        target_username = request.get("target_username")
        target_password = request.get("target_password")
        preserve_plugins = request.get("preserve_plugins", True)
        preserve_themes = request.get("preserve_themes", False)
        
        logger.info(f"Starting restore job {job_id} from {source_url} to {target_url}")
        await job_store.update_job_status(job_id, JobStatus.running, progress=10)
        
        # Step 1: Setup source
        logger.info(f"Setting up source {source_url}")
        # Check if source is a clone first
        is_clone_source = "/clone-" in source_url or ".clones.betaweb.ai" in source_url
        
        if is_clone_source:
            # Try migration-master-key first for clones
            source_api_key = "migration-master-key"
        else:
            # Use browser automation for regular sites
            source_result = await setup_wordpress_with_browser(
                source_url, source_username, source_password, role="source"
            )
            if not source_result.get("success"):
                await job_store.update_job_status(
                    job_id, JobStatus.failed, error=source_result.get("message")
                )
                return {"success": False, "error": source_result.get("message")}
            source_api_key = source_result["api_key"]
        
        await job_store.update_job_status(job_id, JobStatus.running, progress=30)
        
        # Step 2: Setup target
        logger.info(f"Setting up target {target_url}")
        target_result = await setup_wordpress_with_browser(
            target_url, target_username, target_password, role="target"
        )
        if not target_result.get("success"):
            await job_store.update_job_status(
                job_id, JobStatus.failed, error=target_result.get("message")
            )
            return {"success": False, "error": target_result.get("message")}
        target_api_key = target_result["api_key"]
        
        await job_store.update_job_status(job_id, JobStatus.running, progress=50)
        
        # Step 3: Perform restore
        logger.info(f"Restoring from {source_url} to {target_url}")
        restore_result = perform_restore(
            source_url,
            source_api_key,
            target_url,
            target_api_key,
            preserve_plugins=preserve_plugins,
            preserve_themes=preserve_themes,
        )
        
        if not restore_result.get("success"):
            await job_store.update_job_status(
                job_id, JobStatus.failed, error=restore_result.get("message")
            )
            return {"success": False, "error": restore_result.get("message")}
        
        await job_store.update_job_status(
            job_id, JobStatus.completed, progress=100, result=restore_result
        )
        logger.info(f"Restore job {job_id} completed successfully")
        return {"success": True, **restore_result}
        
    except Exception as e:
        logger.error(f"Restore job {job_id} failed: {e}")
        await job_store.update_job_status(job_id, JobStatus.failed, error=str(e))
        return {"success": False, "error": str(e)}
```

- [ ] Implement task function
- [ ] Add progress tracking at each step
- [ ] Add error handling
- [ ] Add logging
- [ ] Handle clone detection for source

### Task 5: Extract perform_restore function
**File**: `kubernetes/wp-k8s-service/app/main.py`
**Estimated Time**: 30 minutes

Extract the core restore logic from `restore_endpoint` into a reusable function:

```python
def perform_restore(
    source_url: str,
    source_api_key: str,
    target_url: str,
    target_api_key: str,
    preserve_plugins: bool = True,
    preserve_themes: bool = False,
) -> Dict:
    """
    Perform WordPress restore operation.
    
    This is the core restore logic extracted from restore_endpoint
    so it can be reused by both sync and async endpoints.
    """
    # Move all the export/import logic here
    pass
```

- [ ] Extract core restore logic
- [ ] Make it reusable by both sync and async endpoints
- [ ] Add proper error handling
- [ ] Add detailed logging

### Task 6: Update old restore endpoint with deprecation notice
**File**: `kubernetes/wp-k8s-service/app/main.py`
**Estimated Time**: 10 minutes

```python
@app.post("/restore", response_model=RestoreResponse, deprecated=True)
async def restore_endpoint(request: RestoreRequest):
    """
    [DEPRECATED] Synchronous restore endpoint. Use /api/v2/restore instead.
    
    This endpoint is maintained for backward compatibility but will be removed
    in a future version. Please migrate to the async endpoint.
    """
    logger.warning("Legacy sync /restore endpoint called - recommend using /api/v2/restore")
    # Keep existing implementation
```

- [ ] Add deprecation warning
- [ ] Update docstring
- [ ] Add warning log

## Phase 2: Testing

### Task 7: Create restore test script
**File**: `scripts/restore-single.py`
**Estimated Time**: 30 minutes

```python
#!/usr/bin/env python3
"""
Single Restore Test - Uses async v2 API
Tests restore from clone to production with job status polling
"""
import requests
import json
import time
from datetime import datetime

API_BASE = "https://clones.betaweb.ai"
SOURCE_URL = "https://test-clone.clones.betaweb.ai"  # Clone source
SOURCE_USERNAME = "admin"
SOURCE_PASSWORD = "..."
TARGET_URL = "https://target-site.com"  # Production target
TARGET_USERNAME = "admin"
TARGET_PASSWORD = "..."

def restore_async(customer_id: str):
    """Start async restore job"""
    url = f"{API_BASE}/api/v2/restore"
    payload = {
        "source_url": SOURCE_URL,
        "source_username": SOURCE_USERNAME,
        "source_password": SOURCE_PASSWORD,
        "target_url": TARGET_URL,
        "target_username": TARGET_USERNAME,
        "target_password": TARGET_PASSWORD,
        "preserve_plugins": True,
        "preserve_themes": False,
        "customer_id": customer_id
    }
    
    response = requests.post(url, json=payload, headers={"Host": "clones.betaweb.ai"})
    return response.json()

def poll_job_status(job_id: str):
    """Poll job status until complete"""
    url = f"{API_BASE}/api/v2/job-status/{job_id}"
    
    while True:
        response = requests.get(url, headers={"Host": "clones.betaweb.ai"})
        job = response.json()
        
        status = job.get("status")
        progress = job.get("progress", 0)
        
        print(f"  Status: {status} ({progress}%)")
        
        if status in ["completed", "failed"]:
            return job
        
        time.sleep(5)

if __name__ == "__main__":
    customer_id = f"restore-test-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    
    print(f"🚀 Starting async restore: {customer_id}")
    print("=" * 60)
    
    # Start restore job
    result = restore_async(customer_id)
    job_id = result.get("job_id")
    
    print(f"✓ Job submitted: {job_id}")
    print(f"⏳ Waiting for restore to complete...")
    
    # Poll for completion
    start_time = time.time()
    final_job = poll_job_status(job_id)
    duration = time.time() - start_time
    
    if final_job.get("status") == "completed":
        print(f"✓ Restore completed! ({int(duration)}s)")
        print(json.dumps(final_job.get("result"), indent=2))
    else:
        print(f"❌ Restore failed: {final_job.get('error')}")
```

- [ ] Create test script
- [ ] Test with clone source
- [ ] Test with regular WordPress source
- [ ] Test error cases

### Task 8: Run integration tests
**Estimated Time**: 30 minutes

- [ ] Test async restore endpoint
- [ ] Test backward compatibility (sync endpoint)
- [ ] Test progress tracking
- [ ] Test error handling
- [ ] Test concurrent restores

## Phase 3: Documentation

### Task 9: Update API documentation
**File**: `kubernetes/wp-k8s-service/README.md` (if exists)
**Estimated Time**: 15 minutes

- [ ] Document new `/api/v2/restore` endpoint
- [ ] Add request/response examples
- [ ] Add usage notes

### Task 10: Update OPERATIONAL_MEMORY.md
**File**: `OPERATIONAL_MEMORY.md`
**Estimated Time**: 15 minutes

- [ ] Document restore async implementation
- [ ] Add to recent changes section
- [ ] Update API endpoints list

## Checklist

**Before Starting:**
- [x] Created openspec change document
- [x] Created tasks breakdown
- [ ] Reviewed existing clone async implementation

**Implementation:**
- [ ] Task 1: Add JobType.restore
- [ ] Task 2: Create AsyncRestoreRequest model
- [ ] Task 3: Create /api/v2/restore endpoint
- [ ] Task 4: Create restore_wordpress task
- [ ] Task 5: Extract perform_restore function
- [ ] Task 6: Update old endpoint with deprecation

**Testing:**
- [ ] Task 7: Create restore test script
- [ ] Task 8: Run integration tests

**Documentation:**
- [ ] Task 9: Update API documentation
- [ ] Task 10: Update OPERATIONAL_MEMORY.md

**Deployment:**
- [ ] Build and deploy new image
- [ ] Test in cluster
- [ ] Monitor logs for errors
- [ ] Verify backward compatibility

## Success Criteria

- ✅ New async endpoint returns job_id in < 1 second
- ✅ Progress tracking works (10%, 30%, 50%, 100%)
- ✅ Old sync endpoint still works
- ✅ Can handle multiple concurrent restores
- ✅ Error handling matches clone endpoint
