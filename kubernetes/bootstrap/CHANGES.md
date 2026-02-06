# Infrastructure Changes Summary

## Adjustments Made Based on Feedback

### 1. **Node Count: 2 → 1 Node**
**Changed in**: `variables.tf`
- `min_nodes`: 2 → **1**
- `desired_nodes`: 2 → **1**
- `max_nodes`: 20 (unchanged)

**Rationale**: Start small, let Karpenter add nodes on-demand
**Cost Savings**: ~$60/month (1 less t3.large running 24/7)

### 2. **NAT Gateways: 3 → 1 NAT Gateway**
**Changed in**: `vpc.tf` line 28
- `single_nat_gateway`: false → **true**

**Why 3 NAT Gateways Originally?**
- Multi-AZ high availability (one NAT per AZ)
- Avoids cross-AZ data transfer charges
- If one AZ fails, others still have internet access

**Why Switch to 1 NAT Gateway?**
- **Cost Savings**: $64/month (2 fewer NAT gateways)
- Acceptable risk for ephemeral WordPress clones
- If NAT fails, we just can't create new clones temporarily
- Cross-AZ data transfer charges are minimal for this workload

**Tradeoff**: Single point of failure, but worth the cost savings

### 3. **Added Karpenter (Better Node Autoscaling)**
**New file**: `karpenter.tf`

**What is Karpenter?**
- Advanced node autoscaler (better than Cluster Autoscaler)
- Provisions nodes in ~30 seconds (vs 2-3 minutes for Cluster Autoscaler)
- More flexible instance selection
- Supports spot instances for 70% cost savings
- Auto-consolidation (removes underutilized nodes)

**Components Created**:
- IAM role for Karpenter controller (IRSA)
- IAM instance profile for Karpenter-managed nodes
- SQS queue for spot interruption handling
- EventBridge rules for spot instance warnings
- Helm chart installation
- NodePool definition (spot + on-demand instances)
- EC2NodeClass for node configuration

**Benefits**:
- Faster scaling (30 seconds vs 2-3 minutes)
- Cost optimization with spot instances
- Better bin-packing (uses instance types efficiently)
- Auto-consolidation of underutilized nodes

### 4. **Added KEDA (Event-Driven Autoscaling)**
**New file**: `keda.tf`

**What is KEDA?**
- Kubernetes Event-Driven Autoscaling
- Scales pods based on external metrics/events
- Works alongside HPA (Horizontal Pod Autoscaler)

**Use Cases for wp-k8s-service**:
- Scale based on SQS queue depth (future)
- Scale based on HTTP request rate
- Scale based on custom Prometheus metrics
- Scale to zero when no traffic

**Components Created**:
- KEDA namespace
- KEDA operator, metrics server, webhooks via Helm
- Example ScaledObject for wp-k8s-service (template)

**Benefits**:
- More intelligent autoscaling than basic HPA
- Can scale to zero during off-hours (cost savings)
- Event-driven (reacts to actual load, not just CPU/memory)

## Updated Cost Estimates

### Before Changes
- EKS control plane: $73/month
- t3.large × 2: $121/month
- NAT Gateways × 3: $97/month
- **Total**: $291/month baseline

### After Changes (On-Demand)
- EKS control plane: $73/month
- t3.large × 1: $60/month
- NAT Gateway × 1: $33/month
- **Total**: $166/month baseline

### After Changes (With Spot via Karpenter)
- EKS control plane: $73/month
- t3.large × 1 (spot): $18/month
- NAT Gateway × 1: $33/month
- **Total**: $124/month baseline

**Savings**: $167/month compared to original plan!

## Architecture Comparison

### Cluster Autoscaler vs Karpenter

| Feature | Cluster Autoscaler | Karpenter |
|---------|-------------------|-----------|
| Scaling Speed | 2-3 minutes | ~30 seconds |
| Instance Flexibility | Fixed (only t3.large) | Dynamic (c, m, r, t families) |
| Spot Support | Limited | Native, with interruption handling |
| Cost Optimization | Basic | Advanced (bin-packing, consolidation) |
| Complexity | Simple | More features, slightly complex |

### HPA vs KEDA

| Feature | HPA | KEDA |
|---------|-----|------|
| Metrics | CPU, Memory | CPU, Memory, SQS, HTTP, Custom |
| Scale to Zero | No | Yes |
| Event-Driven | No | Yes |
| Use Case | Basic scaling | Advanced, event-driven workloads |

## Next Steps

1. Review the updated infrastructure
2. Run `terraform init` to install new providers (kubectl provider added)
3. Run `terraform validate` to verify configuration
4. Run `terraform plan` to review changes
5. Run `terraform apply` to provision (confirm first!)

## Files Modified

- `variables.tf`: Changed node counts (2→1)
- `vpc.tf`: Single NAT gateway (line 28)
- `main.tf`: Added Karpenter discovery tags
- `versions.tf`: Added kubectl provider
- `outputs.tf`: Added Karpenter outputs

## Files Added

- `karpenter.tf`: Full Karpenter setup (200+ lines)
- `keda.tf`: Full KEDA setup with example ScaledObject
- `CHANGES.md`: This file

## Notes

- Karpenter replaces Cluster Autoscaler (can remove Task 1.5 later)
- KEDA works alongside HPA, not a replacement
- Spot instances via Karpenter provide 70% savings
- Single NAT gateway is acceptable risk for this workload
