# Change: Kubernetes Migration for WordPress Clone & Restore System

**Status**: In Progress  
**Target EKS Version**: 1.35  
**Reference Documentation**:
- [KUBERNETES_DEPLOYMENT_PLAN.md](../../KUBERNETES_DEPLOYMENT_PLAN.md) - Strategic migration plan
- [KUBERNETES_IMPLEMENTATION_GUIDE.md](../../KUBERNETES_IMPLEMENTATION_GUIDE.md) - Tactical implementation guide
- [OPERATIONAL_MEMORY.md](../../OPERATIONAL_MEMORY.md) - Current EC2 system documentation

## Why

The current EC2/Docker architecture has limitations that prevent scaling, observability, and operational excellence:

1. **Manual Infrastructure Management**: SSH-based Docker container provisioning requires manual port management, Nginx configuration, and ALB rule creation
2. **Limited Scalability**: Fixed EC2 instance capacity, no auto-scaling based on demand
3. **Deployment Complexity**: Manual Docker image deployment, no GitOps workflow, difficult rollbacks
4. **Single Point of Failure**: Clones depend on specific EC2 instances; instance failure breaks all clones on that host
5. **Operational Overhead**: 905 lines of provisioning code in `ec2_provisioner.py` for managing SSH, Docker, Nginx, MySQL, and ALB

**Business Impact:**
- Cannot handle traffic spikes (clone creation demand exceeds EC2 capacity)
- Deployments require manual SSH and service restarts (downtime risk)
- No automated rollback capabilities
- Difficult to maintain staging/production separation
- High operational complexity for a system that should be declarative

## What Changes

Migrate the WordPress Clone & Restore System from EC2/Docker to **Kubernetes-native architecture** using:

- **KRO (Kube Resource Orchestrator)**: Each WordPress clone becomes a ResourceGroup (Job + Service + Ingress + Secret + RDS) managed atomically
- **ACK (AWS Controllers for Kubernetes)**: Manage RDS databases and IAM roles natively from Kubernetes using CRDs
- **Argo CD**: GitOps workflow for automatic deployments from Git (main → production, staging → staging namespace)
- **AWS Load Balancer Controller**: Path-based routing via Kubernetes Ingress (no manual ALB API calls)
- **Horizontal Pod Autoscaler (HPA)**: Auto-scale wp-k8s-service based on CPU/memory/request rate
- **Cluster Autoscaler**: Auto-scale worker nodes based on pod scheduling needs

**Key Design Decisions:**
1. **New Service, Existing Code Untouched**: Create `kubernetes/wp-k8s-service/` (new), keep `wp-setup-service/` (EC2 version) for rollback
2. **Namespace Isolation**: Staging and production in same EKS cluster via separate namespaces (cost savings)
3. **Database Strategy**: Hybrid approach - shared RDS for staging, per-clone RDS for critical production clones
4. **No Modifications to Existing Files**: All new code in `kubernetes/` folder

## Impact

**Affected specs**:
- `kubernetes-infrastructure` (NEW) - EKS cluster, VPC, node groups, IAM roles
- `kro-orchestration` (NEW) - ResourceGroup definitions for WordPress clones
- `ack-integration` (NEW) - RDS and IAM management via ACK controllers
- `gitops-cicd` (NEW) - Argo CD applications, GitHub Actions, Kustomize overlays
- `wp-clone-automation` (MODIFIED) - Clone provisioning now uses KRO instead of SSH+Docker

**Affected code**:
- **NEW**: `/kubernetes/wp-k8s-service/` - New Python service with KRO provisioner
- **NEW**: `/kubernetes/bootstrap/terraform/` - EKS cluster infrastructure
- **NEW**: `/kubernetes/kro/resourcegroups/` - KRO ResourceGroup definitions
- **NEW**: `/kubernetes/manifests/` - Kubernetes Deployment, Service, Ingress manifests
- **NEW**: `/kubernetes/argocd/` - Argo CD Application definitions
- **NEW**: `/.github/workflows/` - GitHub Actions for CI/CD
- **UNCHANGED**: `/wp-setup-service/` - EC2 version remains for rollback
- **UNCHANGED**: `/wordpress-target-image/` - Reused as-is in Kubernetes

**Benefits**:
- **Auto-scaling**: HPA scales wp-k8s-service (1-10 pods), Cluster Autoscaler scales nodes (2-20 nodes)
- **High Availability**: Multi-AZ deployment, pod auto-restart, RDS Multi-AZ failover
- **GitOps Workflow**: All changes via Git pull requests, automatic deployment, instant rollbacks
- **Code Reduction**: ~80% less provisioning code (KRO handles orchestration)
- **Observability**: Native Kubernetes metrics, OpenTelemetry integration
- **Cost Optimization**: Spot instances for clone Jobs, shared RDS for staging, scale-to-zero during off-hours

**Constraints**:
- **Cost Increase (Initial)**: $163/mo (EC2) → $350-500/mo (EKS baseline) before optimizations
- **Cost Target (Optimized)**: $200-250/mo with spot instances, Aurora Serverless, shared RDS for staging
- **Learning Curve**: Team needs Kubernetes, KRO, ACK, Argo CD knowledge
- **Migration Time**: 4-5 weeks for full migration with parallel testing
- **EKS Control Plane Cost**: $73/mo fixed cost regardless of usage

## Current Infrastructure Status

**EKS Cluster**: `wp-clone-restore` (Target version: 1.35)
- Terraform state exists at `/kubernetes/bootstrap/terraform/`
- Namespaces: `wordpress-staging`, `wordpress-production`
- AWS Load Balancer Controller: Configured via Karpenter
- IRSA: Enabled for service accounts

**Existing EC2 System (Running)**:
- Management Server: `13.222.20.138` (wp-setup-service)
- Target Server: `10.0.13.72` (WordPress clones)
- ALB: `wp-targets-alb-1392351630.us-east-1.elb.amazonaws.com`
- Domain: `clones.betaweb.ai` (HTTPS with ACM cert)

**Migration Strategy**:
1. **Weeks 1-3**: Build Kubernetes infrastructure in parallel (existing system untouched)
2. **Week 4**: Side-by-side testing (both EC2 and EKS running)
3. **Week 5**: Gradual cutover (DNS switch to EKS ALB)
4. **Week 6**: Monitor for 48 hours, decommission EC2 if stable

**Rollback Plan**:
- EC2 version remains deployed throughout migration
- DNS rollback takes < 5 minutes
- No data loss (RDS databases independent of compute layer)
