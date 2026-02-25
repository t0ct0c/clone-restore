# Spec: Kubernetes Infrastructure

## Capability
Deploy and configure EKS cluster with necessary controllers for WordPress clone orchestration.

## Requirements

### EKS Cluster
- **Version**: Kubernetes 1.35 (latest available in us-east-1)
- **Compute**: Managed node groups with Karpenter for autoscaling
- **Networking**: VPC with public + private subnets across 3 AZs
- **Security**: IRSA enabled, security groups for pod-to-RDS communication
- **Cost**: ~$182/month (EKS $73 + nodes $30 + RDS $30 + ALB $16 + NAT $33)

### Controllers Required
1. **Karpenter v1.8.6**: Fast node provisioning (~30 seconds)
2. **KEDA v2.14.0**: Event-driven pod autoscaling
3. **ACK RDS Controller**: Provision RDS instances via K8s API
4. **KRO**: Kubernetes Resource Orchestrator for declarative resource groups
5. **AWS Load Balancer Controller**: Automatic ALB creation from Ingress
6. **Argo CD**: GitOps-based continuous deployment

### IAM Roles (IRSA)
- ACK RDS Controller: `AmazonRDSFullAccess` (scoped to cluster)
- AWS LB Controller: ALB + Target Group management
- wp-k8s-service: Kubernetes API access, RDS database operations
- Karpenter: EC2 instance provisioning
- Cluster Autoscaler: ASG management (legacy, Karpenter preferred)

## Acceptance Criteria

**Infrastructure**:
- [ ] `kubectl get nodes` shows at least 1 node running
- [ ] EKS cluster endpoint accessible via kubectl
- [ ] VPC has 3 public + 3 private subnets
- [ ] NAT gateway enables private subnet internet access
- [ ] RDS security group allows ingress from EKS pods

**Controllers**:
- [ ] `kubectl get pods -n karpenter` shows controller running
- [ ] `kubectl get pods -n keda` shows 3 pods (operator, admission, metrics)
- [ ] `kubectl get pods -n ack-system` shows ack-rds-controller running
- [ ] `kubectl get pods -n kro-system` shows kro-controller running
- [ ] `kubectl get pods -n kube-system | grep aws-load-balancer-controller` shows 2 replicas
- [ ] `kubectl get pods -n argocd` shows all Argo CD components running

**CRDs Registered**:
- [ ] `kubectl get crds | grep karpenter` shows NodePool, EC2NodeClass
- [ ] `kubectl get crds | grep keda` shows ScaledObject, TriggerAuthentication
- [ ] `kubectl get crds | grep rds` shows DBInstance, DBSubnetGroup
- [ ] `kubectl get crds | grep kro` shows ResourceGroup
- [ ] `kubectl get crds | grep elbv2` shows TargetGroupBinding, IngressClassParams

**Namespaces**:
- [ ] `kubectl get namespace wordpress-staging` exists
- [ ] `kubectl get namespace wordpress-production` exists
- [ ] Resource quotas configured for both namespaces

**Terraform State**:
- [ ] `terraform state list` shows all infrastructure resources
- [ ] `terraform output` shows cluster endpoint, IAM role ARNs

## Non-Requirements

- **Multi-cluster setup**: Single EKS cluster for MVP
- **Service mesh**: No Istio/Linkerd needed for MVP
- **Secrets management**: No External Secrets Operator (use K8s Secrets for MVP)
- **Policy enforcement**: No OPA/Kyverno for MVP

## Edge Cases

**Karpenter node provisioning failure**:
- Fallback to managed node group
- Alert if no nodes available for 5+ minutes

**Controller CrashLoopBackOff**:
- Check IRSA role permissions
- Verify CRD installation order
- Check controller logs for specific errors

**RDS subnet group misconfiguration**:
- Ensure subnets are in private subnet group
- Verify security group allows EKS pod CIDR

## Testing Strategy

**Unit Tests**: N/A (infrastructure)

**Integration Tests**:
1. Deploy test pod, verify it schedules on Karpenter node
2. Create test Ingress, verify ALB created automatically
3. Create test DBInstance (ACK), verify RDS provisioned
4. Create test ResourceGroup (KRO), verify child resources created

**Validation Script**:
```bash
#!/bin/bash
# kubernetes/bootstrap/scripts/validate-infrastructure.sh

set -e

echo "Validating EKS cluster..."
kubectl get nodes

echo "Validating controllers..."
kubectl wait --for=condition=available --timeout=60s deployment/karpenter -n karpenter
kubectl wait --for=condition=available --timeout=60s deployment/keda-operator -n keda
kubectl wait --for=condition=available --timeout=60s deployment/ack-rds-controller -n ack-system
kubectl wait --for=condition=available --timeout=60s deployment/kro-controller -n kro-system
kubectl wait --for=condition=available --timeout=60s deployment/aws-load-balancer-controller -n kube-system
kubectl wait --for=condition=available --timeout=60s deployment/argocd-server -n argocd

echo "Validating CRDs..."
kubectl get crd nodepools.karpenter.sh
kubectl get crd scaledobjects.keda.sh
kubectl get crd dbinstances.rds.services.k8s.aws
kubectl get crd resourcegroups.kro.run
kubectl get crd targetgroupbindings.elbv2.k8s.aws

echo "Validating namespaces..."
kubectl get namespace wordpress-staging
kubectl get namespace wordpress-production

echo "✅ Infrastructure validation complete!"
```

## Metrics

**Provisioning Time**:
- Karpenter node: < 60 seconds
- Pod scheduling: < 30 seconds
- Ingress ALB creation: < 2 minutes

**Availability**:
- Controller uptime: > 99.9%
- API server availability: > 99.95%

**Cost**:
- Baseline: ~$182/month
- Per-clone marginal cost: ~$0.02/hour (pod resources only)

## Dependencies

- AWS account with EKS permissions
- Terraform >= 1.0
- kubectl >= 1.28
- Helm >= 3.0
- aws-cli >= 2.0

## References

- EKS Best Practices: https://aws.github.io/aws-eks-best-practices/
- Karpenter Documentation: https://karpenter.sh/
- KEDA Documentation: https://keda.sh/
- ACK Documentation: https://aws-controllers-k8s.github.io/
- KRO GitHub: https://github.com/awslabs/kro
