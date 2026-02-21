#!/bin/bash
# Build and deploy optimization Phase 1 to EKS

set -e

AWS_ACCOUNT_ID="044514005641"
AWS_REGION="us-east-1"
IMAGE_NAME="wp-k8s-service-clone"
IMAGE_TAG="optimized-$(date +%Y%m%d-%H%M%S)"
ECR_REPO="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${IMAGE_NAME}"

echo "=== Building WordPress Clone Image ==="
cd kubernetes/wp-k8s-service/wordpress-clone

# Build Docker image
docker build -t ${ECR_REPO}:${IMAGE_TAG} .
docker tag ${ECR_REPO}:${IMAGE_TAG} ${ECR_REPO}:optimized

echo "=== Pushing to ECR ==="
aws ecr get-login-password --region ${AWS_REGION} | \
  docker login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com

docker push ${ECR_REPO}:${IMAGE_TAG}
docker push ${ECR_REPO}:optimized

echo "=== Image pushed: ${ECR_REPO}:optimized ==="

echo ""
echo "=== Next Steps ==="
echo "1. Update warm_pool_controller.py WORDPRESS_IMAGE env var if needed"
echo "2. Deploy to EKS:"
echo "   kubectl apply -f kubernetes/manifests/base/wp-k8s-service/warm-pool-template.yaml"
echo "3. Create secrets:"
echo "   kubectl create secret generic warm-pool-db-password -n wordpress-staging --from-literal=password=<generate-password>"
echo "   kubectl create secret generic warm-pool-admin-password -n wordpress-staging --from-literal=password=<generate-password>"
echo "4. Verify warm pool controller starts and maintains 1-2 pods"
echo "5. Test clone endpoint"
echo ""
echo "=== Build Complete ==="
