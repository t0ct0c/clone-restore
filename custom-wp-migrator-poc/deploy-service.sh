#!/bin/bash
# Build and deploy wp-setup-service

set -e

IMAGE_NAME="wp-setup-service"
REGISTRY="${DOCKER_REGISTRY:-ghcr.io/t0ct0c}"
TAG="${TAG:-latest}"
FULL_IMAGE="${REGISTRY}/${IMAGE_NAME}:${TAG}"

echo "================================"
echo "WP Setup Service Deployment"
echo "================================"

cd "$(dirname "$0")/wp-setup-service"

# Build Docker image
echo ""
echo "[1/3] Building Docker image..."
docker build -t "${FULL_IMAGE}" .

echo ""
echo "Image built: ${FULL_IMAGE}"

# Push to registry
echo ""
echo "[2/3] Pushing to registry..."
read -p "Push to ${REGISTRY}? (yes/no): " push_confirm

if [ "$push_confirm" = "yes" ]; then
  docker push "${FULL_IMAGE}"
  echo "Image pushed successfully"
else
  echo "Skipping push"
fi

# Deployment options
echo ""
echo "[3/3] Deployment options:"
echo ""
echo "Option A - Run locally with docker-compose:"
echo "  cd wp-setup-service && docker-compose up -d"
echo ""
echo "Option B - Deploy to AWS ECS/Fargate (requires additional Terraform config)"
echo ""
echo "Option C - Deploy to existing EC2:"
echo "  ssh -i wp-targets-key.pem ec2-user@<instance-ip>"
echo "  docker run -d -p 8000:8000 ${FULL_IMAGE}"
echo ""
echo "Service will be available at:"
echo "  Local: http://localhost:5000"
echo "  EC2: http://<instance-ip>:8000"
