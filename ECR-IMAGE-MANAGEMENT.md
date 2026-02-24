# ECR Image Management

## Current Production Images (2026-02-22)

### wp-k8s-service Repository
- **Production Tag**: `20260222-production`
- **Latest Tag**: `latest` (points to same image)
- **Deployment**: Both containers (wp-k8s-service + dramatiq-worker) use `20260222-production`

### wp-k8s-service-clone Repository (Warm Pool)
- **Production Tag**: `optimized-v9`
- **Warm Pool Controller**: Configured to use `optimized-v9`

## Image Naming Convention

Going forward, use this naming pattern for new images:

```
YYYYMMDD-purpose[-version]
```

Examples:
- `20260222-production` - Daily production image
- `20260222-feature-test` - Feature testing image
- `20260223-hotfix` - Hotfix image

## Cleanup Policy

### Keep:
- Current production tag (`YYYYMMDD-production`)
- `latest` tag
- Today's images (`YYYYMMDD-*`)
- Previous day's named releases (`YYYYMMDD-final`, `YYYYMMDD-fix*`)

### Delete:
- Old async images (`async-YYYYMMDD*`)
- Old fix images older than 2 days
- Debug/test images older than 2 days
- Stream fix images (consolidated into production)

## Scripts

### manage-ecr-images.sh
Tags current production image with date-based name and updates deployment.

```bash
./scripts/manage-ecr-images.sh
```

### cleanup-ecr-images.sh
Removes old images according to cleanup policy.

```bash
./scripts/cleanup-ecr-images.sh
```

## Current Image Count

- **wp-k8s-service**: ~52 images (after cleanup)
- **wp-k8s-service-clone**: 2 images (optimized-v8, optimized-v9)

## Verification

Check current deployment images:
```bash
kubectl get deployment wp-k8s-service -n wordpress-staging -o jsonpath='{.spec.template.spec.containers[*].image}'
```

Check available ECR images:
```bash
aws ecr list-images --repository-name wp-k8s-service --region us-east-1 --query 'imageIds[*].imageTag' --output text
```

## Next Cleanup

Run cleanup script weekly to remove images older than 7 days (except production tags).
