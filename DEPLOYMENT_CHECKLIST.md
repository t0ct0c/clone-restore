# Deployment Checklist - WordPress Clone System

## CRITICAL: Read This Before ANY Changes

**RULE 1:** Never delete or modify infrastructure without explicit approval  
**RULE 2:** Always verify what's currently deployed before making changes  
**RULE 3:** Follow this checklist for EVERY deployment  
**RULE 4:** Document what you changed and why  

---

## Current Production State (Last Updated: 2026-02-26)

### Docker Images
- **Clone Image:** `044514005641.dkr.ecr.us-east-1.amazonaws.com/wp-k8s-service-clone:final-fix-20260226-104040`
  - Contains: WordPress with custom entrypoint that sets HTTPS flag
  - DO NOT REBUILD unless absolutely necessary
  
- **Service Image:** `044514005641.dkr.ecr.us-east-1.amazonaws.com/wp-k8s-service:tcpsocket-fix-20260226-183755`
  - Contains: FastAPI + Dramatiq workers + k8s_provisioner.py + warm_pool_controller.py
  - This gets rebuilt when code changes

### Infrastructure Components
1. **EKS Cluster:** wp-clone-restore (us-east-1)
2. **Namespace:** wordpress-staging
3. **Redis:** redis-master-0 with 8Gi persistent storage (gp2)
   - Password: dramatiq-broker-password
   - Replicas: 0 (master only)
4. **EBS CSI Driver:** Installed (IAM role: AmazonEKS_EBS_CSI_DriverRole)
5. **Warm Pool:** 2 pods (wordpress-warm-*)
6. **Traefik:** TLS load balancer (terminates SSL)

### Critical Settings
- **Kubernetes Probes:** tcpSocket on port 80 (NOT httpGet)
- **Redis URL:** `redis://:dramatiq-broker-password@redis-master.wordpress-staging.svc.cluster.local:6379/0`
- **HTTPS Flag:** Set in clone image entrypoint (not in templates)
- **Storage Class:** gp2 (for Redis persistence)

---

## Deployment Checklist

### Before ANY Code Changes

- [ ] Check what's currently deployed
  ```bash
  kubectl get deployment wp-k8s-service -n wordpress-staging -o yaml | grep image:
  ```

- [ ] Read OPERATIONAL_MEMORY.md for context

- [ ] Ask user for approval if making infrastructure changes

### When Code Changes Are Made

#### Files That Require Image Rebuild:
- `kubernetes/wp-k8s-service/app/main.py`
- `kubernetes/wp-k8s-service/app/k8s_provisioner.py`
- `kubernetes/wp-k8s-service/app/warm_pool_controller.py`
- `kubernetes/wp-k8s-service/app/tasks.py`
- `kubernetes/wp-k8s-service/app/browser_setup.py`
- Any file in `kubernetes/wp-k8s-service/app/`

#### Rebuild Steps (Follow EXACTLY):

1. **Verify changes are correct**
   - [ ] Check probe configuration (MUST be tcpSocket, not httpGet)
   - [ ] Check Redis URL has password
   - [ ] Verify HTTPS flag logic

2. **Build new image**
   ```bash
   cd kubernetes/wp-k8s-service
   docker build -t wp-k8s-service:fix-description-YYYYMMDD-HHMMSS .
   ```

3. **Tag for ECR**
   ```bash
   docker tag wp-k8s-service:fix-description-YYYYMMDD-HHMMSS \
     044514005641.dkr.ecr.us-east-1.amazonaws.com/wp-k8s-service:fix-description-YYYYMMDD-HHMMSS
   ```

4. **Push to ECR**
   ```bash
   docker push 044514005641.dkr.ecr.us-east-1.amazonaws.com/wp-k8s-service:fix-description-YYYYMMDD-HHMMSS
   ```

5. **Update deployment (BOTH containers)**
   ```bash
   kubectl set image deployment/wp-k8s-service -n wordpress-staging \
     wp-k8s-service=044514005641.dkr.ecr.us-east-1.amazonaws.com/wp-k8s-service:fix-description-YYYYMMDD-HHMMSS \
     dramatiq-worker=044514005641.dkr.ecr.us-east-1.amazonaws.com/wp-k8s-service:fix-description-YYYYMMDD-HHMMSS
   ```

6. **Wait for rollout**
   ```bash
   kubectl rollout status deployment/wp-k8s-service -n wordpress-staging
   ```

7. **Verify deployment**
   - [ ] Check API health: `curl https://clones.betaweb.ai/health`
   - [ ] Check warm pool: `kubectl get pods -n wordpress-staging -l pool-type=warm`
   - [ ] Create test clone to verify

8. **Clean up old resources if needed**
   - [ ] Delete broken clone deployments
   - [ ] Delete orphaned services/ingresses/secrets
   - [ ] Clear Redis queue if necessary (consult user first)

### When Environment Variables Change

- [ ] Verify the change is necessary
- [ ] Document what's being changed and why
- [ ] Update using kubectl set env:
  ```bash
  kubectl set env deployment/wp-k8s-service -n wordpress-staging KEY=value
  ```

### When Redis Changes

**DO NOT change Redis without approval**

If approved:
- [ ] Document current Redis state
- [ ] Backup important queue data if needed
- [ ] Make changes
- [ ] Update wp-k8s-service REDIS_URL if needed
- [ ] Verify connection works

---

## Verification After Deployment

### Required Checks (ALL must pass):

1. **API Health**
   ```bash
   curl https://clones.betaweb.ai/health
   # Should return: {"status":"healthy","version":"2.0.0","platform":"kubernetes"}
   ```

2. **Warm Pool Status**
   ```bash
   kubectl get pods -n wordpress-staging -l pool-type=warm
   # Should show: 2/2 Running, 0 restarts
   ```

3. **wp-k8s-service Pods**
   ```bash
   kubectl get pods -n wordpress-staging -l app=wp-k8s-service
   # Should show: 2/2 Running
   ```

4. **Redis Status**
   ```bash
   kubectl get pods -n wordpress-staging -l app.kubernetes.io/name=redis
   # Should show: redis-master-0 1/1 Running
   ```

5. **Test Clone Creation**
   ```bash
   curl -X POST https://clones.betaweb.ai/api/v2/clone \
     -H "Content-Type: application/json" \
     -d '{
       "source_url": "https://betaweb.ai",
       "source_username": "Charles@toctoc.com.au",
       "source_password": "6(4b`Nde1i_D",
       "customer_id": "verify-deployment-test",
       "ttl_minutes": 10
     }'
   # Should return: job_id and status: pending
   ```

6. **Verify Clone Pod Uses Correct Probes**
   ```bash
   # Wait 2 minutes for clone to provision
   kubectl get deployment verify-deployment-test -n wordpress-staging -o yaml | grep -A 3 "livenessProbe:"
   # MUST show: tcpSocket (NOT httpGet)
   ```

7. **Verify Clone Reaches 2/2 Ready**
   ```bash
   kubectl get pods -n wordpress-staging -l clone-id=verify-deployment-test
   # Should show: 2/2 Running, 0 restarts
   ```

8. **Clean Up Test Clone**
   ```bash
   kubectl delete deployment,service,ingress,secret -n wordpress-staging -l clone-id=verify-deployment-test
   ```

---

## Common Issues and Solutions

### Issue: Clones stuck at 1/2 Ready with restarts
**Cause:** httpGet probes triggering WordPress redirects  
**Solution:** Verify k8s_provisioner.py has tcpSocket probes, rebuild image, redeploy

### Issue: API returns 500 errors
**Cause:** Redis connection issues  
**Check:** 
```bash
kubectl logs -n wordpress-staging -l app=wp-k8s-service -c wp-k8s-service --tail=50
```
**Solution:** Verify REDIS_URL has correct password

### Issue: Warm pool not being used
**Cause:** Warm pool pods missing labels or not ready  
**Check:** 
```bash
kubectl get pods -n wordpress-staging -l pool-type=warm -o wide
```

### Issue: Connection refused during import
**Cause:** WordPress container not ready when import starts  
**Solution:** Increase initialDelaySeconds for readiness probe (currently 30s)

---

## What NOT To Do

### NEVER:
1. Delete Redis without asking (loses all job queue data)
2. Change Redis password without updating wp-k8s-service REDIS_URL
3. Rebuild clone image unless explicitly requested
4. Use httpGet probes for WordPress containers
5. Remove HTTPS flag from clone image entrypoint
6. Deploy without verifying the build worked
7. Make infrastructure changes without approval
8. Assume cache invalidation worked - always verify

### ALWAYS:
1. Follow this checklist for deployments
2. Verify current state before making changes
3. Ask for approval before infrastructure changes
4. Test after deployment
5. Document what you changed and why
6. Update OPERATIONAL_MEMORY.md after major changes

---

## Emergency Rollback

If deployment breaks production:

1. **Get previous image tag**
   ```bash
   kubectl rollout history deployment/wp-k8s-service -n wordpress-staging
   ```

2. **Rollback**
   ```bash
   kubectl rollout undo deployment/wp-k8s-service -n wordpress-staging
   ```

3. **Or specify exact revision**
   ```bash
   kubectl rollout undo deployment/wp-k8s-service -n wordpress-staging --to-revision=N
   ```

4. **Verify rollback worked**
   - Run all verification checks above

---

## Update History

### 2026-02-26 18:40 UTC
- Created this checklist
- Current state: wp-k8s-service:tcpsocket-fix-20260226-183755
- Redis with persistence (gp2, 8Gi)
- EBS CSI driver installed
- tcpSocket probes deployed
