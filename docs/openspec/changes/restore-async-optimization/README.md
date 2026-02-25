# Restore Endpoint Async Optimization

**Status**: Planning  
**Branch**: feat/kubernetes-restore  
**Created**: 2026-02-25  
**Priority**: High  

## Problem Statement

The current `/restore` endpoint is **synchronous** and blocks the request until the entire restore operation completes (60-120 seconds). This creates several issues:

1. **Poor UX**: Client must wait for full restore before getting a response
2. **Timeout risks**: Long operations may hit HTTP timeouts
3. **No progress tracking**: User has no visibility into restore progress
4. **Inconsistent with /clone**: The `/api/v2/clone` endpoint already uses async pattern successfully

## Current State

### Clone Endpoint (Async - ✅ Working Well)
```
POST /api/v2/clone
  ↓
Creates job in job_store
  ↓
Returns job_id immediately (< 1 second)
  ↓
Dramatiq worker processes in background
  ↓
Client polls GET /api/v2/job-status/{job_id}
  ↓
Gets progress updates (10%, 30%, 50%, 70%, 100%)
```

**Flow:**
1. API receives request → creates Job record → returns job_id
2. Dramatiq worker picks up job → runs `clone_wordpress()` task
3. Task provisions target → sets up source → performs clone → updates progress
4. Client polls for status until complete

### Restore Endpoint (Sync - ❌ Needs Improvement)
```
POST /restore
  ↓
Blocks while:
  - Setting up source (browser automation)
  - Setting up target (browser automation)  
  - Exporting from source
  - Importing to target
  ↓
Returns result after 60-120 seconds
```

**Issues:**
- No progress visibility
- Single long-running request
- Client must wait entire time
- Risk of HTTP timeouts

## Proposed Solution

Make `/restore` endpoint async, matching the `/api/v2/clone` pattern.

### New Flow

```
POST /api/v2/restore
  ↓
Creates job in job_store with type=restore
  ↓
Returns job_id immediately (< 1 second)
  ↓
Dramatiq worker processes in background
  ↓
Client polls GET /api/v2/job-status/{job_id}
  ↓
Gets progress updates (10%, 30%, 50%, 70%, 100%)
```

### Implementation Plan

**1. Create new async restore endpoint:**
```python
@app.post("/api/v2/restore", response_model=JobStatusResponse, tags=["Async V2"])
async def restore_async(request: AsyncRestoreRequest):
    """Restore WordPress asynchronously (non-blocking)."""
    from .tasks import restore_wordpress
    from .job_store import get_job_store, JobType
    
    job_store = get_job_store()
    job = await job_store.create_job(
        job_type=JobType.restore,
        request_payload=request.dict(),
    )
    restore_wordpress.send(job.job_id)
    logger.info(f"Enqueued async restore job {job.job_id}")
    return JobStatusResponse(**job.to_dict())
```

**2. Create Dramatiq task for restore:**
```python
@dramatiq.actor(queue_name="default", max_retries=0, time_limit=600_000)
async def restore_wordpress(job_id: str) -> Dict:
    """Restore WordPress site asynchronously."""
    # Similar structure to clone_wordpress task
    # Steps:
    # 1. Get job from job_store
    # 2. Setup source (browser or API detection)
    # 3. Setup target (browser automation)
    # 4. Perform restore (export + import)
    # 5. Update job status with progress
    # 6. Return result
```

**3. Keep sync endpoint for backward compatibility:**
```python
@app.post("/restore", response_model=RestoreResponse)
async def restore_endpoint(request: RestoreRequest):
    """Legacy synchronous restore endpoint (deprecated)."""
    # Keep existing implementation for backward compatibility
    # Add deprecation warning in response
```

**4. Add JobType.restore:**
```python
class JobType(str, Enum):
    clone = "clone"
    restore = "restore"  # NEW
```

**5. Progress tracking milestones:**
- 10%: Job received and validated
- 30%: Source setup complete
- 50%: Target setup complete
- 70%: Export from source complete
- 90%: Import to target complete
- 100%: Restore complete

## Benefits

1. **Better UX**: Immediate response with job_id
2. **Progress visibility**: Client can show progress bar
3. **No timeouts**: Job runs in background
4. **Consistent API**: Matches clone endpoint pattern
5. **Scalability**: Can handle multiple concurrent restores
6. **Backward compatible**: Old endpoint still works

## Testing Plan

1. **Test async restore endpoint:**
   - Create job successfully
   - Poll for status updates
   - Verify progress tracking (10%, 30%, 50%, 70%, 100%)
   - Verify final result matches sync endpoint

2. **Test backward compatibility:**
   - Ensure old `/restore` endpoint still works
   - Verify no breaking changes

3. **Test error handling:**
   - Source setup failure
   - Target setup failure
   - Export failure
   - Import failure

4. **Test concurrent restores:**
   - Start multiple restore jobs
   - Verify all complete successfully

## Success Criteria

- ✅ New `/api/v2/restore` endpoint returns job_id in < 1 second
- ✅ Job status polling works correctly
- ✅ Progress updates at each milestone (10%, 30%, 50%, 70%, 100%)
- ✅ Old `/restore` endpoint still works for backward compatibility
- ✅ Error handling matches clone endpoint behavior
- ✅ Can handle 5+ concurrent restore jobs

## Files to Modify

1. **kubernetes/wp-k8s-service/app/main.py**
   - Add `/api/v2/restore` endpoint
   - Add deprecation notice to old `/restore` endpoint

2. **kubernetes/wp-k8s-service/app/tasks.py**
   - Add `restore_wordpress()` Dramatiq task
   - Implement progress tracking

3. **kubernetes/wp-k8s-service/app/job_store.py**
   - Add `JobType.restore` enum value

4. **kubernetes/wp-k8s-service/app/models.py** (if exists)
   - Add `AsyncRestoreRequest` model

5. **scripts/restore-single.py** (NEW)
   - Create test script for async restore
   - Similar to `scripts/clone-single.py`

## Dependencies

- Existing job_store implementation (already works for clone)
- Existing Dramatiq setup (already configured)
- Existing restore logic in main.py (reuse with progress tracking)

## Timeline

**Phase 1: Implementation (Est. 2-3 hours)**
- Create async endpoint
- Create Dramatiq task
- Add progress tracking

**Phase 2: Testing (Est. 1-2 hours)**
- Write test script
- Test various scenarios
- Verify backward compatibility

**Phase 3: Documentation (Est. 30 min)**
- Update API documentation
- Update OPERATIONAL_MEMORY.md
- Add usage examples

## References

- Existing clone implementation: `kubernetes/wp-k8s-service/app/main.py:1121`
- Existing clone task: `kubernetes/wp-k8s-service/app/tasks.py:20`
- Job store: `kubernetes/wp-k8s-service/app/job_store.py`
