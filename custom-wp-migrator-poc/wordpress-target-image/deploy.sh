#!/bin/bash
set -e

echo "🚀 Deploying wordpress-target-sqlite to AWS ECR"

# Configuration
REGION="us-east-1"
AWS_ACCOUNT_ID="044514005641"
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
IMAGE_NAME="wordpress-target-sqlite"

# Get version from git or use timestamp
VERSION=$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d-%H%M%S)

echo "📦 Building image version: ${VERSION}"

# Step 1: Build Docker image locally
echo "🔨 Building Docker image..."
cd "$(dirname "$0")"
docker build -t ${IMAGE_NAME}:${VERSION} -t ${IMAGE_NAME}:latest .

# Step 2: Tag for ECR
echo "🏷️  Tagging for ECR..."
docker tag ${IMAGE_NAME}:${VERSION} ${ECR_REGISTRY}/${IMAGE_NAME}:${VERSION}
docker tag ${IMAGE_NAME}:latest ${ECR_REGISTRY}/${IMAGE_NAME}:latest

# Step 3: Login to ECR
echo "🔐 Logging into ECR..."
aws ecr get-login-password --region ${REGION} | docker login --username AWS --password-stdin ${ECR_REGISTRY}

# Step 4: Push to ECR
echo "⬆️  Pushing to ECR..."
docker push ${ECR_REGISTRY}/${IMAGE_NAME}:${VERSION}
docker push ${ECR_REGISTRY}/${IMAGE_NAME}:latest

echo ""
echo "================================"
echo "✅ Deployment Complete!"
echo "================================"
echo ""
echo "Version: ${VERSION}"
echo "ECR Image: ${ECR_REGISTRY}/${IMAGE_NAME}:${VERSION}"
echo ""
echo "📝 Important Notes:"
echo "  • NEW clones will automatically use this updated image"
echo "  • EXISTING clones continue running the old image until they expire"
echo "  • The EC2 provisioner pulls 'wordpress-target-sqlite:latest' when creating clones"
echo ""
echo "To test the changes:"
echo "  1. Create a new clone: POST http://13.222.20.138:8000/clone"
echo "  2. Test Application Passwords on the new clone"
echo ""
