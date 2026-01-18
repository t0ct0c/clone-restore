#!/bin/bash
# EC2 User Data Script for WordPress Target Hosts
# Installs Docker, Nginx, and configures the instance for container hosting

set -e

# Update system
yum update -y

# Install Docker
amazon-linux-extras install docker -y
systemctl start docker
systemctl enable docker
usermod -aG docker ec2-user

# Install Loki Docker driver
docker plugin install grafana/loki-docker-driver:latest --alias loki --grant-all-permissions

# Install Nginx
amazon-linux-extras install nginx1 -y
systemctl start nginx
systemctl enable nginx

# Create Nginx sites directories
mkdir -p /etc/nginx/sites-available
mkdir -p /etc/nginx/sites-enabled

# Configure Nginx to include sites-enabled
cat > /etc/nginx/nginx.conf << 'EOF'
user nginx;
worker_processes auto;
error_log /var/log/nginx/error.log;
pid /run/nginx.pid;

events {
    worker_connections 1024;
}

http {
    log_format  main  '$remote_addr - $remote_user [$time_local] "$request" '
                      '$status $body_bytes_sent "$http_referer" '
                      '"$http_user_agent" "$http_x_forwarded_for"';

    access_log  /var/log/nginx/access.log  main;

    sendfile            on;
    tcp_nopush          on;
    tcp_nodelay         on;
    keepalive_timeout   65;
    types_hash_max_size 4096;

    include             /etc/nginx/mime.types;
    default_type        application/octet-stream;
    
    # Default server block for ALB health checks and WordPress proxying
    server {
        listen 80;
        listen [::]:80;
        server_name _;
        
        # Health check endpoint for ALB
        location / {
            return 200 "OK";
        }
        
        # Include dynamic location configs for WordPress containers
        include /etc/nginx/default.d/*.conf;
    }
}
EOF

# Create default.d directory for dynamic location configs
mkdir -p /etc/nginx/default.d

# Restart Nginx
systemctl restart nginx

# Start MySQL container for shared database
echo "Starting MySQL container..."
docker run -d \
  --name mysql \
  --restart unless-stopped \
  -e MYSQL_ROOT_PASSWORD='${mysql_root_password}' \
  -v /var/lib/mysql:/var/lib/mysql \
  -p 3306:3306 \
  mysql:8.0 \
  --default-authentication-plugin=mysql_native_password

# Wait for MySQL to be ready
echo "Waiting for MySQL to be ready..."
for i in {1..30}; do
  if docker exec mysql mysqladmin ping -h localhost -p'${mysql_root_password}' --silent 2>/dev/null; then
    echo "MySQL is ready"
    break
  fi
  echo "Waiting for MySQL... ($i/30)"
  sleep 2
done

# Pull WordPress Docker image
docker pull ghcr.io/t0ct0c/wordpress-migrator:latest

# Install at command for TTL scheduling
yum install -y at
systemctl start atd
systemctl enable atd

# Install CloudWatch Agent for custom metrics
wget https://s3.amazonaws.com/amazoncloudwatch-agent/amazon_linux/amd64/latest/amazon-cloudwatch-agent.rpm
rpm -U ./amazon-cloudwatch-agent.rpm

# Create CloudWatch config for container count metric
cat > /opt/aws/amazon-cloudwatch-agent/etc/config.json << 'EOF'
{
  "metrics": {
    "namespace": "WPTargets",
    "metrics_collected": {
      "statsd": {
        "service_address": ":8125",
        "metrics_collection_interval": 60,
        "metrics_aggregation_interval": 60
      }
    }
  }
}
EOF

# Start CloudWatch Agent
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config \
  -m ec2 \
  -s \
  -c file:/opt/aws/amazon-cloudwatch-agent/etc/config.json

# Create script to publish container count metric
cat > /usr/local/bin/publish-container-count.sh << 'EOF'
#!/bin/bash
CONTAINER_COUNT=$(docker ps --filter "name=client-" --format "{{.ID}}" | wc -l)
INSTANCE_ID=$(ec2-metadata --instance-id | cut -d " " -f 2)

aws cloudwatch put-metric-data \
  --namespace WPTargets \
  --metric-name ContainerCount \
  --dimensions InstanceId=$INSTANCE_ID \
  --value $CONTAINER_COUNT \
  --region us-east-1
EOF

chmod +x /usr/local/bin/publish-container-count.sh

# Schedule container count metric publishing every minute
(crontab -l 2>/dev/null; echo "* * * * * /usr/local/bin/publish-container-count.sh") | crontab -

# Create SSH directory for service access
mkdir -p /home/ec2-user/.ssh
chown ec2-user:ec2-user /home/ec2-user/.ssh

echo "User data script completed successfully"
