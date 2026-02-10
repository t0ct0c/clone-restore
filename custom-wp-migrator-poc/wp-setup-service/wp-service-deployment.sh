#!/bin/bash
# WordPress Setup Service Deployment Script
# Deploys the wp-setup-service to EC2 instance 13.222.20.138

set -e  # Exit on error

# Configuration
SERVER_IP="13.222.20.138"
SSH_KEY="/home/chaz/Desktop/clone-restore/custom-wp-migrator-poc/wp-key.pem"
SSH_USER="ec2-user"
SERVICE_DIR="wp-setup-service"
DOCKER_NETWORK="wp_migration_net"
SERVICE_PORT="5000"
INTERNAL_PORT="8000"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_ssh_connection() {
    log_info "Checking SSH connection to $SERVER_IP..."
    ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no -o ConnectTimeout=5 "$SSH_USER@$SERVER_IP" "echo 'SSH connection successful'" || {
        log_error "Failed to connect to $SERVER_IP"
        exit 1
    }
}

check_docker() {
    log_info "Checking Docker installation on server..."
    ssh -i "$SSH_KEY" "$SSH_USER@$SERVER_IP" "which docker && docker --version" || {
        log_error "Docker not found on server"
        exit 1
    }
}

backup_existing_service() {
    log_info "Backing up existing service..."
    ssh -i "$SSH_KEY" "$SSH_USER@$SERVER_IP" "
        if [ -d \"$SERVICE_DIR\" ]; then
            BACKUP_DIR=\"${SERVICE_DIR}_backup_\$(date +%Y%m%d_%H%M%S)\"
            mv \"$SERVICE_DIR\" \"\$BACKUP_DIR\"
            echo \"Backup created: \$BACKUP_DIR\"
        fi
    "
}

upload_service() {
    log_info "Uploading service code to server..."
    
    # Create tarball of current directory
    cd "$(dirname "$0")"
    tar -czf /tmp/wp-setup-service.tar.gz . --exclude='*.tar.gz' --exclude='*.zip' --exclude='.git' --exclude='__pycache__'
    
    # Upload to server
    scp -i "$SSH_KEY" /tmp/wp-setup-service.tar.gz "$SSH_USER@$SERVER_IP:~/"
    
    # Extract on server
    ssh -i "$SSH_KEY" "$SSH_USER@$SERVER_IP" "
        rm -rf \"$SERVICE_DIR\"
        mkdir -p \"$SERVICE_DIR\"
        tar -xzf wp-setup-service.tar.gz -C \"$SERVICE_DIR\"
        rm wp-setup-service.tar.gz
        echo \"Service uploaded to ~/$SERVICE_DIR\"
    "
    
    # Clean up local tarball
    rm -f /tmp/wp-setup-service.tar.gz
}

create_docker_network() {
    log_info "Creating Docker network if not exists..."
    ssh -i "$SSH_KEY" "$SSH_USER@$SERVER_IP" "
        if ! docker network ls | grep -q \"$DOCKER_NETWORK\"; then
            docker network create \"$DOCKER_NETWORK\"
            echo \"Docker network '$DOCKER_NETWORK' created\"
        else
            echo \"Docker network '$DOCKER_NETWORK' already exists\"
        fi
    "
}

stop_existing_container() {
    log_info "Stopping existing container..."
    ssh -i "$SSH_KEY" "$SSH_USER@$SERVER_IP" "
        if docker ps -a | grep -q wp_setup_service; then
            docker stop wp_setup_service 2>/dev/null || true
            docker rm wp_setup_service 2>/dev/null || true
            echo \"Existing container stopped and removed\"
        fi
    "
}

build_and_deploy() {
    log_info "Building and deploying service..."
    ssh -i "$SSH_KEY" "$SSH_USER@$SERVER_IP" "
        cd \"$SERVICE_DIR\"
        
        # Build Docker image
        echo \"Building Docker image...\"
        docker build -t wp-setup-service:latest .
        
        # Deploy with docker-compose
        echo \"Starting service with docker-compose...\"
        docker-compose up -d
        
        # Wait for service to start
        echo \"Waiting for service to start...\"
        sleep 10
        
        # Check container status
        echo \"Container status:\"
        docker ps | grep wp_setup_service
    "
}

verify_deployment() {
    log_info "Verifying deployment..."
    
    # Check if container is running
    ssh -i "$SSH_KEY" "$SSH_USER@$SERVER_IP" "
        echo \"Container status:\"
        docker ps | grep wp_setup_service
        
        echo -e \"\nContainer logs (last 10 lines):\"
        docker logs wp_setup_service --tail 10 2>/dev/null || echo \"No logs available\"
    "
    
    # Test health endpoint
    log_info "Testing health endpoint..."
    if curl -s "http://$SERVER_IP:$SERVICE_PORT/health" | grep -q "healthy"; then
        log_info "Health check passed!"
    else
        log_warn "Health check failed or service not responding"
    fi
    
    # Test create-app-password endpoint
    log_info "Testing create-app-password endpoint..."
    RESPONSE=$(curl -s -X POST "http://$SERVER_IP:$SERVICE_PORT/create-app-password" \
        -H "Content-Type: application/json" \
        -d '{"url":"http://example.com","username":"test","password":"test"}' \
        -w "\n%{http_code}")
    
    HTTP_CODE=$(echo "$RESPONSE" | tail -1)
    RESPONSE_BODY=$(echo "$RESPONSE" | head -n -1)
    
    if [ "$HTTP_CODE" = "500" ]; then
        log_info "Endpoint is responding (expected error for test credentials)"
        echo "Response: $RESPONSE_BODY"
    else
        log_warn "Unexpected HTTP code: $HTTP_CODE"
        echo "Response: $RESPONSE_BODY"
    fi
}

cleanup_old_containers() {
    log_info "Cleaning up old containers and images..."
    ssh -i "$SSH_KEY" "$SSH_USER@$SERVER_IP" "
        # Remove stopped containers
        docker ps -aq --filter \"status=exited\" | xargs -r docker rm
        
        # Remove dangling images
        docker images -q --filter \"dangling=true\" | xargs -r docker rmi
        
        # List current images
        echo -e \"\nCurrent Docker images:\"
        docker images | grep wp-setup-service
    "
}

show_service_info() {
    log_info "Service Information:"
    echo "=========================================="
    echo "Server: $SERVER_IP"
    echo "Service Port: $SERVICE_PORT"
    echo "Internal Port: $INTERNAL_PORT"
    echo "Docker Network: $DOCKER_NETWORK"
    echo "Service Directory: ~/$SERVICE_DIR"
    echo ""
    echo "Available Endpoints:"
    echo "  GET  http://$SERVER_IP:$SERVICE_PORT/health"
    echo "  POST http://$SERVER_IP:$SERVICE_PORT/create-app-password"
    echo "  POST http://$SERVER_IP:$SERVICE_PORT/clone"
    echo "  POST http://$SERVER_IP:$SERVICE_PORT/setup"
    echo "  POST http://$SERVER_IP:$SERVICE_PORT/restore"
    echo "  POST http://$SERVER_IP:$SERVICE_PORT/provision"
    echo "=========================================="
}

main() {
    echo "=========================================="
    echo "WordPress Setup Service Deployment"
    echo "=========================================="
    
    case "${1:-deploy}" in
        "deploy")
            check_ssh_connection
            check_docker
            backup_existing_service
            upload_service
            create_docker_network
            stop_existing_container
            build_and_deploy
            verify_deployment
            cleanup_old_containers
            show_service_info
            ;;
        "verify")
            check_ssh_connection
            verify_deployment
            show_service_info
            ;;
        "cleanup")
            check_ssh_connection
            stop_existing_container
            cleanup_old_containers
            ;;
        "info")
            show_service_info
            ;;
        *)
            echo "Usage: $0 [deploy|verify|cleanup|info]"
            echo "  deploy  - Full deployment (default)"
            echo "  verify  - Verify existing deployment"
            echo "  cleanup - Clean up old containers"
            echo "  info    - Show service information"
            exit 1
            ;;
    esac
    
    log_info "Deployment script completed!"
}

main "$@"