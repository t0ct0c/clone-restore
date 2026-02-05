# Spec: GitOps CI/CD with Argo CD

## Overview
Implement GitOps workflow using Argo CD for automatic deployments from Git, with separate staging and production environments.

## ADDED Requirements

### REQ-GITOPS-001: Argo CD Installation
**Priority**: High
**Category**: CI/CD Infrastructure

The system MUST install Argo CD in the EKS cluster for GitOps deployments.

#### Scenario: Argo CD is deployed via Helm
**Given** EKS cluster is running
**When** `helm install argocd` is executed
**Then** Argo CD server is running in argocd namespace
**And** Argo CD UI is accessible via LoadBalancer or Ingress
**And** Argo CD CLI can authenticate to cluster

### REQ-GITOPS-002: Argo CD Applications for Staging
**Priority**: High
**Category**: Environment Management

The system MUST create Argo CD Application that deploys staging environment from `staging` Git branch.

#### Scenario: Staging application auto-syncs from staging branch
**Given** Argo CD Application `wp-k8s-staging` is created
**When** code is pushed to `staging` branch
**Then** Argo CD detects Git changes
**And** Argo CD applies Kubernetes manifests from `kubernetes/manifests/overlays/staging`
**And** Deployment is updated in `wordpress-staging` namespace
**And** new pods are rolled out automatically

#### Scenario: Staging uses reduced replica count
**Given** Kustomize overlay for staging is configured
**When** staging Deployment is applied
**Then** wp-k8s-service has 1-3 replicas (vs 2-10 for production)
**And** HPA scales between 1-3 replicas based on load

### REQ-GITOPS-003: Argo CD Applications for Production
**Priority**: Critical
**Category**: Environment Management

The system MUST create Argo CD Application that deploys production environment from `main` Git branch.

#### Scenario: Production application auto-syncs from main branch
**Given** Argo CD Application `wp-k8s-production` is created
**When** code is merged to `main` branch
**Then** Argo CD detects Git changes
**And** Argo CD applies Kubernetes manifests from `kubernetes/manifests/overlays/production`
**And** Deployment is updated in `wordpress-production` namespace
**And** rolling update strategy ensures zero-downtime

#### Scenario: Production uses higher replica count
**Given** Kustomize overlay for production is configured
**When** production Deployment is applied
**Then** wp-k8s-service has 2-10 replicas
**And** HPA scales between 2-10 replicas based on load

### REQ-GITOPS-004: Kustomize Overlays
**Priority**: High
**Category**: Configuration Management

The system MUST use Kustomize to manage environment-specific configurations.

#### Scenario: Base manifests shared across environments
**Given** base manifests exist in `kubernetes/manifests/base/`
**When** Kustomize builds overlay
**Then** Deployment, Service, Ingress are inherited from base
**And** environment-specific patches are applied

#### Scenario: Staging overlay reduces resources
**Given** staging overlay exists
**When** Kustomize builds staging manifests
**Then** Deployment replica count is patched to 1
**And** resource requests are reduced (cpu: 250m, memory: 512Mi)
**And** namespace is patched to `wordpress-staging`

#### Scenario: Production overlay increases resources
**Given** production overlay exists
**When** Kustomize builds production manifests
**Then** Deployment replica count is patched to 2
**And** resource requests are higher (cpu: 500m, memory: 1Gi)
**And** namespace is patched to `wordpress-production`

### REQ-GITOPS-005: GitHub Actions for Docker Image Builds
**Priority**: High
**Category**: CI Pipeline

The system MUST use GitHub Actions to build and push Docker images to ECR on code changes.

#### Scenario: Code push triggers image build
**Given** code is pushed to `main` or `staging` branch
**And** files in `kubernetes/wp-k8s-service/` are modified
**When** GitHub Actions workflow runs
**Then** Docker image is built from `kubernetes/wp-k8s-service/Dockerfile`
**And** image is tagged with Git commit SHA
**And** image is pushed to ECR repository `wp-k8s-service`
**And** `latest` tag is updated

#### Scenario: Image tag is updated in Kustomize
**Given** new Docker image is pushed to ECR
**When** GitHub Actions workflow updates manifests
**Then** Kustomize overlay's image tag is set to commit SHA
**And** updated manifest is committed to Git
**And** Argo CD detects Git change and deploys new image

### REQ-GITOPS-006: Automatic Rollback
**Priority**: High
**Category**: Reliability

The system MUST support rollback to previous Git commit for quick recovery from bad deployments.

#### Scenario: Rollback via Git revert
**Given** bad deployment is pushed to main branch
**When** `git revert <commit>` is executed and pushed
**Then** Argo CD detects revert commit
**And** Argo CD applies previous manifests
**And** Deployment rolls back to previous image version

#### Scenario: Manual rollback via Argo CD UI
**Given** bad deployment is detected
**When** user clicks "Rollback" in Argo CD UI
**Then** Argo CD reverts to previous sync revision
**And** Deployment is updated with previous manifests

### REQ-GITOPS-007: Sync Policies
**Priority**: Medium
**Category**: Deployment Strategy

The system MUST configure Argo CD sync policies for automatic deployment and pruning.

#### Scenario: Automatic sync enabled for both environments
**Given** Argo CD Application has `syncPolicy.automated.prune: true`
**When** Git manifests are updated
**Then** Argo CD automatically applies changes without manual approval
**And** deleted resources are automatically removed from cluster

#### Scenario: Self-heal corrects manual changes
**Given** Argo CD Application has `syncPolicy.automated.selfHeal: true`
**When** user manually modifies Deployment via kubectl
**Then** Argo CD detects drift from Git
**And** Argo CD reverts manual changes to match Git state

---

## Integration Points

### Related Capabilities
- `kubernetes-infrastructure`: Provides EKS cluster where Argo CD runs
- `kro-orchestration`: ResourceGroup definitions deployed via Argo CD

### Modified Components
- **NEW**: `/kubernetes/argocd/applications/wp-k8s-staging.yaml` - Staging Application
- **NEW**: `/kubernetes/argocd/applications/wp-k8s-production.yaml` - Production Application
- **NEW**: `/kubernetes/manifests/base/` - Base Kubernetes manifests
- **NEW**: `/kubernetes/manifests/overlays/staging/` - Staging Kustomize overlay
- **NEW**: `/kubernetes/manifests/overlays/production/` - Production Kustomize overlay
- **NEW**: `/.github/workflows/build-wp-k8s-service.yaml` - GitHub Actions workflow

---

## Non-Functional Requirements

### Performance
- Argo CD sync latency < 2 minutes from Git push
- Docker image build time < 3 minutes
- Rolling update completes within 5 minutes (zero downtime)

### Reliability
- Argo CD retries failed syncs with exponential backoff
- Health checks ensure pods are ready before marking sync complete
- Rolling update strategy ensures minimum replicas available during deployment

### Security
- Argo CD uses Git SSH key for private repository access
- GitHub Actions uses AWS credentials stored as GitHub Secrets
- ECR image pull requires IRSA authentication (no hardcoded credentials)

### Auditability
- All deployments tracked in Git history
- Argo CD UI shows deployment timeline and status
- Git commits include deployment metadata (image SHA, timestamp, author)
