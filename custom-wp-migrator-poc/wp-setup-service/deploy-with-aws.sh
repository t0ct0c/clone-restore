#!/bin/bash
set -e

echo "🚀 Deploying wp-setup-service with AWS integration..."

# Extract SSH key from Terraform
echo "📦 Extracting SSH key from Terraform..."
cd ../infra/wp-targets
terraform output -raw ssh_private_key_pem > /tmp/wp-targets-key.pem
chmod 600 /tmp/wp-targets-key.pem
cd ../../wp-setup-service

# Build Docker image
echo "🔨 Building Docker image..."
docker build -t wp-setup-service .

# Stop and remove existing container
echo "🛑 Stopping existing container..."
docker stop wp-setup-service 2>/dev/null || true
docker rm wp-setup-service 2>/dev/null || true

# Run container with AWS credentials and SSH key
echo "🚀 Starting container with AWS integration..."
docker run -d \
  -p 5000:8000 \
  --name wp-setup-service \
  -e AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID}" \
  -e AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY}" \
  -e AWS_SESSION_TOKEN="${AWS_SESSION_TOKEN:-}" \
  -e AWS_DEFAULT_REGION="us-east-1" \
  -v /tmp/wp-targets-key.pem:/app/ssh/wp-targets-key.pem:ro \
  wp-setup-service:latest

echo "✅ Service deployed successfully!"
echo "📍 Health check: http://localhost:5000/health"
echo "📍 API docs: http://localhost:5000/docs"
echo ""
echo "🔍 Checking service health..."
sleep 3
curl -s http://localhost:5000/health | jq || echo "Service starting..."
