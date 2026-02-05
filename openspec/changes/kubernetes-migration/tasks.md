# Tasks: Kubernetes Migration

## Phase 1: Bootstrap EKS Cluster + KRO + ACK + Argo CD (Week 1)

### Task 1.1: Create EKS Cluster with Terraform
**Estimate**: 1 day
**Priority**: Critical
**Dependencies**: None

**Steps**:
- [ ] Create `/kubernetes/bootstrap/terraform/main.tf` - EKS cluster definition
- [ ] Create `/kubernetes/bootstrap/terraform/vpc.tf` - VPC with public/private subnets
- [ ] Create `/kubernetes/bootstrap/terraform/iam.tf` - IRSA roles for ACK and wp-k8s-service
- [ ] Run `terraform init && terraform plan`
- [ ] Run `terraform apply` to provision EKS cluster
- [ ] Verify cluster access: `kubectl get nodes`
- [ ] Create namespaces: `wordpress-staging`, `wordpress-production`

**Acceptance Criteria**:
- EKS cluster running with 2 worker nodes (t3.large)
- Control plane accessible via kubectl
- Namespaces created with ResourceQuotas applied

---

### Task 1.2: Install ACK Controllers
**Estimate**: 0.5 days
**Priority**: Critical
**Dependencies**: Task 1.1

**Steps**:
- [ ] Create `/kubernetes/bootstrap/terraform/ack-controllers.tf`
- [ ] Install ACK RDS controller via Helm
- [ ] Install ACK IAM controller via Helm
- [ ] Verify CRDs registered: `kubectl get crds | grep rds`
- [ ] Verify controller pods running: `kubectl get pods -n ack-system`
- [ ] Test IRSA roles: Check controller logs for AWS API calls

**Acceptance Criteria**:
- ACK RDS controller running in ack-system namespace
- DBInstance, DBSubnetGroup CRDs available
- Controller has IRSA role with RDS permissions

---

### Task 1.3: Install KRO
**Estimate**: 0.5 days
**Priority**: Critical
**Dependencies**: Task 1.1

**Steps**:
- [ ] Create `/kubernetes/bootstrap/scripts/install-kro.sh`
- [ ] Download KRO CLI: `curl -L https://github.com/kubernetes-sigs/kro/releases/latest/download/kro-linux-amd64 -o kro`
- [ ] Install KRO operator: `kro install`
- [ ] Verify KRO controller running: `kubectl get pods -n kro-system`
- [ ] Verify ResourceGroup CRD: `kubectl get crds | grep resourcegroup`

**Acceptance Criteria**:
- KRO controller running in kro-system namespace
- ResourceGroup CRD available
- KRO CLI functional

---

### Task 1.4: Install Argo CD
**Estimate**: 0.5 days
**Priority**: High
**Dependencies**: Task 1.1

**Steps**:
- [ ] Create `/kubernetes/bootstrap/terraform/argocd.tf`
- [ ] Install Argo CD via Helm
- [ ] Expose Argo CD UI via LoadBalancer or Ingress
- [ ] Retrieve admin password: `kubectl get secret argocd-initial-admin-secret -n argocd`
- [ ] Login to Argo CD UI and CLI
- [ ] Configure Git repository access (SSH key)

**Acceptance Criteria**:
- Argo CD UI accessible
- Argo CD CLI authenticated
- Git repository connected

---

### Task 1.5: Install Cluster Autoscaler
**Estimate**: 0.5 days
**Priority**: High
**Dependencies**: Task 1.1

**Steps**:
- [ ] Add Cluster Autoscaler to `/kubernetes/bootstrap/terraform/addons.tf`
- [ ] Install Cluster Autoscaler via Helm
- [ ] Configure autoscaler to watch EKS node groups
- [ ] Set min nodes: 2, max nodes: 20
- [ ] Verify autoscaler pod running: `kubectl get pods -n kube-system`

**Acceptance Criteria**:
- Cluster Autoscaler running
- Node auto-scaling functional (test by creating pending pods)

---

### Task 1.6: Install AWS Load Balancer Controller
**Estimate**: 0.5 days
**Priority**: Critical
**Dependencies**: Task 1.1

**Steps**:
- [ ] Add AWS Load Balancer Controller to `/kubernetes/bootstrap/terraform/addons.tf`
- [ ] Install via Helm
- [ ] Configure IRSA role for controller
- [ ] Verify controller running: `kubectl get pods -n kube-system`
- [ ] Test by creating sample Ingress resource

**Acceptance Criteria**:
- AWS Load Balancer Controller running
- Can create ALB via Ingress resource

---

## Phase 2: Deploy KRO ResourceGroups & RDS Setup (Week 1-2)

### Task 2.1: Create RDS Prerequisites
**Estimate**: 0.5 days
**Priority**: Critical
**Dependencies**: Task 1.2

**Steps**:
- [ ] Create `/kubernetes/bootstrap/terraform/rds-prerequisites.tf`
- [ ] Create RDS subnet group for private subnets
- [ ] Create security group allowing MySQL access from EKS worker nodes
- [ ] Apply with Terraform
- [ ] Verify subnet group exists in AWS console

**Acceptance Criteria**:
- RDS subnet group spans 3 AZs
- Security group allows TCP 3306 from EKS worker SG

---

### Task 2.2: Create WordPress Clone ResourceGroup
**Estimate**: 2 days
**Priority**: Critical
**Dependencies**: Task 1.3, Task 2.1

**Steps**:
- [ ] Create `/kubernetes/kro/resourcegroups/wordpress-clone.yaml`
- [ ] Define schema: sourceUrl, cloneId, ttlSeconds, useDedicatedDatabase
- [ ] Define resources: Secret, DBInstance, Job, Service, Ingress
- [ ] Define statusCollectors for cloneUrl, credentials
- [ ] Apply ResourceGroup: `kubectl apply -f wordpress-clone.yaml`
- [ ] Verify ResourceGroup registered: `kubectl get resourcegroup`

**Acceptance Criteria**:
- ResourceGroup deployed successfully
- WordPressClone CRD available
- Schema validation works

---

### Task 2.3: Test Manual WordPressClone Creation
**Estimate**: 1 day
**Priority**: High
**Dependencies**: Task 2.2

**Steps**:
- [ ] Create test WordPressClone: `/kubernetes/kro/instances/staging/test-clone.yaml`
- [ ] Apply resource: `kubectl apply -f test-clone.yaml -n wordpress-staging`
- [ ] Watch resource creation: `kubectl get wordpressclone -w`
- [ ] Verify Secret created
- [ ] Verify RDS provisioning (if useDedicatedDatabase: true)
- [ ] Verify Job pod running
- [ ] Verify Service created
- [ ] Verify Ingress created and ALB updated
- [ ] Access clone URL in browser

**Acceptance Criteria**:
- WordPressClone provisions all resources
- Clone accessible via ALB URL
- Status fields populated correctly

---

### Task 2.4: Test TTL Cleanup
**Estimate**: 0.5 days
**Priority**: Medium
**Dependencies**: Task 2.3

**Steps**:
- [ ] Create WordPressClone with `ttlSeconds: 300` (5 minutes)
- [ ] Wait for TTL to expire
- [ ] Verify Job deleted by Kubernetes TTL controller
- [ ] Verify KRO deletes child resources (Service, Ingress, Secret, RDS)
- [ ] Verify ALB listener rule removed

**Acceptance Criteria**:
- Resources cleaned up automatically after TTL
- No orphaned resources remain

---

### Task 2.5: Create Shared RDS for Staging
**Estimate**: 0.5 days
**Priority**: High
**Dependencies**: Task 2.1

**Steps**:
- [ ] Create `/kubernetes/manifests/base/mysql/shared-rds-staging.yaml`
- [ ] Define DBInstance: `wordpress-staging-shared-rds`
- [ ] Instance type: db.t3.small
- [ ] Apply resource: `kubectl apply -f shared-rds-staging.yaml`
- [ ] Wait for RDS to be available
- [ ] Store endpoint in ConfigMap for staging clones

**Acceptance Criteria**:
- Shared RDS available for staging namespace
- Endpoint accessible from staging pods

---

## Phase 3: Create NEW wp-k8s-service (Week 2-3)

### Task 3.1: Create KRO Provisioner
**Estimate**: 2 days
**Priority**: Critical
**Dependencies**: Task 2.2

**Steps**:
- [ ] Create `/kubernetes/wp-k8s-service/app/kro_provisioner.py`
- [ ] Implement `KROProvisioner` class
- [ ] Implement `create_clone()` method - creates WordPressClone resource
- [ ] Implement `_wait_for_clone_ready()` method - polls status
- [ ] Implement `delete_clone()` method
- [ ] Add Kubernetes Python client to requirements.txt
- [ ] Unit tests for provisioner

**Acceptance Criteria**:
- Provisioner can create WordPressClone via K8s API
- Provisioner waits for status to be ready
- Provisioner returns clone URL and credentials

---

### Task 3.2: Create FastAPI Service
**Estimate**: 2 days
**Priority**: Critical
**Dependencies**: Task 3.1

**Steps**:
- [ ] Copy `/wp-setup-service/app/main.py` to `/kubernetes/wp-k8s-service/app/main.py`
- [ ] Replace `ec2_provisioner` imports with `kro_provisioner`
- [ ] Update `/clone` endpoint to use `KROProvisioner.create_clone()`
- [ ] Keep `/restore` endpoint unchanged (browser automation still needed)
- [ ] Update `/health` endpoint
- [ ] Test locally with kind cluster

**Acceptance Criteria**:
- `/clone` endpoint creates WordPressClone resource
- `/restore` endpoint still functional
- Service runs in Kubernetes pod

---

### Task 3.3: Create Dockerfile
**Estimate**: 0.5 days
**Priority**: High
**Dependencies**: Task 3.2

**Steps**:
- [ ] Create `/kubernetes/wp-k8s-service/Dockerfile`
- [ ] Base image: `python:3.11-slim`
- [ ] Install dependencies: `playwright`, `camoufox`, `fastapi`, `kubernetes`
- [ ] Copy app code
- [ ] Build image locally: `docker build -t wp-k8s-service:test .`
- [ ] Test image: `docker run -p 8000:8000 wp-k8s-service:test`

**Acceptance Criteria**:
- Docker image builds successfully
- Service runs in container
- Browser automation (Camoufox) works in container

---

### Task 3.4: Push Image to ECR
**Estimate**: 0.5 days
**Priority**: High
**Dependencies**: Task 3.3

**Steps**:
- [ ] Authenticate to ECR: `aws ecr get-login-password | docker login`
- [ ] Tag image: `docker tag wp-k8s-service:test 044514005641.dkr.ecr.us-east-1.amazonaws.com/wp-k8s-service:latest`
- [ ] Push image: `docker push ...`
- [ ] Verify image in ECR console

**Acceptance Criteria**:
- Image available in ECR repository
- Image pullable from EKS cluster

---

### Task 3.5: Create Kubernetes Manifests
**Estimate**: 1 day
**Priority**: High
**Dependencies**: Task 3.4

**Steps**:
- [ ] Create `/kubernetes/manifests/base/wp-k8s-service/deployment.yaml`
- [ ] Create `/kubernetes/manifests/base/wp-k8s-service/service.yaml` (ClusterIP)
- [ ] Create `/kubernetes/manifests/base/wp-k8s-service/ingress.yaml` (ALB)
- [ ] Create `/kubernetes/manifests/base/wp-k8s-service/hpa.yaml` (Horizontal Pod Autoscaler)
- [ ] Create `/kubernetes/manifests/base/wp-k8s-service/serviceaccount.yaml` (with IRSA annotation)
- [ ] Apply to staging namespace: `kubectl apply -k kubernetes/manifests/overlays/staging`

**Acceptance Criteria**:
- Deployment creates pods successfully
- Service routes traffic to pods
- Ingress creates ALB
- HPA scales pods based on CPU

---

### Task 3.6: Test End-to-End Clone Creation
**Estimate**: 1 day
**Priority**: Critical
**Dependencies**: Task 3.5

**Steps**:
- [ ] Get ALB URL from Ingress: `kubectl get ingress -n wordpress-staging`
- [ ] Send POST request to `/clone` endpoint
- [ ] Verify WordPressClone resource created
- [ ] Verify clone resources provisioned (Secret, Job, Service, Ingress)
- [ ] Access clone URL
- [ ] Test browser automation (upload plugin, activate, get API key)
- [ ] Test REST API endpoints

**Acceptance Criteria**:
- `/clone` endpoint creates functional WordPress clone
- Clone accessible via ALB
- REST API works
- Browser automation succeeds

---

## Phase 4: GitOps CI/CD with Argo CD (Week 3)

### Task 4.1: Create Kustomize Overlays
**Estimate**: 1 day
**Priority**: High
**Dependencies**: Task 3.5

**Steps**:
- [ ] Create `/kubernetes/manifests/overlays/staging/kustomization.yaml`
- [ ] Create `/kubernetes/manifests/overlays/production/kustomization.yaml`
- [ ] Staging patches: replica count = 1, resources reduced, namespace = wordpress-staging
- [ ] Production patches: replica count = 2, resources increased, namespace = wordpress-production
- [ ] Test build: `kustomize build kubernetes/manifests/overlays/staging`

**Acceptance Criteria**:
- Kustomize builds manifests for both environments
- Environment-specific values applied correctly

---

### Task 4.2: Create Argo CD Applications
**Estimate**: 0.5 days
**Priority**: High
**Dependencies**: Task 4.1

**Steps**:
- [ ] Create `/kubernetes/argocd/applications/wp-k8s-staging.yaml`
- [ ] Create `/kubernetes/argocd/applications/wp-k8s-production.yaml`
- [ ] Staging: tracks `staging` branch, deploys to `wordpress-staging` namespace
- [ ] Production: tracks `main` branch, deploys to `wordpress-production` namespace
- [ ] Apply Applications: `kubectl apply -f kubernetes/argocd/applications/`
- [ ] Verify in Argo CD UI

**Acceptance Criteria**:
- Both Applications appear in Argo CD UI
- Auto-sync enabled
- Deployments successful

---

### Task 4.3: Create GitHub Actions Workflow
**Estimate**: 1 day
**Priority**: High
**Dependencies**: Task 4.2

**Steps**:
- [ ] Create `/.github/workflows/build-wp-k8s-service.yaml`
- [ ] Trigger on push to `main` or `staging` branches
- [ ] Build Docker image with commit SHA tag
- [ ] Push to ECR
- [ ] Update Kustomize overlay with new image tag
- [ ] Commit and push updated manifests
- [ ] Test by pushing to staging branch

**Acceptance Criteria**:
- GitHub Actions workflow builds image on push
- Image pushed to ECR with commit SHA tag
- Argo CD detects manifest change and deploys

---

### Task 4.4: Test GitOps Workflow
**Estimate**: 0.5 days
**Priority**: High
**Dependencies**: Task 4.3

**Steps**:
- [ ] Make code change in `kubernetes/wp-k8s-service/`
- [ ] Push to `staging` branch
- [ ] Verify GitHub Actions builds and pushes image
- [ ] Verify Argo CD deploys to staging namespace
- [ ] Test functionality in staging
- [ ] Merge to `main` branch
- [ ] Verify Argo CD deploys to production namespace

**Acceptance Criteria**:
- Staging deployment automatic from staging branch
- Production deployment automatic from main branch
- Zero-downtime rolling updates

---

## Phase 5: Observability Migration (Week 4)

### Task 5.1: Deploy OpenTelemetry Collector
**Estimate**: 1 day
**Priority**: Medium
**Dependencies**: Task 3.6

**Steps**:
- [ ] Install OpenTelemetry Operator via Helm
- [ ] Create OpenTelemetryCollector resource
- [ ] Configure exporter for CloudWatch
- [ ] Update wp-k8s-service to use OTEL SDK
- [ ] Test metrics, logs, traces

**Acceptance Criteria**:
- OpenTelemetry Collector running
- Metrics exported to CloudWatch
- Logs exported to CloudWatch Logs
- Traces visible in CloudWatch X-Ray

---

## Phase 6: Parallel Testing & Cutover (Week 4-5)

### Task 6.1: Validation Checklist
**Estimate**: 2 days
**Priority**: Critical
**Dependencies**: Task 3.6, Task 5.1

**Steps**:
- [ ] Clone creation time < 5 minutes
- [ ] TTL cleanup functional
- [ ] Path-based routing works
- [ ] Browser automation succeeds
- [ ] Database isolation maintained
- [ ] Auto-scaling works (HPA + CA)
- [ ] GitOps workflow functional
- [ ] Observability metrics available
- [ ] Cost tracking (should be < $250/mo)

**Acceptance Criteria**:
- All validation items pass
- System ready for production cutover

---

### Task 6.2: DNS Cutover
**Estimate**: 0.5 days
**Priority**: Critical
**Dependencies**: Task 6.1

**Steps**:
- [ ] Get EKS ALB DNS name
- [ ] Update DNS record to point to EKS ALB
- [ ] Monitor traffic shift
- [ ] Verify clone creation works on EKS
- [ ] Keep EC2 system running for rollback

**Acceptance Criteria**:
- Traffic routing to EKS
- No errors in production
- EC2 available for rollback if needed

---

### Task 6.3: Monitor for 48 Hours
**Estimate**: 2 days
**Priority**: Critical
**Dependencies**: Task 6.2

**Steps**:
- [ ] Monitor CloudWatch metrics
- [ ] Monitor Argo CD for deployment issues
- [ ] Monitor clone creation success rate
- [ ] Monitor TTL cleanup
- [ ] Monitor cost (should decrease from EC2 baseline)
- [ ] Check for errors in logs

**Acceptance Criteria**:
- No critical errors for 48 hours
- System stable
- Cost under target ($250/mo)

---

### Task 6.4: Decommission EC2 Infrastructure
**Estimate**: 1 day
**Priority**: Low
**Dependencies**: Task 6.3

**Steps**:
- [ ] Verify EKS stable for 48 hours
- [ ] Backup EC2 configuration for reference
- [ ] Run `terraform destroy` for EC2 infrastructure
- [ ] Verify ALB, EC2 instances terminated
- [ ] Archive wp-setup-service code (don't delete, keep for reference)

**Acceptance Criteria**:
- EC2 infrastructure removed
- Cost reduced by ~$163/mo (EC2 baseline)
- Code preserved for rollback if needed

---

## Summary

**Total Estimated Duration**: 4-5 weeks
**Critical Path**: Task 1.1 → 2.2 → 3.1 → 3.2 → 3.6 → 6.1 → 6.2

**Key Milestones**:
- End of Week 1: EKS cluster + KRO + ACK + Argo CD ready
- End of Week 2: KRO ResourceGroups working
- End of Week 3: wp-k8s-service deployed, GitOps functional
- End of Week 4: Observability migrated, parallel testing complete
- End of Week 5: Production cutover, EC2 decommissioned
