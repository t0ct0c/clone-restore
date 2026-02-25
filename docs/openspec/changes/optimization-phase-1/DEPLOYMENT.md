# Phase 1 Deployment Instructions

**Branch**: feat/optimization  
**Status**: Ready for EKS Testing  

---

## Prerequisites

- AWS CLI configured with ECR push permissions
- kubectl configured for EKS cluster
- Docker installed locally

---

## Step 1: Build and Push Docker Image

```bash
cd kubernetes/wp-k8s-service/wordpress-clone
./build.sh
```

This will:
1. Build `wp-k8s-service-clone:optimized` image
2. Push to ECR
3. Tag as `optimized` (latest for optimization branch)

**Image**: `044514005641.dkr.ecr.us-east-1.amazonaws.com/wp-k8s-service-clone:optimized`

---

## Step 2: Create Secrets for Warm Pool

```bash
# Generate secure passwords
DB_PASSWORD=$(openssl rand -base64 32)
ADMIN_PASSWORD=$(openssl rand -base64 32)

# Create secrets
kubectl create secret generic warm-pool-db-password \
  -n wordpress-staging \
  --from-literal=password="${DB_PASSWORD}"

kubectl create secret generic warm-pool-admin-password \
  -n wordpress-staging \
  --from-literal=password="${ADMIN_PASSWORD}"
```

---

## Step 3: Deploy Warm Pool Template

```bash
kubectl apply -f kubernetes/manifests/base/wp-k8s-service/warm-pool-template.yaml
```

**Note**: Warm pool controller manages replicas (starts at 0, scales to 1-2)

---

## Step 4: Verify Warm Pool Controller

The warm pool controller should already be running (started with wp-k8s-service).

```bash
# Check controller is running
kubectl get pods -n wordpress-staging -l app=wp-k8s-service

# Check warm pool pods (should see 1-2 after ~1 minute)
kubectl get pods -n wordpress-staging -l pool-type=warm

# View controller logs
kubectl logs -n wordpress-staging -l app=wp-k8s-service -c wp-k8s-service | grep -i "warm pool"
```

Expected output:
```
Warm pool controller started (maintaining 1-2 pods)
Created warm pod (pool size: 1)
Created warm pod (pool size: 2)
```

---

## Step 5: Test Clone Endpoint

```bash
# Test clone with warm pool
curl -X POST http://localhost:8090/api/v2/clone \
  -H "Content-Type: application/json" \
  -d '{
    "source_url": "https://betaweb.ai",
    "ttl_minutes": 30
  }'

# Check response time (should be < 5s for warm pool assignment)
# Clone should be ready in 35-65s total
```

---

## Step 6: Monitor Warm Pool

```bash
# Watch warm pool pods
watch kubectl get pods -n wordpress-staging -l pool-type=warm

# Check pod lifecycle
kubectl get pods -n wordpress-staging -l pool-type=assigned
kubectl get pods -n wordpress-staging -l pool-type=assigned,clone-id=<test-clone-id>
```

---

## Verification Checklist

- [ ] Docker image built and pushed to ECR
- [ ] Secrets created in wordpress-staging namespace
- [ ] Warm pool template deployed
- [ ] Warm pool controller running
- [ ] 1-2 warm pods running and ready
- [ ] Clone endpoint uses warm pool (check logs)
- [ ] Clone time < 65s
- [ ] Pod returned to pool after TTL

---

## Troubleshooting

### Warm pods not created

```bash
# Check controller logs
kubectl logs -n wordpress-staging -l app=wp-k8s-service -c wp-k8s-service | grep -i warm

# Check for image pull errors
kubectl describe pod -n wordpress-staging -l pool-type=warm
```

### Clone not using warm pool

```bash
# Check provision logs
kubectl logs -n wordpress-staging -l app=wp-k8s-service -c wp-k8s-service | grep -i "provision"

# Verify USE_WARM_POOL env var
kubectl get deployment -n wordpress-staging wp-k8s-service -o jsonpath='{.spec.template.spec.containers[0].env}' | jq
```

### MySQL sidecar not ready

```bash
# Check MySQL container logs
kubectl logs -n wordpress-staging <warm-pod-name> -c mysql

# Test MySQL connectivity from WordPress container
kubectl exec -n wordpress-staging <warm-pod-name> -c wordpress -- \
  mysqladmin ping -h127.0.0.1 -uwordpress -p<password>
```

---

## Rollback

If issues occur:

```bash
# Disable warm pool
kubectl set env deployment/wp-k8s-service -n wordpress-staging USE_WARM_POOL=false

# Delete warm pool deployment
kubectl delete -f kubernetes/manifests/base/wp-k8s-service/warm-pool-template.yaml

# Revert to previous image
kubectl set image deployment/wp-k8s-service wp-k8s-service=<previous-image> -n wordpress-staging
```

---

## Expected Performance

| Metric | Before | After (Target) |
|--------|--------|----------------|
| Clone time | 180-240s | 35-65s |
| Pod startup | 30-60s | 0s (already running) |
| Plugin activation | 10-20s | 0s (pre-installed) |
| DB creation | 5-10s (RDS) | 2-5s (localhost) |

---

## Cost Impact

| Component | Before | After | Change |
|-----------|--------|-------|--------|
| RDS | $50-100/mo | $0 | -$50-100/mo |
| Warm pods (2) | $0 | $21/mo | +$21/mo |
| **Total** | **$124-224/mo** | **$95-166/mo** | **-$29-58/mo** |

---

## Next Steps After Testing

1. **If successful**:
   - Update IMPLEMENTATION_PROGRESS.md
   - Proceed to Phase 2 (parallel execution)
   - Consider Phase 3 (Go K8s sidecar)

2. **If issues**:
   - Document in troubleshooting section
   - Fix and retest
   - Consider fallback to cold provision only
