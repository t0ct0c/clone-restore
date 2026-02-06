# EKS Cluster Infrastructure

This directory contains Terraform configuration for the WordPress Clone & Restore EKS cluster.

## Prerequisites

- AWS CLI configured with credentials
- Terraform >= 1.0
- kubectl >= 1.28

## What Gets Created

### Infrastructure
- **EKS Cluster**: Kubernetes 1.28 cluster with IRSA enabled
- **VPC**: Multi-AZ VPC with public and private subnets (3 AZs)
- **NAT Gateways**: Multi-AZ NAT for high availability
- **Node Group**: t3.large instances (min: 2, max: 20, desired: 2)

### IAM Roles (IRSA)
- ACK RDS Controller role
- wp-k8s-service role
- AWS Load Balancer Controller role
- Cluster Autoscaler role

### Kubernetes Resources
- Namespaces: `wordpress-staging`, `wordpress-production`
- Resource quotas for both namespaces
- Security groups for RDS access
- RDS subnet groups

## Usage

### 1. Initialize Terraform

```bash
cd kubernetes/bootstrap/terraform
terraform init
```

### 2. Review the Plan

```bash
terraform plan
```

### 3. Apply the Configuration

```bash
terraform apply
```

This will take approximately 15-20 minutes to create the EKS cluster and all resources.

### 4. Configure kubectl

After the cluster is created, configure kubectl:

```bash
aws eks update-kubeconfig --region us-east-1 --name wordpress-clone-restore
```

### 5. Verify Cluster Access

```bash
kubectl get nodes
kubectl get namespaces
```

## Configuration

### Variables

You can customize the deployment by modifying `variables.tf` or creating a `terraform.tfvars` file:

```hcl
# terraform.tfvars
cluster_name     = "wordpress-clone-restore"
aws_region       = "us-east-1"
min_nodes        = 2
max_nodes        = 20
desired_nodes    = 2
instance_types   = ["t3.large"]
enable_spot_instances = false  # Set to true for cost savings
```

### Spot Instances (Cost Optimization)

To enable spot instances for 70% cost reduction:

```hcl
enable_spot_instances = true
```

## Outputs

After applying, Terraform will output:

- `cluster_name`: EKS cluster name
- `cluster_endpoint`: EKS API endpoint
- `configure_kubectl`: Command to configure kubectl
- IAM role ARNs for all service accounts
- VPC and subnet IDs
- RDS security group and subnet group

## Cost Estimate

### Baseline (On-Demand)
- EKS control plane: $73/month
- t3.large × 2: ~$121/month
- NAT Gateways × 3: ~$97/month
- **Total**: ~$291/month (before workload costs)

### Optimized (Spot Instances)
- EKS control plane: $73/month
- t3.large × 2 (spot): ~$36/month
- NAT Gateways × 3: ~$97/month
- **Total**: ~$206/month (before workload costs)

## Next Steps

After the cluster is up:

1. Install ACK controllers (Task 1.2)
2. Install KRO (Task 1.3)
3. Install Argo CD (Task 1.4)
4. Install Cluster Autoscaler (Task 1.5)
5. Install AWS Load Balancer Controller (Task 1.6)

See the scripts in `kubernetes/bootstrap/scripts/` for installation procedures.

## Cleanup

To destroy all resources:

```bash
terraform destroy
```

**Warning**: This will delete the entire EKS cluster and all associated resources.
