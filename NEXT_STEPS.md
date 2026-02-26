# Next Steps - Resume Point for feat/kubernetes-restore

**Date**: 2026-02-26 05:05 UTC
**Branch**: feat/kubernetes-restore
**Status**: ACTIVE BUG - CrashLoopBackOff + wp-admin login redirect

## The Problem

Two conflicting requirements:
1. `$_SERVER['HTTPS'] = 'on'` in wp-config.php is NEEDED for wp-admin login (pods behind TLS LB)
2. Kubernetes `httpGet` probes on port 80 get 301-redirected to HTTPS:443 by WordPress, which doesn't exist

Apache logs confirm: `"GET / HTTP/1.1" 301 263 "-" "kube-probe/1.35+"`

## The Fix

Change health probes from `httpGet` to `tcpSocket` on port 80. This checks "is Apache listening?" without WordPress redirect logic.

## Step-by-Step Execution

### Step 1: Revert warm_pool_controller.py templates
Remove `$_SERVER['HTTPS'] = 'on';` from BOTH wp-config templates in warm_pool_controller.py.
Not needed there - the Docker entrypoint (image `final-fix-20260226-104040`) already handles this.

```python
# Line ~308 and ~682: REMOVE this line from both templates
$_SERVER['HTTPS'] = 'on';
```

### Step 2: Change probes in warm_pool_controller.py (~lines 415-430)
```python
# FROM:
liveness_probe=client.V1Probe(
    http_get=client.V1HTTPGetAction(path="/", port=80),
    ...
)
# TO:
liveness_probe=client.V1Probe(
    tcp_socket=client.V1TCPSocketAction(port=80),
    ...
)
```
Same for readiness_probe.

### Step 3: Change probes in k8s_provisioner.py (~lines 515-532)
Same httpGet → tcpSocket change for cold provision path.

### Step 4: Build and deploy
```bash
# Build (from kubernetes/wp-k8s-service/)
docker build -t wp-k8s-service:probe-fix-$(date +%Y%m%d-%H%M%S) .

# Tag and push
docker tag wp-k8s-service:<tag> 044514005641.dkr.ecr.us-east-1.amazonaws.com/wp-k8s-service:<tag>
docker push 044514005641.dkr.ecr.us-east-1.amazonaws.com/wp-k8s-service:<tag>

# Deploy
kubectl set image deployment/wp-k8s-service wp-k8s-service=044514005641.dkr.ecr.us-east-1.amazonaws.com/wp-k8s-service:<tag> -n wordpress-staging
```

### Step 5: Reset warm pool
```bash
kubectl delete pod -n wordpress-staging -l pool-type=warm
# Wait for new pods to spawn
kubectl get pods -n wordpress-staging -l pool-type=warm -w
# Verify 2/2 Ready, 0 restarts
```

### Step 6: Test clone
```bash
curl -s -X POST https://clones.betaweb.ai/api/v2/clone \
  -H "Content-Type: application/json" \
  -d '{"source_url": "https://bonnel.ai", "source_username": "admin", "source_password": "ygu8GZ9jSjCHIF6S", "customer_id": "probe-fix-test-'$(date +%s)'", "ttl_minutes": 30}'

# Check job status, then try wp-admin login
```

## Do NOT
- Remove HTTPS from docker-entrypoint.sh (it's correct there)
- Use httpGet probes for WordPress containers
- Commit before verifying on cluster
- Rebuild the clone Docker image

## Current Images
- Clone (KEEP): `wp-k8s-service-clone:final-fix-20260226-104040`
- Service (NEEDS REBUILD): `wp-k8s-service:fix-https-flag-20260226-123505`
