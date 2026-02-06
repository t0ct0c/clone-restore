#!/bin/bash
# Deploy WordPress target image to ECR
set -e

echo "================================"
echo "WordPress Target Image Deployment"
echo "================================"

# Configuration
REGION="us-east-1"
AWS_ACCOUNT_ID="044514005641"
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
IMAGE_NAME="wordpress-target-sqlite"

echo ""
echo "Step 1: Rebuilding plugin.zip..."
cd wordpress-target-image
rm -f plugin.zip
zip -r plugin.zip plugin/ -x "*.git*" "*.DS_Store" "*.backup" "*.broken" "*.pre-fix-backup" "*.before-redirect-fix"
cp plugin.zip ../plugin.zip
echo "✅ Plugin rebuilt"

echo ""
echo "Step 2: Building Docker image..."
docker build -t ${IMAGE_NAME}:latest .
echo "✅ Image built"

echo ""
echo "Step 3: Authenticating with ECR..."
aws ecr get-login-password --region ${REGION} | docker login --username AWS --password-stdin ${ECR_REGISTRY}
echo "✅ ECR authentication successful"

echo ""
echo "Step 4: Tagging image..."
docker tag ${IMAGE_NAME}:latest ${ECR_REGISTRY}/${IMAGE_NAME}:latest
echo "✅ Image tagged"

echo ""
echo "Step 5: Pushing to ECR..."
docker push ${ECR_REGISTRY}/${IMAGE_NAME}:latest
echo "✅ Image pushed to ECR"

cd ..

echo ""
echo "================================"
echo "Deployment Complete!"
echo "================================"
echo ""
echo "Image: ${ECR_REGISTRY}/${IMAGE_NAME}:latest"
echo ""
echo "New WordPress clones will automatically use this updated image."
echo "Existing clones will continue using their current image until recreated."
echo ""
