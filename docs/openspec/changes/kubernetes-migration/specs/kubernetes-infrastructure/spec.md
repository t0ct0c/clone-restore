# Spec: Kubernetes Infrastructure

## Overview
Provision EKS cluster with supporting AWS infrastructure (VPC, node groups, IAM roles) to replace EC2/Docker architecture.

## ADDED Requirements

### REQ-K8S-001: EKS Cluster Provisioning
**Priority**: Critical
**Category**: Infrastructure

The system MUST provision an EKS cluster with control plane in multiple availability zones for high availability.

#### Scenario: EKS cluster is created with Terraform
**Given** no existing EKS cluster
**When** `terraform apply` is executed in `/kubernetes/bootstrap/terraform/`
**Then** an EKS cluster is created with control plane version 1.29 or later
**And** control plane spans 3 availability zones (us-east-1a, us-east-1b, us-east-1c)
**And** cluster endpoint is publicly accessible
**And** cluster authentication uses IAM

### REQ-K8S-002: Worker Node Groups
**Priority**: Critical
**Category**: Infrastructure

The system MUST provision worker node groups with auto-scaling enabled.

#### Scenario: Node groups support auto-scaling
**Given** EKS cluster is created
**When** worker node group is provisioned
**Then** minimum node count is 2
**And** maximum node count is 20
**And** desired node count starts at 2
**And** instance type is t3.large
**And** nodes are spread across 2+ availability zones

#### Scenario: Spot instances used for cost savings
**Given** worker node group is created
**When** node group configuration is applied
**Then** capacity type is SPOT
**And** spot allocation strategy is lowest-price
**And** max price is 70% of on-demand price

### REQ-K8S-003: VPC and Networking
**Priority**: Critical
**Category**: Infrastructure

The system MUST provision VPC with public and private subnets for EKS cluster.

#### Scenario: VPC supports EKS best practices
**Given** VPC provisioning starts
**When** Terraform creates VPC resources
**Then** VPC CIDR is 10.0.0.0/16
**And** 3 public subnets exist (one per AZ)
**And** 3 private subnets exist (one per AZ)
**And** NAT gateways exist in each public subnet
**And** private subnets route internet traffic through NAT gateways

### REQ-K8S-004: IAM Roles for IRSA
**Priority**: High
**Category**: Security

The system MUST provision IAM roles for service accounts (IRSA) to enable secure AWS API access.

#### Scenario: wp-k8s-service uses IRSA for ECR access
**Given** wp-k8s-service Deployment is created
**When** pod starts
**Then** service account has IAM role annotation
**And** pod can pull images from ECR without hardcoded credentials
**And** IAM role has policy for ecr:GetAuthorizationToken, ecr:BatchGetImage

#### Scenario: ACK controllers use IRSA for AWS resource management
**Given** ACK RDS controller is deployed
**When** controller pod starts
**Then** service account has IAM role annotation
**And** role has permissions for rds:CreateDBInstance, rds:DeleteDBInstance

### REQ-K8S-005: Namespace Isolation
**Priority**: High
**Category**: Resource Management

The system MUST create separate namespaces for staging and production with resource quotas.

#### Scenario: Staging namespace has restricted resources
**Given** staging namespace is created
**When** ResourceQuota is applied
**Then** namespace is limited to 4 CPU cores
**And** namespace is limited to 8GB memory
**And** namespace can create max 10 concurrent WordPress clones

#### Scenario: Production namespace has higher limits
**Given** production namespace is created
**When** ResourceQuota is applied
**Then** namespace is limited to 16 CPU cores
**And** namespace is limited to 32GB memory
**And** namespace can create max 100 concurrent WordPress clones

### REQ-K8S-006: Cluster Autoscaler
**Priority**: High
**Category**: Auto-scaling

The system MUST install Cluster Autoscaler to automatically scale worker nodes based on pod scheduling needs.

#### Scenario: Cluster scales up when pods are pending
**Given** all worker nodes are fully utilized
**And** new WordPress clone Job is created
**When** Kubernetes scheduler cannot place pod
**Then** Cluster Autoscaler detects pending pod
**And** new worker node is provisioned
**And** pod is scheduled on new node

#### Scenario: Cluster scales down when nodes are underutilized
**Given** worker node has no pods running for 10 minutes
**When** Cluster Autoscaler evaluates node utilization
**Then** node is cordoned
**And** node is drained
**And** node is terminated
**And** node count decreases (respects minimum of 2 nodes)

### REQ-K8S-007: AWS Load Balancer Controller
**Priority**: Critical
**Category**: Load Balancing

The system MUST install AWS Load Balancer Controller to manage ALB via Kubernetes Ingress resources.

#### Scenario: Ingress resources create ALB automatically
**Given** AWS Load Balancer Controller is installed
**When** Ingress resource is created with annotation `alb.ingress.kubernetes.io/group.name: wordpress-clones`
**Then** ALB is provisioned automatically (or reused if group exists)
**And** Ingress path rules create ALB listener rules
**And** target groups route traffic to Kubernetes Service

---

## Integration Points

### Related Capabilities
- `kro-orchestration`: KRO uses Kubernetes API to create resources on this cluster
- `ack-integration`: ACK controllers use Kubernetes CRDs and IRSA roles provisioned here
- `gitops-cicd`: Argo CD deploys to namespaces created by this spec

### Modified Components
- **NEW**: `/kubernetes/bootstrap/terraform/main.tf` - EKS cluster provisioning
- **NEW**: `/kubernetes/bootstrap/terraform/vpc.tf` - VPC and networking
- **NEW**: `/kubernetes/bootstrap/terraform/iam.tf` - IRSA roles
- **NEW**: `/kubernetes/bootstrap/terraform/addons.tf` - Cluster Autoscaler, AWS Load Balancer Controller

---

## Non-Functional Requirements

### Performance
- EKS cluster provisioning completes within 15 minutes
- Worker node auto-scaling latency < 3 minutes (node ready)
- ALB provisioning via Ingress < 2 minutes

### Security
- Worker nodes in private subnets (no public IPs)
- EKS cluster endpoint requires IAM authentication
- IRSA roles follow least-privilege principle
- Network policies isolate namespaces

### Reliability
- Control plane spans 3 availability zones
- Worker nodes span 2+ availability zones
- Cluster Autoscaler respects minimum node count (2) to avoid zero-capacity scenarios

### Cost
- Spot instances reduce compute cost by 70%
- Cluster Autoscaler scales down underutilized nodes
- Single EKS control plane shared across staging/production ($73/mo vs $146/mo for separate clusters)
