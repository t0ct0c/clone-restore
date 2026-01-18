#!/bin/bash
# Deploy wp-setup-service to AWS EC2
set -e

echo "================================"
echo "WP Setup Service AWS Deployment"
echo "================================"

# Configuration
REGION="us-east-1"
INSTANCE_NAME="wp-setup-service"
INSTANCE_TYPE="t3.small"
IMAGE_NAME="wp-setup-service"
SERVICE_PORT="8000"

# Check AWS CLI
if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found. Please install it first."
    exit 1
fi

# Check if Terraform state exists
if [ ! -f "infra/wp-targets/terraform.tfstate" ]; then
    echo "❌ Terraform state not found. Please run ./deploy-aws.sh first to create infrastructure."
    exit 1
fi

echo ""
echo "Step 1: Building Docker image..."
cd wp-setup-service
docker build -t ${IMAGE_NAME}:latest .
cd ..

echo ""
echo "Step 2: Saving Docker image as tar..."
docker save ${IMAGE_NAME}:latest -o /tmp/${IMAGE_NAME}.tar

echo ""
echo "Step 3: Getting VPC, subnet and MySQL information from Terraform..."
cd infra/wp-targets
VPC_ID=$(terraform output -json | jq -r '.vpc_id.value // empty')
SUBNET_ID=$(terraform output -json | jq -r '.public_subnet_ids.value[0] // empty')
MYSQL_ROOT_PASSWORD=$(terraform output -raw mysql_root_password)
SSH_KEY_NAME="wp-targets-key"

# If VPC not in outputs, query it
if [ -z "$VPC_ID" ]; then
    VPC_ID=$(aws ec2 describe-vpcs --region $REGION --filters "Name=tag:Name,Values=wp-targets-vpc" --query 'Vpcs[0].VpcId' --output text)
fi

if [ -z "$SUBNET_ID" ]; then
    SUBNET_ID=$(aws ec2 describe-subnets --region $REGION --filters "Name=tag:Name,Values=wp-targets-public-0" --query 'Subnets[0].SubnetId' --output text)
fi

echo "VPC ID: $VPC_ID"
echo "Subnet ID: $SUBNET_ID"

cd ../..

echo ""
echo "Step 4: Creating security group for setup service..."
SG_NAME="wp-setup-service-sg"
SG_ID=$(aws ec2 describe-security-groups --region $REGION --filters "Name=group-name,Values=$SG_NAME" --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || echo "")

if [ "$SG_ID" = "None" ] || [ -z "$SG_ID" ]; then
    echo "Creating new security group..."
    SG_ID=$(aws ec2 create-security-group \
        --region $REGION \
        --group-name $SG_NAME \
        --description "Security group for WP Setup Service" \
        --vpc-id $VPC_ID \
        --output text --query 'GroupId')
    
    # Allow HTTP traffic
    aws ec2 authorize-security-group-ingress \
        --region $REGION \
        --group-id $SG_ID \
        --protocol tcp \
        --port $SERVICE_PORT \
        --cidr 0.0.0.0/0
    
    # Allow SSH
    aws ec2 authorize-security-group-ingress \
        --region $REGION \
        --group-id $SG_ID \
        --protocol tcp \
        --port 22 \
        --cidr 0.0.0.0/0
    
    echo "Security group created: $SG_ID"
else
    echo "Using existing security group: $SG_ID"
fi

echo ""
echo "Step 5: Checking for existing instance..."
EXISTING_INSTANCE=$(aws ec2 describe-instances \
    --region $REGION \
    --filters "Name=tag:Name,Values=$INSTANCE_NAME" "Name=instance-state-name,Values=running" \
    --query 'Reservations[0].Instances[0].InstanceId' \
    --output text 2>/dev/null || echo "")

if [ "$EXISTING_INSTANCE" != "None" ] && [ -n "$EXISTING_INSTANCE" ]; then
    echo "Found existing instance: $EXISTING_INSTANCE"
    read -p "Terminate and recreate? (yes/no): " recreate
    if [ "$recreate" = "yes" ]; then
        echo "Terminating existing instance..."
        aws ec2 terminate-instances --region $REGION --instance-ids $EXISTING_INSTANCE
        aws ec2 wait instance-terminated --region $REGION --instance-ids $EXISTING_INSTANCE
    else
        echo "Using existing instance..."
        INSTANCE_ID=$EXISTING_INSTANCE
    fi
fi

if [ -z "$INSTANCE_ID" ]; then
    echo ""
    echo "Step 6: Creating EC2 instance..."
    
    # Get latest Amazon Linux 2 AMI
    AMI_ID=$(aws ec2 describe-images \
        --region $REGION \
        --owners amazon \
        --filters "Name=name,Values=amzn2-ami-hvm-*-x86_64-gp2" \
        --query 'sort_by(Images, &CreationDate)[-1].ImageId' \
        --output text)
    
    echo "Using AMI: $AMI_ID"
    
    # Create user data script
    cat > /tmp/setup-service-userdata.sh << 'EOF'
#!/bin/bash
set -e

# Install Docker
yum update -y
yum install -y docker
systemctl start docker
systemctl enable docker
usermod -aG docker ec2-user

# Install AWS CLI v2
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip -q awscliv2.zip
./aws/install
rm -rf aws awscliv2.zip

# Create directory for SSH key
mkdir -p /app/ssh
chown ec2-user:ec2-user /app/ssh

echo "Setup complete" > /var/log/userdata-complete.log
EOF
    
    # Launch instance
    INSTANCE_ID=$(aws ec2 run-instances \
        --region $REGION \
        --image-id $AMI_ID \
        --instance-type $INSTANCE_TYPE \
        --key-name $SSH_KEY_NAME \
        --security-group-ids $SG_ID \
        --subnet-id $SUBNET_ID \
        --user-data file:///tmp/setup-service-userdata.sh \
        --iam-instance-profile Name=wp-targets-ec2-instance-profile \
        --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$INSTANCE_NAME}]" \
        --query 'Instances[0].InstanceId' \
        --output text)
    
    echo "Instance created: $INSTANCE_ID"
    echo "Waiting for instance to be running..."
    aws ec2 wait instance-running --region $REGION --instance-ids $INSTANCE_ID
    
    echo "Waiting for status checks..."
    aws ec2 wait instance-status-ok --region $REGION --instance-ids $INSTANCE_ID
fi

echo ""
echo "Step 7: Getting instance details..."
INSTANCE_IP=$(aws ec2 describe-instances \
    --region $REGION \
    --instance-ids $INSTANCE_ID \
    --query 'Reservations[0].Instances[0].PublicIpAddress' \
    --output text)

echo "Instance IP: $INSTANCE_IP"

echo ""
echo "Step 8: Extracting SSH key from Terraform..."
cd infra/wp-targets
terraform output -raw ssh_private_key_pem > /tmp/wp-targets-key.pem
chmod 600 /tmp/wp-targets-key.pem
cd ../..

echo ""
echo "Step 9: Waiting for SSH to be ready..."
sleep 30
for i in {1..10}; do
    if ssh -i /tmp/wp-targets-key.pem -o StrictHostKeyChecking=no -o ConnectTimeout=5 ec2-user@$INSTANCE_IP "echo SSH ready" 2>/dev/null; then
        echo "SSH connection established"
        break
    fi
    echo "Waiting for SSH... (attempt $i/10)"
    sleep 10
done

echo ""
echo "Step 10: Copying Docker image to instance..."
scp -i /tmp/wp-targets-key.pem -o StrictHostKeyChecking=no /tmp/${IMAGE_NAME}.tar ec2-user@$INSTANCE_IP:/tmp/

echo ""
echo "Step 11: Loading Docker image on instance..."
ssh -i /tmp/wp-targets-key.pem -o StrictHostKeyChecking=no ec2-user@$INSTANCE_IP "sudo docker load -i /tmp/${IMAGE_NAME}.tar && rm /tmp/${IMAGE_NAME}.tar"

echo ""
echo "Step 12: Copying SSH key for EC2 provisioning..."
cd infra/wp-targets
terraform output -raw ssh_private_key_pem | ssh -i /tmp/wp-targets-key.pem -o StrictHostKeyChecking=no ec2-user@$INSTANCE_IP "sudo mkdir -p /app/ssh && sudo tee /app/ssh/wp-targets-key.pem > /dev/null && sudo chmod 600 /app/ssh/wp-targets-key.pem"
cd ../..

echo ""
echo "Step 13: Starting wp-setup-service container..."
ssh -i /tmp/wp-targets-key.pem -o StrictHostKeyChecking=no ec2-user@$INSTANCE_IP << ENDSSH
# Stop existing container if running
sudo docker stop wp-setup-service 2>/dev/null || true
sudo docker rm wp-setup-service 2>/dev/null || true

# Start new container
sudo docker run -d \
  --name wp-setup-service \
  --restart unless-stopped \
  -p ${SERVICE_PORT}:8000 \
  -v /app/ssh:/app/ssh:ro \
  -e AWS_DEFAULT_REGION=${REGION} \
  -e MYSQL_ROOT_PASSWORD='${MYSQL_ROOT_PASSWORD}' \
  ${IMAGE_NAME}:latest

echo "Container started"
sudo docker ps | grep wp-setup-service
ENDSSH

echo ""
echo "Step 14: Testing service..."
sleep 5
if curl -s http://${INSTANCE_IP}:${SERVICE_PORT}/health | grep -q "healthy"; then
    echo "✅ Service is healthy!"
else
    echo "⚠️  Service may still be starting..."
fi

echo ""
echo "================================"
echo "Deployment Complete!"
echo "================================"
echo ""
echo "Service URL: http://${INSTANCE_IP}:${SERVICE_PORT}"
echo "UI: http://${INSTANCE_IP}:${SERVICE_PORT}/"
echo "API Docs: http://${INSTANCE_IP}:${SERVICE_PORT}/docs"
echo ""
echo "Instance ID: $INSTANCE_ID"
echo "Instance IP: $INSTANCE_IP"
echo ""
echo "To view logs:"
echo "  ssh -i /tmp/wp-targets-key.pem ec2-user@${INSTANCE_IP}"
echo "  sudo docker logs -f wp-setup-service"
echo ""
echo "To stop service:"
echo "  aws ec2 stop-instances --region ${REGION} --instance-ids ${INSTANCE_ID}"
echo ""
echo "To terminate instance:"
echo "  aws ec2 terminate-instances --region ${REGION} --instance-ids ${INSTANCE_ID}"
echo ""
