#!/bin/bash
# Build and deploy wp-k8s-service with bug fix

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AWS_ACCOUNT_ID="044514005641"
AWS_REGION="us-east-1"
IMAGE_NAME="wp-k8s-service"
IMAGE_TAG="bugfix-$(date +%Y%m%d-%H%M%S)"
ECR_REPO="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${IMAGE_NAME}"

echo "=== Building wp-k8s-service Image ==="
cd "$SCRIPT_DIR"

# Build Docker image
docker build -t ${ECR_REPO}:${IMAGE_TAG} .
docker tag ${ECR_REPO}:${IMAGE_TAG} ${ECR_REPO}:latest

echo "=== Pushing to ECR ==="
aws ecr get-login-password --region ${AWS_REGION} | \
  docker login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com

docker push ${ECR_REPO}:${IMAGE_TAG}
docker push ${ECR_REPO}:latest

echo "=== Image pushed: ${ECR_REPO}:${IMAGE_TAG} ==="
echo "=== Tagged as: ${ECR_REPO}:latest ==="

echo ""
echo "=== Updating Deployment ==="
kubectl set image deployment/wp-k8s-service \
  wp-k8s-service=${ECR_REPO}:${IMAGE_TAG} \
  dramatiq-worker=${ECR_REPO}:${IMAGE_TAG} \
  -n wordpress-staging

echo "=== Waiting for rollout ==="
kubectl rollout status deployment/wp-k8s-service -n wordpress-staging --timeout=300s

echo ""
echo "=== Deployment Complete ==="
echo "Service updated with image: ${ECR_REPO}:${IMAGE_TAG}"
echo ""
