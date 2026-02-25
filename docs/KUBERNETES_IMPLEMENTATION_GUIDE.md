# Kubernetes Implementation Guide - WordPress Clone/Restore System

**Quick Start Guide for Developers**  
**Based on:** `feat/repair-endpoints` branch → Kubernetes migration

## Prerequisites

### 1. Kubernetes Cluster
- EKS cluster `wp-clone-restore` (version 1.35)
- AWS Load Balancer Controller installed
- EBS CSI driver installed
- ExternalDNS (optional, for automatic DNS)

### 2. Local Development Tools
```bash
# Required tools
kubectl
helm
docker/nerdctl
awscli
k9s (optional, for cluster management)

# Python environment (for wp-setup-service)
python3.11+
uv (package manager)
```

### 3. AWS Permissions
- EKS cluster access
- ECR push/pull permissions
- ALB management permissions
- RDS access (if using shared database)

## Step 1: Set Up Development Environment

### 1.1 Clone and Prepare Repository
```bash
# Switch to feat/repair-endpoints branch
git checkout feat/repair-endpoints

# Set up Python environment
cd custom-wp-migrator-poc/wp-setup-service
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt

# Install Kubernetes dependencies
uv pip install kubernetes
```

### 1.2 Configure kubectl
```bash
# Update kubeconfig for EKS cluster
aws eks update-kubeconfig --name wp-clone-restore --region us-east-1

# Verify access
kubectl get nodes
kubectl get pods -A
```

## Step 2: Create Base Kubernetes Manifests

### 2.1 Create Directory Structure
```bash
mkdir -p kubernetes/manifests/{namespaces,wp-setup-service,wordpress-clone,databases,ingress}
```

### 2.2 Namespace Configuration
```yaml
# kubernetes/manifests/namespaces/wordpress-migration-system.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: wordpress-migration-system
  labels:
    environment: migration
    managed-by: terraform
---
# kubernetes/manifests/namespaces/wordpress-clones.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: wordpress-clones
  labels:
    environment: clones
    managed-by: terraform
```

Apply namespaces:
```bash
kubectl apply -f kubernetes/manifests/namespaces/
```

## Step 3: Deploy wp-setup-service

### 3.1 Create Docker Image
```dockerfile
# custom-wp-migrator-poc/wp-setup-service/Dockerfile.k8s
FROM python:3.11-slim

# Install system dependencies for Playwright
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    gnupg \
    ca-certificates \
    && wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list \
    && apt-get update && apt-get install -y \
    google-chrome-stable \
    fonts-ipafont-gothic \
    fonts-wqy-zenhei \
    fonts-thai-tlwg \
    fonts-kacst \
    fonts-freefont-ttf \
    libxss1 \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install kubernetes

# Install Playwright browsers
RUN playwright install chromium

# Copy application code
COPY . .

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 3.2 Build and Push Image
```bash
# Build image
docker build -f Dockerfile.k8s -t wp-setup-service:k8s .

# Tag for ECR
docker tag wp-setup-service:k8s 044514005641.dkr.ecr.us-east-1.amazonaws.com/wp-setup-service:k8s

# Push to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 044514005641.dkr.ecr.us-east-1.amazonaws.com
docker push 044514005641.dkr.ecr.us-east-1.amazonaws.com/wp-setup-service:k8s
```

### 3.3 Create Kubernetes Deployment
```yaml
# kubernetes/manifests/wp-setup-service/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: wp-setup-service
  namespace: wordpress-migration-system
spec:
  replicas: 2
  selector:
    matchLabels:
      app: wp-setup-service
  template:
    metadata:
      labels:
        app: wp-setup-service
    spec:
      serviceAccountName: wp-setup-service-sa
      containers:
      - name: wp-setup-service
        image: 044514005641.dkr.ecr.us-east-1.amazonaws.com/wp-setup-service:k8s
        ports:
        - containerPort: 8000
        env:
        - name: KUBECONFIG
          value: /var/run/secrets/kubernetes.io/serviceaccount
        - name: AWS_REGION
          value: us-east-1
        - name: ALB_DNS
          value: clones.betaweb.ai
        - name: ALB_LISTENER_ARN
          valueFrom:
            secretKeyRef:
              name: alb-config
              key: listener-arn
        - name: PLUGIN_ZIP_PATH
          value: /app/plugin.zip
        volumeMounts:
        - name: plugin-zip
          mountPath: /app/plugin.zip
          subPath: plugin.zip
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "2Gi"
            cpu: "1000m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5
      volumes:
      - name: plugin-zip
        configMap:
          name: custom-migrator-plugin
---
# kubernetes/manifests/wp-setup-service/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: wp-setup-service
  namespace: wordpress-migration-system
spec:
  selector:
    app: wp-setup-service
  ports:
  - port: 8000
    targetPort: 8000
  type: ClusterIP
```

### 3.4 Create Service Account and RBAC
```yaml
# kubernetes/manifests/wp-setup-service/rbac.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: wp-setup-service-sa
  namespace: wordpress-migration-system
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: wp-setup-service-role
rules:
- apiGroups: [""]
  resources: ["pods", "services", "configmaps", "secrets"]
  verbs: ["create", "get", "list", "watch", "update", "patch", "delete"]
- apiGroups: ["apps"]
  resources: ["deployments"]
  verbs: ["create", "get", "list", "watch", "update", "patch", "delete"]
- apiGroups: ["networking.k8s.io"]
  resources: ["ingresses"]
  verbs: ["create", "get", "list", "watch", "update", "patch", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: wp-setup-service-binding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: wp-setup-service-role
subjects:
- kind: ServiceAccount
  name: wp-setup-service-sa
  namespace: wordpress-migration-system
```

### 3.5 Create ConfigMap for Plugin
```bash
# Create plugin.zip from existing plugin
cd custom-wp-migrator-poc/wordpress-target-image
zip -r plugin.zip plugin/

# Create ConfigMap
kubectl create configmap custom-migrator-plugin \
  --namespace wordpress-migration-system \
  --from-file=plugin.zip=plugin.zip
```

### 3.6 Create ALB Configuration Secret
```bash
# Get ALB listener ARN from AWS Console or Terraform output
ALB_LISTENER_ARN="arn:aws:elasticloadbalancing:us-east-1:044514005641:listener/app/wp-targets-alb/9deaa3f04bc5506b/f6542ccc3f16bfd7"

kubectl create secret generic alb-config \
  --namespace wordpress-migration-system \
  --from-literal=listener-arn=$ALB_LISTENER_ARN
```

### 3.7 Deploy wp-setup-service
```bash
kubectl apply -f kubernetes/manifests/wp-setup-service/
```

## Step 4: Create WordPress Clone Template

### 4.1 WordPress Deployment Template
```yaml
# kubernetes/manifests/wordpress-clone/template.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: wordpress-clone-{TIMESTAMP}
  namespace: wordpress-clones
  labels:
    clone-id: {TIMESTAMP}
    managed-by: wp-setup-service
spec:
  replicas: 1
  selector:
    matchLabels:
      app: wordpress
      clone-id: {TIMESTAMP}
  template:
    metadata:
      labels:
        app: wordpress
        clone-id: {TIMESTAMP}
    spec:
      containers:
      - name: wordpress
        image: wordpress:latest
        env:
        - name: WORDPRESS_DB_HOST
          value: localhost
        - name: WORDPRESS_DB_USER
          value: wpuser
        - name: WORDPRESS_DB_PASSWORD
          valueFrom:
            secretKeyRef:
              name: mysql-credentials-{TIMESTAMP}
              key: password
        - name: WORDPRESS_DB_NAME
          value: wordpress_{TIMESTAMP}
        ports:
        - containerPort: 80
        volumeMounts:
        - name: wp-content
          mountPath: /var/www/html/wp-content
        - name: plugin
          mountPath: /var/www/html/wp-content/plugins/custom-migrator
        resources:
          requests:
            memory: "256Mi"
            cpu: "100m"
          limits:
            memory: "1Gi"
            cpu: "500m"
      - name: mysql
        image: mysql:8.0
        env:
        - name: MYSQL_ROOT_PASSWORD
          valueFrom:
            secretKeyRef:
              name: mysql-credentials-{TIMESTAMP}
              key: root-password
        - name: MYSQL_DATABASE
          value: wordpress_{TIMESTAMP}
        - name: MYSQL_USER
          value: wpuser
        - name: MYSQL_PASSWORD
          valueFrom:
            secretKeyRef:
              name: mysql-credentials-{TIMESTAMP}
              key: password
        ports:
        - containerPort: 3306
        volumeMounts:
        - name: mysql-data
          mountPath: /var/lib/mysql
      volumes:
      - name: wp-content
        persistentVolumeClaim:
          claimName: wp-content-{TIMESTAMP}
      - name: plugin
        configMap:
          name: custom-migrator-plugin
      - name: mysql-data
        persistentVolumeClaim:
          claimName: mysql-data-{TIMESTAMP}
---
# kubernetes/manifests/wordpress-clone/service-template.yaml
apiVersion: v1
kind: Service
metadata:
  name: wordpress-clone-{TIMESTAMP}
  namespace: wordpress-clones
spec:
  selector:
    app: wordpress
    clone-id: {TIMESTAMP}
  ports:
  - port: 80
    targetPort: 80
  type: ClusterIP
```

### 4.2 Ingress Template for ALB Routing
```yaml
# kubernetes/manifests/ingress/template.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: wordpress-clone-{TIMESTAMP}
  namespace: wordpress-clones
  annotations:
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip
    alb.ingress.kubernetes.io/listen-ports: '[{"HTTPS":443}]'
    alb.ingress.kubernetes.io/certificate-arn: arn:aws:acm:us-east-1:044514005641:certificate/c3fb5ab3-160f-4db2-ac4b-056fe7166558
    alb.ingress.kubernetes.io/group.name: wp-clones
spec:
  ingressClassName: alb
  rules:
  - http:
      paths:
      - path: /clone-{TIMESTAMP}/*
        pathType: Prefix
        backend:
          service:
            name: wordpress-clone-{TIMESTAMP}
            port:
              number: 80
```

## Step 5: Modify wp-setup-service for Kubernetes

### 5.1 Create Kubernetes Client Module
```python
# custom-wp-migrator-poc/wp-setup-service/app/k8s_client.py
"""
Kubernetes client for WordPress clone management
"""
import yaml
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class KubernetesClient:
    def __init__(self):
        # Load in-cluster config
        config.load_incluster_config()
        self.apps_v1 = client.AppsV1Api()
        self.core_v1 = client.CoreV1Api()
        self.networking_v1 = client.NetworkingV1Api()
        
    def create_clone(self, clone_id: str, source_url: str) -> dict:
        """
        Create a WordPress clone in Kubernetes
        """
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        
        try:
            # 1. Create namespace if not exists
            self._ensure_namespace("wordpress-clones")
            
            # 2. Create MySQL credentials secret
            self._create_mysql_secret(clone_id, timestamp)
            
            # 3. Create PersistentVolumeClaims
            self._create_pvcs(clone_id, timestamp)
            
            # 4. Create WordPress Deployment
            deployment = self._create_deployment(clone_id, timestamp, source_url)
            
            # 5. Create Service
            service = self._create_service(clone_id, timestamp)
            
            # 6. Create Ingress for ALB routing
            ingress = self._create_ingress(clone_id, timestamp)
            
            return {
                "success": True,
                "clone_url": f"https://clones.betaweb.ai/clone-{timestamp}",
                "namespace": "wordpress-clones",
                "deployment": deployment.metadata.name,
                "service": service.metadata.name,
                "ingress": ingress.metadata.name,
                "timestamp": timestamp
            }
            
        except ApiException as e:
            logger.error(f"Kubernetes API error: {e}")
            return {
                "success": False,
                "error": str(e),
                "error_code": "K8S_API_ERROR"
            }
    
    def _ensure_namespace(self, namespace: str):
        """Ensure namespace exists"""
        try:
            self.core_v1.read_namespace(namespace)
        except ApiException:
            # Create namespace
            namespace_body = client.V1Namespace(
                metadata=client.V1ObjectMeta(name=namespace)
            )
            self.core_v1.create_namespace(namespace_body)
    
    def _create_mysql_secret(self, clone_id: str, timestamp: str):
        """Create MySQL credentials secret"""
        import secrets
        import string
        
        # Generate random passwords
        alphabet = string.ascii_letters + string.digits
        root_password = ''.join(secrets.choice(alphabet) for _ in range(16))
        user_password = ''.join(secrets.choice(alphabet) for _ in range(16))
        
        secret_body = client.V1Secret(
            metadata=client.V1ObjectMeta(
                name=f"mysql-credentials-{timestamp}",
                namespace="wordpress-clones"
            ),
            string_data={
                "root-password": root_password,
                "password": user_password
            },
            type="Opaque"
        )
        
        return self.core_v1.create_namespaced_secret(
            namespace="wordpress-clones",
            body=secret_body
        )
    
    def _create_pvcs(self, clone_id: str, timestamp: str):
        """Create PersistentVolumeClaims for WordPress and MySQL"""
        # WordPress content PVC
        wp_pvc = client.V1PersistentVolumeClaim(
            metadata=client.V1ObjectMeta(
                name=f"wp-content-{timestamp}",
                namespace="wordpress-clones"
            ),
            spec=client.V1PersistentVolumeClaimSpec(
                access_modes=["ReadWriteOnce"],
                resources=client.V1ResourceRequirements(
                    requests={"storage": "5Gi"}
                ),
                storage_class_name="gp2"
            )
        )
        
        # MySQL data PVC
        mysql_pvc = client.V1PersistentVolumeClaim(
            metadata=client.V1ObjectMeta(
                name=f"mysql-data-{timestamp}",
                namespace="wordpress-clones"
            ),
            spec=client.V1PersistentVolumeClaimSpec(
                access_modes=["ReadWriteOnce"],
                resources=client.V1ResourceRequirements(
                    requests={"storage": "10Gi"}
                ),
                storage_class_name="gp2"
            )
        )
        
        self.core_v1.create_namespaced_persistent_volume_claim(
            namespace="wordpress-clones",
            body=wp_pvc
        )
        
        self.core_v1.create_namespaced_persistent_volume_claim(
            namespace="wordpress-clones",
            body=mysql_pvc
        )
    
    def _create_deployment(self, clone_id: str, timestamp: str, source_url: str):
        """Create WordPress Deployment with MySQL sidecar"""
        # Load template and replace placeholders
        with open("/app/templates/wordpress-deployment.yaml") as f:
            template = f.read()
        
        template = template.replace("{TIMESTAMP}", timestamp)
        
        deployment_body = yaml.safe_load(template)
        
        return self.apps_v1.create_namespaced_deployment(
            namespace="wordpress-clones",
            body=deployment_body
        )
    
    def _create_service(self, clone_id: str, timestamp: str):
        """Create Service for WordPress clone"""
        with open("/app/templates/wordpress-service.yaml") as f:
            template = f.read()
        
        template = template.replace("{TIMESTAMP}", timestamp)
        
        service_body = yaml.safe_load(template)
        
        return self.core_v1.create_namespaced_service(
            namespace="wordpress-clones",
            body=service_body
        )
    
    def _create_ingress(self, clone_id: str, timestamp: str):
        """Create Ingress for ALB routing"""
        with open("/app/templates/wordpress-ingress.yaml") as f:
            template = f.read()
        
        template = template.replace("{TIMESTAMP}", timestamp)
        
        ingress_body = yaml.safe_load(template)
        
        return self.networking_v1.create_namespaced_ingress(
            namespace="wordpress-clones",
            body=ingress_body
        )
    
    def delete_clone(self, clone_id: str):
        """Delete WordPress clone resources"""
        try:
            # Delete Ingress
            self.networking_v1.delete_namespaced_ingress(
                name=f"wordpress-clone-{clone_id}",
                namespace="wordpress-clones"
            )
            
            # Delete Service
            self.core_v1.delete_namespaced_service(
                name=f"wordpress-clone-{clone_id}",
                namespace="wordpress-clones"
            )
            
            # Delete Deployment
            self.apps_v1.delete_namespaced_deployment(
                name=f"wordpress-clone-{clone_id}",
                namespace="wordpress-clones",
                propagation_policy="Foreground"
            )
            
            # Delete PVCs
            self.core_v1.delete_namespaced_persistent_volume_claim(
                name=f"wp-content-{clone_id}",
                namespace="wordpress-clones"
            )
            
            self.core_v1.delete_namespaced_persistent_volume_claim(
                name=f"mysql-data-{clone_id}",
                namespace="wordpress-clones"
            )
            
            # Delete Secret
            self.core_v1.delete_namespaced_secret(
                name=f"mysql-credentials-{clone_id}",
                namespace="wordpress-clones"
            )
            
            return {"success": True}
            
        except ApiException as e:
            logger.error(f"Error deleting clone {clone_id}: {e}")
            return {"success": False, "error": str(e)}
```

### 5.2 Update main.py to Use Kubernetes Client
```python
# In custom-wp-migrator-poc/wp-setup-service/app/main.py
# Add import
from .k8s_client import KubernetesClient

# Modify clone endpoint to use Kubernetes
@app.post("/clone", response_model=CloneResponse)
async def clone_endpoint(request: CloneRequest):
    """
    Clone WordPress from source to target using Kubernetes
    """
    # Initialize Kubernetes client
    k8s_client = KubernetesClient()
    
    # Generate clone ID
    clone_id = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    
    # Create clone in Kubernetes
    clone_result = k8s_client.create_clone(clone_id, str(request.source.url))
    
    if not clone_result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Kubernetes clone creation failed: {clone_result.get('error')}",
        )
    
    # Continue with existing setup logic...
    # (Setup source WordPress, browser automation, etc.)
```

## Step 6: Testing and Validation

### 6.1 Test wp-setup-service Deployment
```bash
# Check pods
kubectl get pods -n wordpress-migration-system

# Check logs
kubectl logs -f deployment/wp-setup-service -n wordpress-migration-system

# Port forward for local testing
kubectl port-forward svc/wp-setup-service 8000:8000 -n wordpress-migration-system

# Test health endpoint
curl http://localhost:8000/health
```

### 6.2 Test Clone Creation
```bash
# Create a test clone
curl -X POST http://localhost:8000/clone \
  -H "Content-Type: application/json" \
  -d '{
    "source": {
      "url": "https://example.com",
      "username": "admin",
      "password": "password"
    }
  }'

# Check Kubernetes resources
kubectl get all -n wordpress-clones
kubectl get ingress -n wordpress-clones
kubectl get pvc -n wordpress-clones
```

### 6.3 Verify ALB Integration
```bash
# Get Ingress details
kubectl describe ingress -n wordpress-clones

# Test clone URL (after DNS propagation)
curl -I "https://clones.betaweb.ai/clone-YYYYMMDD-HHMMSS/"
```

## Step 7: Gradual Migration Strategy

### 7.1 Phase 1: Dual Deployment
```
EC2 wp-setup-service (production) ←→ Kubernetes wp-setup-service (staging)
                                  ↕
                            Same ALB, different paths
```

### 7.2 Phase 2: Traffic Splitting
- Route 50% of traffic to Kubernetes
- Monitor performance and errors
- Adjust split based on results

### 7.3 Phase 3: Full Migration
- Route 100% traffic to Kubernetes
- Decommission EC2 resources
- Update documentation

## Troubleshooting Guide

### Common Issues

#### 1. "ImagePullBackOff" Error
```bash
# Check image exists in ECR
aws ecr describe-images --repository-name wp-setup-service --region us-east-1

# Check ECR permissions
kubectl describe pod wp-setup-service-xxx -n wordpress-migration-system
```

#### 2. ALB Not Created
```bash
# Check AWS Load Balancer Controller logs
kubectl logs -f deployment/aws-load-balancer-controller -n kube-system

# Check Ingress events
kubectl describe ingress -n wordpress-clones
```

#### 3. WordPress Cannot Connect to MySQL
```bash
# Check MySQL pod logs
kubectl logs wordpress-clone-xxx-mysql -n wordpress-clones

# Check WordPress pod logs
kubectl logs wordpress-clone-xxx-wordpress -n wordpress-clones

# Test MySQL connection from WordPress pod
kubectl exec -it wordpress-clone-xxx-wordpress -n wordpress-clones -- \
  mysql -h localhost -u wpuser -p
```

#### 4. Browser Automation Fails
```bash
# Check Playwright installation
kubectl exec -it wp-setup-service-xxx -n wordpress-migration-system -- \
  playwright --version

# Check Chrome availability
kubectl exec -it wp-setup-service-xxx -n wordpress-migration-system -- \
  google-chrome --version
```

## Monitoring and Logging

### 7.1 Set Up Monitoring
```bash
# Install Prometheus stack
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install prometheus prometheus-community/kube-prometheus-stack -n monitoring

# Create ServiceMonitors for wp-setup-service
kubectl apply -f kubernetes/manifests/monitoring/
```

### 7.2 Configure Logging
```bash
# Install FluentBit
helm repo add fluent https://fluent.github.io/helm-charts
helm install fluent-bit fluent/fluent-bit -n logging

# Configure CloudWatch logs
# Update FluentBit config to send logs to CloudWatch
```

## Cleanup Commands

### Delete Test Resources
```bash
# Delete all clones
kubectl delete namespace wordpress-clones

# Delete wp-setup-service
kubectl delete -f kubernetes/manifests/wp-setup-service/

# Delete namespaces
kubectl delete namespace wordpress-migration-system
```

### Rollback to EC2
```bash
# Scale down Kubernetes deployment
kubectl scale deployment wp-setup-service --replicas=0 -n wordpress-migration-system

# Restart EC2 wp-setup-service
ssh ec2-user@13.222.20.138 "docker restart wp-setup-service"
```

## Next Steps After Implementation

1. **Performance Testing**: Load test with multiple concurrent clones
2. **Automated Testing**: Implement CI/CD pipeline
3. **Backup Strategy**: Implement Velero for cluster backups
4. **Security Hardening**: Network policies, pod security standards
5. **Cost Optimization**: Right-size resources, implement auto-scaling

---

**Implementation Status**: Ready for development  
**Estimated Time**: 2-4 weeks for full migration  
**Risk Level**: Medium (managed rollout with rollback plan)  
**Success Criteria**: All existing functionality working in Kubernetes with equal or better performance