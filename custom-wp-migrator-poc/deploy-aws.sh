#!/bin/bash
# Deploy AWS infrastructure for WordPress target provisioning

set -e

echo "================================"
echo "AWS Infrastructure Deployment"
echo "================================"

cd "$(dirname "$0")/infra/wp-targets"

# Initialize Terraform
echo ""
echo "[1/4] Initializing Terraform..."
terraform init

# Validate configuration
echo ""
echo "[2/4] Validating Terraform configuration..."
terraform validate

# Plan deployment
echo ""
echo "[3/4] Planning infrastructure changes..."
terraform plan -out=tfplan

# Apply
echo ""
echo "[4/4] Deploying infrastructure..."
echo "This will create AWS resources (EC2, VPC, ALB, etc.)"
read -p "Continue? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
  echo "Deployment cancelled"
  exit 0
fi

terraform apply tfplan

# Output results
echo ""
echo "================================"
echo "Deployment Complete!"
echo "================================"
echo ""
terraform output

# Save SSH key
echo ""
echo "Saving SSH private key..."
terraform output -raw ssh_private_key_pem > wp-targets-key.pem
chmod 600 wp-targets-key.pem
echo "SSH key saved to: $(pwd)/wp-targets-key.pem"

echo ""
echo "Next steps:"
echo "1. Build and push wp-setup-service Docker image"
echo "2. Deploy setup service to ECS/EC2"
echo "3. Configure DNS for ALB (optional)"
