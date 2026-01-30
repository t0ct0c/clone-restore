#!/bin/bash
set -e

echo "🚀 Deploying wp-setup-service to AWS"

# Configuration
REGION="us-east-1"
AWS_ACCOUNT_ID="044514005641"
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
IMAGE_NAME="wp-setup-service"
MANAGEMENT_SERVER_IP="13.222.20.138"
SSH_KEY="$(dirname "$0")/../wp-targets-key.pem"

# Get version from git or use timestamp
VERSION=$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d-%H%M%S)

echo "📦 Building image version: ${VERSION}"

# Step 1: Build Docker image locally
echo "🔨 Building Docker image..."
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

# Step 5: Deploy to management server
echo "🚀 Deploying to management server ${MANAGEMENT_SERVER_IP}..."

ssh -i ${SSH_KEY} -o StrictHostKeyChecking=no ec2-user@${MANAGEMENT_SERVER_IP} << ENDSSH
set -e

echo "🔐 Logging into ECR on remote server..."
aws ecr get-login-password --region ${REGION} | docker login --username AWS --password-stdin ${ECR_REGISTRY}

echo "⬇️  Pulling latest image from ECR..."
docker pull ${ECR_REGISTRY}/${IMAGE_NAME}:latest

echo "🏷️  Tagging as local latest..."
docker tag ${ECR_REGISTRY}/${IMAGE_NAME}:latest ${IMAGE_NAME}:latest

echo "🛑 Stopping existing container..."
docker stop wp-setup-service 2>/dev/null || true
docker rm wp-setup-service 2>/dev/null || true

echo "🚀 Starting new container..."
docker run -d \
  --name wp-setup-service \
  --restart unless-stopped \
  --log-driver loki \
  --log-opt loki-url="http://localhost:3100/loki/api/v1/push" \
  --log-opt loki-batch-size=100 \
  --log-opt loki-retries=2 \
  --log-opt loki-external-labels="job=wp-setup-service,environment=production" \
  --network host \
  -e AWS_REGION=${REGION} \
  -e AWS_DEFAULT_REGION=${REGION} \
  -e OTEL_EXPORTER_OTLP_ENDPOINT=http://10.0.4.2:4318/v1/traces \
  -e 'MYSQL_ROOT_PASSWORD=r]s@3{wClRz5X&sJ7+?_6@dIXz!}s&D:' \
  -v /home/ec2-user/.aws:/root/.aws:ro \
  -v /home/ec2-user/wp-targets-key.pem:/app/ssh/wp-targets-key.pem:ro \
  ${IMAGE_NAME}:latest

echo "✅ Container started"
docker ps | grep wp-setup-service
ENDSSH

# Step 6: Health check
echo ""
echo "🏥 Checking service health..."
sleep 5
if curl -s http://${MANAGEMENT_SERVER_IP}:8000/health | grep -q "healthy"; then
    echo "✅ Service is healthy!"
else
    echo "⚠️  Service may still be starting..."
    echo "Check logs: ssh -i ${SSH_KEY} ec2-user@${MANAGEMENT_SERVER_IP} 'docker logs wp-setup-service'"
fi

echo ""
echo "================================"
echo "✅ Deployment Complete!"
echo "================================"
echo ""
echo "Version: ${VERSION}"
echo "ECR Image: ${ECR_REGISTRY}/${IMAGE_NAME}:${VERSION}"
echo "Service URL: http://${MANAGEMENT_SERVER_IP}:8000"
echo "API Docs: http://${MANAGEMENT_SERVER_IP}:8000/docs"
echo ""
echo "To view logs:"
echo "  ssh -i ${SSH_KEY} ec2-user@${MANAGEMENT_SERVER_IP} 'docker logs -f wp-setup-service'"
echo ""
