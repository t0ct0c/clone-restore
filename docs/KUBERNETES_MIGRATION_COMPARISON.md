# Kubernetes Migration - Architecture Comparison & Refactoring Guide

**Purpose**: This document provides a side-by-side comparison between the current `feat/restore` implementation and the planned Kubernetes architecture to guide the refactoring process.

**Last Updated**: 2026-02-06
**Current Branch**: `feat/restore`
**Target Branch**: `feat/kubernetes`

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Component Mapping](#component-mapping)
3. [Workflow Comparison](#workflow-comparison)
4. [Infrastructure Changes](#infrastructure-changes)
5. [Code Migration Strategy](#code-migration-strategy)
6. [Critical Design Decisions](#critical-design-decisions)
7. [Migration Roadmap](#migration-roadmap)

---

## Executive Summary

### Current State (feat/restore)
- **Platform**: AWS EC2 + Docker
- **Orchestration**: SSH + paramiko (imperative)
- **Provisioning**: Manual Docker commands via SSH
- **Networking**: ALB + Nginx + manual port allocation
- **Database**: MySQL container (single instance)
- **Scaling**: EC2 Auto Scaling Group
- **State**: No persistent clone state
- **Cost**: ~$124/month

### Target State (feat/kubernetes)
- **Platform**: AWS EKS (Kubernetes 1.35)
- **Orchestration**: Kubernetes API (declarative)
- **Provisioning**: KRO ResourceGroups + Helm
- **Networking**: AWS Load Balancer Controller + Ingress
- **Database**: RDS MySQL (managed, multi-AZ)
- **Scaling**: Karpenter + KEDA
- **State**: Kubernetes resources (Pods, Services, ConfigMaps)
- **Cost**: ~$140/month (estimated)

### Key Benefits of Migration

✅ **Cloud-Native**: Declarative infrastructure, no SSH operations
✅ **High Availability**: Multi-AZ, self-healing, automatic failover
✅ **GitOps**: Argo CD for deployments, version control
✅ **Better Scaling**: KEDA + Karpenter for dynamic scaling
✅ **Observability**: Native Kubernetes metrics + existing Loki/Tempo
✅ **Developer Experience**: kubectl, no SSH key management

---

## Component Mapping

### 1. Management Service (FastAPI)

| Current (EC2 + Docker) | Kubernetes | Changes Required |
|------------------------|------------|------------------|
| **Deployment**: Manual `docker run` | **Deployment**: Kubernetes Deployment | Convert Docker run to YAML |
| **Networking**: Host port 8000 | **Service**: ClusterIP + Ingress | Create Service + Ingress |
| **Scaling**: Single container | **HPA**: Horizontal Pod Autoscaler | Add HPA for load-based scaling |
| **Updates**: Manual SSH + docker pull | **GitOps**: Argo CD | Create Application manifest |
| **Secrets**: Env vars | **Secrets**: Kubernetes Secret | Migrate MYSQL_ROOT_PASSWORD |

**File Changes**:
- ✅ Keep: `wp-setup-service/app/main.py` (API logic)
- ✅ Keep: `wp-setup-service/app/browser_setup.py` (browser automation)
- ❌ Replace: `wp-setup-service/app/ec2_provisioner.py` → `k8s_provisioner.py`
- ➕ Add: `kubernetes/wp-k8s-service/deployment.yaml`
- ➕ Add: `kubernetes/wp-k8s-service/service.yaml`
- ➕ Add: `kubernetes/wp-k8s-service/ingress.yaml`

### 2. WordPress Clones

| Current (EC2 + Docker) | Kubernetes | Changes Required |
|------------------------|------------|------------------|
| **Provisioning**: SSH + `docker run` | **Provisioning**: KRO ResourceGroup or Job | Create ResourceGroup template |
| **Container**: Manual port allocation (8001-8050) | **Pod**: Automatic port via Service | No manual port allocation |
| **Naming**: `clone-YYYYMMDD-HHMMSS` | **Pod**: `wp-clone-xxx` | Same naming convention |
| **Storage**: Container ephemeral | **Storage**: EmptyDir or PVC | Decision: EmptyDir vs S3 |
| **Database**: MySQL container | **Database**: RDS MySQL via ACK | Create DBInstance resource |
| **Networking**: Nginx reverse proxy | **Networking**: Kubernetes Service | Create Service per clone |
| **Routing**: ALB listener rules | **Routing**: Ingress path rules | Create Ingress per clone |
| **Cleanup**: `at` command cron | **Cleanup**: Kubernetes CronJob or TTL | Create CronJob or use TTL |

**File Changes**:
- ✅ Keep: `wordpress-target-image/Dockerfile` (container image)
- ✅ Keep: `wordpress-target-image/plugin/` (WordPress plugin code)
- ➕ Add: `kubernetes/kro-resources/wordpress-clone-resourcegroup.yaml`
- ➕ Add: `kubernetes/wp-k8s-service/templates/wordpress-pod.yaml` (if not using KRO)

### 3. Database (MySQL)

| Current (EC2 + Docker) | Kubernetes | Changes Required |
|------------------------|------------|------------------|
| **Type**: MySQL 8.0 container | **Type**: RDS MySQL 8.0 | ACK controller provisioning |
| **Deployment**: `docker run mysql:8.0` | **Deployment**: ACK DBInstance CR | Create DBInstance YAML |
| **High Availability**: None (single container) | **High Availability**: Multi-AZ RDS | Enabled by default |
| **Backups**: None | **Backups**: Automated RDS backups | Enabled by default |
| **Scaling**: Vertical only (container limits) | **Scaling**: Vertical (RDS instance type) | Manual or scheduled |
| **Access**: `host.docker.internal:3306` | **Access**: RDS endpoint | Update connection string |
| **DB Creation**: SSH + `docker exec mysql` | **DB Creation**: SQL via RDS endpoint | Update provisioner logic |

**File Changes**:
- ❌ Remove: MySQL container deployment
- ➕ Add: `kubernetes/bootstrap/terraform/rds.tf` (RDS instance)
- 🔄 Update: `k8s_provisioner.py` to use RDS endpoint instead of docker exec

### 4. Reverse Proxy / Load Balancing

| Current (EC2 + Docker) | Kubernetes | Changes Required |
|------------------------|------------|------------------|
| **Layer 1**: ALB (AWS) | **Layer 1**: ALB (AWS Load Balancer Controller) | Deploy controller |
| **Layer 2**: Nginx on EC2 | **Layer 2**: Kubernetes Ingress | No Nginx needed |
| **Config Management**: SSH + write file + reload | **Config Management**: kubectl apply Ingress | Declarative YAML |
| **Path Routing**: Nginx location blocks | **Path Routing**: Ingress path rules | Same concept, different syntax |
| **Dynamic Rules**: Python boto3 elbv2 API | **Dynamic Rules**: kubectl create ingress | Kubernetes API |
| **Example**: `/etc/nginx/default.d/clone-xxx.conf` | **Example**: `ingress-clone-xxx.yaml` | Convert config format |

**Nginx Config** (Current):
```nginx
location /clone-20260206-120000/ {
    proxy_pass http://localhost:8021/;
    proxy_set_header Host localhost;
    proxy_redirect / /clone-20260206-120000/;
}
```

**Kubernetes Ingress** (Target):
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: clone-20260206-120000
  annotations:
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip
spec:
  ingressClassName: alb
  rules:
  - http:
      paths:
      - path: /clone-20260206-120000
        pathType: Prefix
        backend:
          service:
            name: clone-20260206-120000
            port:
              number: 80
```

### 5. Auto Scaling

| Current (EC2 + Docker) | Kubernetes | Changes Required |
|------------------------|------------|------------------|
| **Node Scaling**: EC2 ASG (1-5 instances) | **Node Scaling**: Karpenter | Deploy Karpenter |
| **Trigger**: CPU utilization or container count | **Trigger**: Pending pods | Automatic |
| **Container Scaling**: Manual (50 containers/instance max) | **Pod Scaling**: KEDA ScaledObject | Create ScaledObject |
| **Scale-Up Logic**: Python code checks 80% capacity | **Scale-Up Logic**: Kubernetes scheduler | Native |
| **Scale-Down**: Manual or TTL cleanup | **Scale-Down**: Karpenter consolidation | Automatic |

**File Changes**:
- ❌ Remove: ASG-based scaling logic from `ec2_provisioner.py`
- ➕ Add: `kubernetes/keda/scaledobject.yaml`
- ➕ Add: `kubernetes/bootstrap/terraform/karpenter.tf` (already exists)

### 6. Observability

| Current (EC2 + Docker) | Kubernetes | Changes Required |
|------------------------|------------|------------------|
| **Logs**: Docker Loki driver | **Logs**: Fluent Bit DaemonSet → Loki | Deploy Fluent Bit |
| **Traces**: OpenTelemetry OTLP exporter | **Traces**: Same (OTLP exporter) | No change |
| **Metrics**: None | **Metrics**: Prometheus + Kube State Metrics | Deploy Prometheus |
| **Dashboards**: Grafana | **Dashboards**: Grafana | Same |

**File Changes**:
- ✅ Keep: OpenTelemetry instrumentation in `main.py`
- ➕ Add: `kubernetes/observability/fluent-bit-daemonset.yaml`
- ➕ Add: `kubernetes/observability/prometheus.yaml`

---

## Workflow Comparison

### Clone Workflow: Before vs After

#### Current (feat/restore)

```python
# ec2_provisioner.py
def provision_target(customer_id, ttl_minutes):
    1. Find least-loaded EC2 instance (boto3 ASG API)
    2. SSH into instance (paramiko)
    3. Allocate port: check docker ps, find next free 8001-8050
    4. Generate passwords
    5. SSH exec: docker exec mysql "CREATE DATABASE ..."
    6. SSH exec: docker run wordpress-target-sqlite ...
    7. SSH exec: echo nginx config > /etc/nginx/default.d/clone-xxx.conf
    8. SSH exec: sudo systemctl reload nginx
    9. boto3: Create ALB target group + listener rule
    10. SSH exec: echo cleanup script | at now + 60 minutes
    return {target_url, username, password}
```

#### Target (Kubernetes)

```python
# k8s_provisioner.py
from kubernetes import client, config

def provision_target(customer_id, ttl_minutes):
    1. Load kubeconfig (or in-cluster config)
    2. Generate passwords (same)
    3. Create Secret: kubectl apply -f secret.yaml
    4. Create ConfigMap: kubectl apply -f configmap.yaml

    # Option A: KRO ResourceGroup (preferred)
    5. Create ResourceGroup: kubectl apply -f resourcegroup.yaml
       - KRO automatically creates: Pod, Service, Ingress, DBInstance
       - KRO handles dependencies (DB ready before Pod)

    # Option B: Manual resources (fallback)
    5a. Create DBInstance: kubectl apply -f dbinstance.yaml (ACK)
    5b. Wait for DBInstance ready: kubectl wait --for=condition=ACKResourceSynced
    5c. Create Deployment: kubectl apply -f deployment.yaml
    5d. Create Service: kubectl apply -f service.yaml
    5e. Create Ingress: kubectl apply -f ingress.yaml

    6. Wait for Pod ready: kubectl wait --for=condition=Ready pod/clone-xxx
    7. Get Ingress URL: kubectl get ingress clone-xxx -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'
    8. Schedule cleanup: kubectl apply -f cronjob.yaml (ttl-based)

    return {target_url, username, password}
```

**Key Differences**:
- ❌ No SSH operations
- ❌ No manual port allocation
- ❌ No Nginx config files
- ❌ No boto3 ALB API calls
- ✅ Declarative YAML resources
- ✅ Kubernetes API operations
- ✅ KRO handles dependencies

### Database Creation: Before vs After

#### Current (SSH + docker exec)

```python
ssh = paramiko.SSHClient()
ssh.connect(instance_ip, key_filename=self.ssh_key_path)

mysql_cmd = f"""
docker exec mysql mysql -uroot -p{mysql_root_password} -e "
CREATE DATABASE IF NOT EXISTS wp_clone_20260206_120000;
CREATE USER 'wp_clone_20260206_120000'@'%' IDENTIFIED BY '{db_password}';
GRANT ALL PRIVILEGES ON wp_clone_20260206_120000.* TO 'wp_clone_20260206_120000'@'%';
FLUSH PRIVILEGES;
"
"""

stdin, stdout, stderr = ssh.exec_command(mysql_cmd)
ssh.close()
```

#### Target (ACK + RDS)

```python
from kubernetes import client

# Create DBInstance resource (ACK creates RDS database)
db_instance = {
    "apiVersion": "rds.services.k8s.aws/v1alpha1",
    "kind": "DBInstance",
    "metadata": {
        "name": f"wp-clone-{customer_id}",
        "namespace": "wordpress-staging"
    },
    "spec": {
        "dbInstanceIdentifier": f"wp-clone-{customer_id}",
        "dbInstanceClass": "db.t3.micro",
        "engine": "mysql",
        "engineVersion": "8.0",
        "masterUsername": "admin",
        "masterUserPassword": {"name": f"db-secret-{customer_id}", "key": "password"},
        "allocatedStorage": 20,
        "multiAZ": false  # True for production
    }
}

api = client.CustomObjectsApi()
api.create_namespaced_custom_object(
    group="rds.services.k8s.aws",
    version="v1alpha1",
    namespace="wordpress-staging",
    plural="dbinstances",
    body=db_instance
)

# Wait for DBInstance to be ready
# Get endpoint from status
```

**Key Differences**:
- ❌ No SSH, no docker exec
- ✅ Declarative Kubernetes resource
- ✅ ACK controller handles RDS API calls
- ✅ Multi-AZ support for production

---

## Infrastructure Changes

### Networking Architecture

#### Current (EC2 + Docker)

```
Internet
    ↓
AWS ALB (port 80)
    ↓ Listener rules: /clone-xxx/* → TargetGroup-xxx
EC2 Instance (10.0.13.72:80)
    ↓ Nginx reverse proxy
Docker Containers (localhost:8001-8050)
    ↓
MySQL Container (host.docker.internal:3306)
```

#### Target (Kubernetes)

```
Internet
    ↓
AWS ALB (port 80)
    ↓ Managed by AWS Load Balancer Controller
Kubernetes Ingress (path-based routing)
    ↓
Kubernetes Service (ClusterIP)
    ↓
Pod (ephemeral IP, dynamic port)
    ↓
RDS MySQL (managed endpoint)
```

### Terraform Changes

| Resource | Current | Kubernetes | Status |
|----------|---------|------------|--------|
| VPC | ✅ Exists | ✅ Keep | No change |
| Subnets | ✅ 3 public + 3 private | ✅ Keep | No change |
| NAT Gateway | ✅ 1 gateway | ✅ Keep | No change |
| EC2 ASG | ✅ wp-targets-asg | ❌ Remove | Replace with EKS nodes |
| ALB | ✅ wp-targets-alb | 🔄 Managed by K8s | Keep ALB, remove manual rules |
| EKS Cluster | ❌ None | ➕ Create | **DONE** (K8s 1.35) |
| RDS Instance | ❌ None | ➕ Create | **TODO** |
| Karpenter | ❌ None | ✅ Exists | **DONE** (v1.8.6) |
| KEDA | ❌ None | ✅ Exists | **DONE** (installed) |
| IAM Roles | ✅ EC2 instance role | 🔄 IRSA roles | **DONE** (5 roles created) |

---

## Code Migration Strategy

### Phase 1: Core Service (wp-k8s-service)

**Goal**: Deploy FastAPI management service to Kubernetes

**Files to Create**:
```
kubernetes/wp-k8s-service/
├── base/
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── ingress.yaml
│   ├── configmap.yaml
│   ├── secret.yaml (sealed)
│   └── kustomization.yaml
├── overlays/
│   ├── staging/
│   │   └── kustomization.yaml
│   └── production/
│       └── kustomization.yaml
└── Dockerfile (copy from wp-setup-service)
```

**Code Changes**:
1. Create `k8s_provisioner.py` (replace `ec2_provisioner.py`)
2. Update `main.py` to use `k8s_provisioner.py`
3. Add `kubernetes` Python library to `requirements.txt`
4. Remove `paramiko` and `boto3.ec2` dependencies
5. Keep browser automation unchanged

**Deployment**:
```bash
# Build and push image
docker build -t wp-k8s-service kubernetes/wp-k8s-service/
docker tag wp-k8s-service:latest 044514005641.dkr.ecr.us-east-1.amazonaws.com/wp-k8s-service:latest
docker push 044514005641.dkr.ecr.us-east-1.amazonaws.com/wp-k8s-service:latest

# Deploy to Kubernetes
kubectl apply -k kubernetes/wp-k8s-service/overlays/staging/
```

### Phase 2: KRO ResourceGroups

**Goal**: Define WordPress clone as a declarative resource

**Files to Create**:
```
kubernetes/kro-resources/
├── wordpress-clone-resourcegroup.yaml
└── examples/
    └── clone-example.yaml
```

**ResourceGroup Structure**:
```yaml
apiVersion: kro.run/v1alpha1
kind: ResourceGroup
metadata:
  name: wordpress-clone
spec:
  resources:
    - id: db-secret
      template:
        apiVersion: v1
        kind: Secret
        metadata:
          name: "{{ .spec.cloneName }}-db-secret"

    - id: db-instance
      template:
        apiVersion: rds.services.k8s.aws/v1alpha1
        kind: DBInstance
        spec:
          dbInstanceIdentifier: "{{ .spec.cloneName }}"
          # ... RDS config

    - id: wordpress-deployment
      template:
        apiVersion: apps/v1
        kind: Deployment
        spec:
          replicas: 1
          template:
            spec:
              containers:
              - name: wordpress
                image: 044514005641.dkr.ecr.us-east-1.amazonaws.com/wordpress-target:latest
                env:
                - name: WORDPRESS_DB_HOST
                  value: "{{ .resources.dbInstance.status.endpoint.address }}"

    - id: wordpress-service
      template:
        apiVersion: v1
        kind: Service
        # ...

    - id: wordpress-ingress
      template:
        apiVersion: networking.k8s.io/v1
        kind: Ingress
        # ...
```

**Usage**:
```python
# k8s_provisioner.py
def provision_target(customer_id, ttl_minutes):
    clone_resource = {
        "apiVersion": "kro.run/v1alpha1",
        "kind": "WordPressClone",
        "metadata": {"name": customer_id},
        "spec": {
            "cloneName": customer_id,
            "ttlMinutes": ttl_minutes,
            "adminPassword": generate_password(),
            "dbPassword": generate_password()
        }
    }

    api = client.CustomObjectsApi()
    api.create_namespaced_custom_object(
        group="kro.run",
        version="v1alpha1",
        namespace="wordpress-staging",
        plural="wordpressclones",
        body=clone_resource
    )
```

### Phase 3: TTL Cleanup

**Option A: Kubernetes CronJob** (recommended for simplicity)

Create per-clone CronJob that runs once at TTL expiration:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: cleanup-clone-20260206-120000
spec:
  schedule: "0 13 6 2 *"  # 2026-02-06 13:00 (TTL expiration)
  successfulJobsHistoryLimit: 0
  failedJobsHistoryLimit: 1
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: clone-cleanup-sa
          containers:
          - name: kubectl
            image: bitnami/kubectl:latest
            command:
            - /bin/sh
            - -c
            - |
              kubectl delete wordpressclone clone-20260206-120000 -n wordpress-staging
              kubectl delete cronjob cleanup-clone-20260206-120000 -n wordpress-staging
          restartPolicy: OnFailure
```

**Option B: Custom TTL Controller** (more complex, better UX)

Watch for WordPressClone resources with TTL, delete when expired.

**Option C: Native Kubernetes TTL** (future, requires alpha feature gate)

Kubernetes supports TTL on Jobs, but not yet on custom resources.

### Phase 4: RDS Integration

**ACK DBInstance Creation**:

```python
# k8s_provisioner.py
def create_database(customer_id, db_password):
    db_instance = {
        "apiVersion": "rds.services.k8s.aws/v1alpha1",
        "kind": "DBInstance",
        "metadata": {
            "name": f"clone-{customer_id}",
            "namespace": "wordpress-staging"
        },
        "spec": {
            "dbInstanceIdentifier": f"clone-{customer_id}",
            "dbInstanceClass": "db.t3.micro",
            "engine": "mysql",
            "engineVersion": "8.0",
            "masterUsername": "admin",
            "masterUserPassword": {
                "name": f"db-secret-{customer_id}",
                "key": "password"
            },
            "allocatedStorage": 20,
            "multiAZ": False,
            "publiclyAccessible": False,
            "vpcSecurityGroupIDs": ["sg-0ebe7a63f2033888d"],
            "dbSubnetGroupName": "wp-clone-restore-rds-subnet-group"
        }
    }

    api = client.CustomObjectsApi()
    api.create_namespaced_custom_object(
        group="rds.services.k8s.aws",
        version="v1alpha1",
        namespace="wordpress-staging",
        plural="dbinstances",
        body=db_instance
    )

    # Wait for DBInstance to be ready
    while True:
        db = api.get_namespaced_custom_object(
            group="rds.services.k8s.aws",
            version="v1alpha1",
            namespace="wordpress-staging",
            plural="dbinstances",
            name=f"clone-{customer_id}"
        )

        if db.get("status", {}).get("status") == "available":
            endpoint = db["status"]["endpoint"]["address"]
            return endpoint

        time.sleep(10)
```

**Issue**: RDS provisioning is slow (5-10 minutes per instance)

**Solutions**:
1. **Pre-warm Database Pool**: Create RDS instances in advance, assign to clones on-demand
2. **Shared RDS Instance**: Use single RDS with multiple databases (like current MySQL container)
3. **Aurora Serverless v2**: Auto-scaling, faster provisioning

---

## Critical Design Decisions

### Decision 1: WordPress Clone Provisioning Method

**Option A: KRO ResourceGroup** (Recommended)
- ✅ Declarative single resource
- ✅ Handles dependencies automatically
- ✅ Easy to extend/modify
- ❌ Requires KRO installation
- ❌ Less familiar to operators

**Option B: Manual Kubernetes Resources**
- ✅ Standard Kubernetes primitives
- ✅ No additional dependencies
- ❌ More code to maintain
- ❌ Manual dependency management

**Decision C: Helm Chart**
- ✅ Templating + versioning
- ✅ Industry standard
- ❌ More complex than KRO
- ❌ Requires Helm installation

**Recommendation**: Start with **Option A (KRO)** since it's already deployed and aligns with Kubernetes migration goals.

### Decision 2: Database Strategy

**Option A: Shared RDS Instance** (Recommended for MVP)
- ✅ Fast provisioning (instant)
- ✅ Cost-effective ($30/month for db.t3.small)
- ✅ Similar to current MySQL container
- ❌ Not true multi-tenancy
- ❌ Need to create databases via SQL

**Option B: RDS Per Clone**
- ✅ True isolation
- ✅ ACK native
- ❌ Very slow (5-10 min provisioning)
- ❌ Expensive ($15/clone/month)
- ❌ AWS RDS limits (40 instances per region)

**Option C: Aurora Serverless v2**
- ✅ Fast auto-scaling
- ✅ Pay-per-use
- ❌ More expensive than RDS
- ❌ Complex ACK setup

**Recommendation**: **Option A (Shared RDS)** for MVP, same as current architecture but managed by AWS.

### Decision 3: Storage for Uploads

**Option A: EmptyDir Volumes** (Recommended for ephemeral clones)
- ✅ Simple, no extra config
- ✅ Fast local storage
- ✅ Ephemeral nature fits clone use-case
- ❌ Lost on pod restart
- ❌ Not shared across replicas

**Option B: S3 + Persistent Volumes**
- ✅ Durable storage
- ✅ Shared across replicas
- ❌ More complex
- ❌ Additional cost
- ❌ Slower than local

**Recommendation**: **Option A (EmptyDir)** since clones are ephemeral and have TTL.

### Decision 4: Ingress Strategy

**Option A: Ingress Per Clone** (Recommended)
- ✅ Explicit path routing
- ✅ Easy to manage per-clone
- ✅ Maps 1:1 to current ALB rules
- ❌ More Ingress resources

**Option B: Single Ingress with Multiple Paths**
- ✅ Single resource
- ❌ Hard to manage dynamically
- ❌ All-or-nothing updates

**Recommendation**: **Option A (Ingress Per Clone)** for flexibility and isolation.

---

## Migration Roadmap

### Phase 1: Infrastructure (IN PROGRESS)

✅ **Task 1.1**: Deploy EKS cluster (Kubernetes 1.35) - **DONE**
✅ **Task 1.1**: Install Karpenter (v1.8.6) - **DONE**
✅ **Task 1.1**: Install KEDA - **DONE**
⏳ **Task 1.2**: Install ACK RDS Controller - **TODO**
⏳ **Task 1.3**: Install KRO - **TODO**
⏳ **Task 1.4**: Install Argo CD - **TODO**
⏳ **Task 1.6**: Install AWS Load Balancer Controller - **TODO**

### Phase 2: Core Service

⏳ **Task 2.1**: Create `k8s_provisioner.py` (replace EC2 provisioner)
⏳ **Task 2.2**: Create Kubernetes manifests for wp-k8s-service
⏳ **Task 2.3**: Build and push Docker image to ECR
⏳ **Task 2.4**: Deploy wp-k8s-service to Kubernetes
⏳ **Task 2.5**: Test /health endpoint via Ingress

### Phase 3: WordPress Clone Resources

⏳ **Task 3.1**: Create KRO ResourceGroup for WordPress clones
⏳ **Task 3.2**: Create RDS database (shared or per-clone)
⏳ **Task 3.3**: Create WordPress Deployment template
⏳ **Task 3.4**: Create Service and Ingress templates
⏳ **Task 3.5**: Test manual clone creation via kubectl

### Phase 4: Dynamic Provisioning

⏳ **Task 4.1**: Implement `k8s_provisioner.provision_target()`
⏳ **Task 4.2**: Implement TTL cleanup (CronJob or controller)
⏳ **Task 4.3**: Test /clone endpoint end-to-end
⏳ **Task 4.4**: Test /restore endpoint end-to-end

### Phase 5: Observability & GitOps

⏳ **Task 5.1**: Deploy Fluent Bit for log aggregation
⏳ **Task 5.2**: Create Grafana dashboards for Kubernetes metrics
⏳ **Task 5.3**: Configure Argo CD for GitOps deployments
⏳ **Task 5.4**: Create CI/CD pipeline (GitHub Actions)

### Phase 6: Production Cutover

⏳ **Task 6.1**: Parallel testing (EC2 vs Kubernetes)
⏳ **Task 6.2**: Migrate DNS to Kubernetes Ingress
⏳ **Task 6.3**: Decommission EC2 infrastructure
⏳ **Task 6.4**: Update documentation

---

## Code Examples

### Example 1: Create Clone via Kubernetes API

```python
# k8s_provisioner.py
from kubernetes import client, config
from datetime import datetime, timedelta

class K8sProvisioner:
    def __init__(self):
        config.load_incluster_config()  # Or load_kube_config() for local
        self.api = client.CustomObjectsApi()
        self.core_api = client.CoreV1Api()
        self.networking_api = client.NetworkingV1Api()

    def provision_target(self, customer_id: str, ttl_minutes: int) -> dict:
        """Provision WordPress clone on Kubernetes"""

        # Generate credentials
        wp_password = self._generate_password()
        db_password = self._generate_password()

        # Create Secret
        secret = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {
                "name": f"{customer_id}-secret",
                "namespace": "wordpress-staging"
            },
            "stringData": {
                "wp-admin-password": wp_password,
                "db-password": db_password
            }
        }
        self.core_api.create_namespaced_secret("wordpress-staging", secret)

        # Create WordPressClone resource (KRO ResourceGroup)
        clone = {
            "apiVersion": "kro.run/v1alpha1",
            "kind": "WordPressClone",
            "metadata": {
                "name": customer_id,
                "namespace": "wordpress-staging"
            },
            "spec": {
                "cloneName": customer_id,
                "ttlMinutes": ttl_minutes,
                "secretName": f"{customer_id}-secret",
                "ingressPath": f"/{customer_id}"
            }
        }

        self.api.create_namespaced_custom_object(
            group="kro.run",
            version="v1alpha1",
            namespace="wordpress-staging",
            plural="wordpressclones",
            body=clone
        )

        # Wait for Ingress to get ALB hostname
        ingress_name = f"{customer_id}-ingress"
        for _ in range(60):  # 5 minutes max
            try:
                ingress = self.networking_api.read_namespaced_ingress(
                    ingress_name, "wordpress-staging"
                )
                if ingress.status.load_balancer.ingress:
                    alb_hostname = ingress.status.load_balancer.ingress[0].hostname
                    target_url = f"http://{alb_hostname}/{customer_id}"

                    # Schedule cleanup
                    self._schedule_cleanup(customer_id, ttl_minutes)

                    return {
                        "success": True,
                        "target_url": target_url,
                        "wordpress_username": "admin",
                        "wordpress_password": wp_password,
                        "api_key": "migration-master-key",
                        "expires_at": (datetime.utcnow() + timedelta(minutes=ttl_minutes)).isoformat() + "Z"
                    }
            except:
                pass
            time.sleep(5)

        raise Exception("Timeout waiting for Ingress")

    def _schedule_cleanup(self, customer_id: str, ttl_minutes: int):
        """Create CronJob for TTL-based cleanup"""
        expiration = datetime.utcnow() + timedelta(minutes=ttl_minutes)
        cron_schedule = f"{expiration.minute} {expiration.hour} {expiration.day} {expiration.month} *"

        cronjob = {
            "apiVersion": "batch/v1",
            "kind": "CronJob",
            "metadata": {
                "name": f"cleanup-{customer_id}",
                "namespace": "wordpress-staging"
            },
            "spec": {
                "schedule": cron_schedule,
                "successfulJobsHistoryLimit": 0,
                "jobTemplate": {
                    "spec": {
                        "template": {
                            "spec": {
                                "serviceAccountName": "clone-cleanup-sa",
                                "containers": [{
                                    "name": "kubectl",
                                    "image": "bitnami/kubectl:latest",
                                    "command": ["/bin/sh", "-c",
                                        f"kubectl delete wordpressclone {customer_id} -n wordpress-staging && "
                                        f"kubectl delete cronjob cleanup-{customer_id} -n wordpress-staging"]
                                }],
                                "restartPolicy": "OnFailure"
                            }
                        }
                    }
                }
            }
        }

        batch_api = client.BatchV1Api()
        batch_api.create_namespaced_cron_job("wordpress-staging", cronjob)
```

### Example 2: KRO ResourceGroup Definition

```yaml
# kubernetes/kro-resources/wordpress-clone-resourcegroup.yaml
apiVersion: kro.run/v1alpha1
kind: ResourceGroup
metadata:
  name: wordpress-clone
spec:
  schema:
    apiVersion: v1alpha1
    kind: WordPressClone
    spec:
      cloneName: string
      ttlMinutes: integer
      secretName: string
      ingressPath: string

  resources:
    # Secret already created by provisioner

    # ConfigMap for WordPress configuration
    - id: wp-config
      template:
        apiVersion: v1
        kind: ConfigMap
        metadata:
          name: "{{ .spec.cloneName }}-config"
          namespace: wordpress-staging
        data:
          WP_SITE_URL: "http://{{ .status.ingressHostname }}{{ .spec.ingressPath }}"
          DB_HOST: "wp-clone-restore-rds.abcdef.us-east-1.rds.amazonaws.com"
          DB_NAME: "wp_{{ .spec.cloneName | replace \"-\" \"_\" }}"

    # Deployment for WordPress
    - id: wordpress-deployment
      template:
        apiVersion: apps/v1
        kind: Deployment
        metadata:
          name: "{{ .spec.cloneName }}"
          namespace: wordpress-staging
          labels:
            app: wordpress-clone
            clone: "{{ .spec.cloneName }}"
        spec:
          replicas: 1
          selector:
            matchLabels:
              clone: "{{ .spec.cloneName }}"
          template:
            metadata:
              labels:
                clone: "{{ .spec.cloneName }}"
            spec:
              containers:
              - name: wordpress
                image: 044514005641.dkr.ecr.us-east-1.amazonaws.com/wordpress-target:latest
                ports:
                - containerPort: 80
                env:
                - name: WORDPRESS_DB_HOST
                  valueFrom:
                    configMapKeyRef:
                      name: "{{ .spec.cloneName }}-config"
                      key: DB_HOST
                - name: WORDPRESS_DB_NAME
                  valueFrom:
                    configMapKeyRef:
                      name: "{{ .spec.cloneName }}-config"
                      key: DB_NAME
                - name: WORDPRESS_DB_USER
                  value: "wp_{{ .spec.cloneName | replace \"-\" \"_\" }}"
                - name: WORDPRESS_DB_PASSWORD
                  valueFrom:
                    secretKeyRef:
                      name: "{{ .spec.secretName }}"
                      key: db-password
                - name: WP_ADMIN_USER
                  value: admin
                - name: WP_ADMIN_PASSWORD
                  valueFrom:
                    secretKeyRef:
                      name: "{{ .spec.secretName }}"
                      key: wp-admin-password
                - name: WP_SITE_URL
                  valueFrom:
                    configMapKeyRef:
                      name: "{{ .spec.cloneName }}-config"
                      key: WP_SITE_URL
                volumeMounts:
                - name: wp-content
                  mountPath: /var/www/html/wp-content
              volumes:
              - name: wp-content
                emptyDir: {}

    # Service
    - id: wordpress-service
      template:
        apiVersion: v1
        kind: Service
        metadata:
          name: "{{ .spec.cloneName }}"
          namespace: wordpress-staging
        spec:
          type: ClusterIP
          selector:
            clone: "{{ .spec.cloneName }}"
          ports:
          - port: 80
            targetPort: 80

    # Ingress
    - id: wordpress-ingress
      template:
        apiVersion: networking.k8s.io/v1
        kind: Ingress
        metadata:
          name: "{{ .spec.cloneName }}-ingress"
          namespace: wordpress-staging
          annotations:
            alb.ingress.kubernetes.io/scheme: internet-facing
            alb.ingress.kubernetes.io/target-type: ip
            alb.ingress.kubernetes.io/healthcheck-path: /
        spec:
          ingressClassName: alb
          rules:
          - http:
              paths:
              - path: "{{ .spec.ingressPath }}"
                pathType: Prefix
                backend:
                  service:
                    name: "{{ .spec.cloneName }}"
                    port:
                      number: 80
```

---

## Conclusion

The migration from `feat/restore` to Kubernetes involves:

1. **Replacing SSH-based operations** with Kubernetes API calls
2. **Converting imperative Docker commands** to declarative YAML resources
3. **Leveraging KRO** for simplified resource management
4. **Using managed services** (RDS instead of MySQL container)
5. **Adopting cloud-native patterns** (Ingress, Services, ConfigMaps)

**Key Takeaway**: The core business logic (browser automation, export/import, WordPress plugin) remains unchanged. Only the infrastructure provisioning layer changes from EC2+Docker to Kubernetes.

---

**Document Version**: 1.0
**Author**: Claude
**Generated**: 2026-02-06
