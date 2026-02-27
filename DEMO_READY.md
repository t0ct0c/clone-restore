# Demo Ready - 10 Clone Bulk Test

## Current Status: ✅ READY

### Working Clones
- **10 clones** currently running
- All accessible at: `https://load-test-XXX.clones.betaweb.ai`
- Credentials saved in: `scripts/bulk-clone-credentials-20260227-122201.json`

### System State
- ✅ wp-k8s-service: Running (1/1)
- ✅ Warm pool: 4 baseline pods (will burst to 10-15 during demo)
- ✅ Script fixed: Polling endpoint corrected

## Quick Commands

### Run 10-Clone Demo
```bash
cd /home/chaz/Desktop/clone-restore/scripts
python3 bulk-create-clones.py
```

**Expected behavior:**
1. Submits 10 clone jobs (5 from betaweb.ai, 5 from bonnel.ai)
2. Warm pool scales from 4 to ~10-15 pods
3. Clones complete in ~4-5 minutes
4. Generates JSON file: `bulk-clone-credentials-{timestamp}.json`

### Cleanup Test Clones
```bash
# Clean up all load-test clones
./scripts/cleanup-test-clones.sh load-test

# Clean up everything
./scripts/cleanup-test-clones.sh
```

**Cleans:**
- Services
- Ingresses  
- Secrets
- Assigned pods (warm pods return to pool)

## What Was Fixed

### 1. Bulk Script Polling Bug
- **Problem:** Script used wrong endpoint `/api/v2/jobs/{job_id}`
- **Fix:** Changed to correct endpoint `/api/v2/job-status/{job_id}`
- **File:** `scripts/bulk-create-clones.py:82`

### 2. Delete Script Doesn't Work
- **Problem:** Tries to delete deployments (clones use warm pods, not deployments)
- **Solution:** Created new script `cleanup-test-clones.sh` that deletes actual resources
- **Old script:** `delete-clones.py` (don't use)
- **New script:** `cleanup-test-clones.sh` (use this)

### 3. Manual Credential Extraction
- If polling breaks again, extract credentials manually:
```python
cd scripts && python3 << 'PYTHON_EOF'
import json, subprocess, base64
from datetime import datetime

clones = []
for i in range(1, 11):
    clone_id = f"load-test-{i:03d}"
    result = subprocess.run(
        ["kubectl", "get", "secret", f"{clone_id}-credentials", 
         "-n", "wordpress-staging", "-o", "jsonpath={.data}"],
        capture_output=True, text=True
    )
    if result.returncode == 0 and result.stdout:
        data = json.loads(result.stdout)
        clones.append({
            "clone_id": clone_id,
            "public_url": f"https://{clone_id}.clones.betaweb.ai",
            "wordpress_username": base64.b64decode(data.get("wordpress-username", "YWRtaW4=")).decode(),
            "wordpress_password": base64.b64decode(data.get("wordpress-password", "")).decode(),
            "api_key": base64.b64decode(data.get("api-key", "")).decode() if data.get("api-key") else ""
        })

filename = f"bulk-clone-credentials-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
with open(filename, "w") as f:
    json.dump({"test_timestamp": datetime.now().isoformat(), "ttl_minutes": 30, "total_clones": len(clones), "clones": clones}, f, indent=2)
print(f"Created {filename}")
PYTHON_EOF
```

## Architecture Summary

**Clone Flow:**
1. API receives clone request → Creates Dramatiq job
2. Warm pool controller assigns ready warm pod to clone
3. Pod changes from `pool-type=warm` to `pool-type=assigned`
4. Service + Ingress created for the clone
5. Clone credentials saved to Kubernetes secret
6. After TTL expires, pod returns to warm pool

**No deployments are created** - clones reuse warm pods directly!

## Files

- **Credentials:** `scripts/bulk-clone-credentials-20260227-122201.json` (current 10 clones)
- **Cleanup script:** `scripts/cleanup-test-clones.sh` (NEW - use this)
- **Old delete script:** `scripts/delete-clones.py` (BROKEN - don't use)
- **Bulk test script:** `scripts/bulk-create-clones.py` (FIXED)
