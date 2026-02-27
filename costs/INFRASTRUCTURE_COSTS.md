# Infrastructure Cost Analysis - WordPress Clone System

**Environment**: wordpress-staging (Pre-Production)  
**AWS Region**: us-east-1  
**Last Updated**: February 27, 2026

---

## Current Infrastructure Configuration

### Compute (EKS Nodes via Karpenter)

**NodePool Configuration**: `general-purpose`
- **Capacity Type**: Spot instances (70-90% cheaper than On-Demand)
- **Instance Categories**: c, m, r, t families
- **Instance Sizes**: xlarge and larger (after optimization)
- **Auto-Scaling**: Enabled with aggressive consolidation
  - `consolidateAfter`: 30 seconds
  - `consolidationPolicy`: WhenEmptyOrUnderutilized
- **Node Expiry**: 720 hours (30 days)
- **Limits**: 100 vCPU, 200Gi RAM maximum

### Current Node Inventory (as of fix)
```
Node 1: c3.4xlarge (Spot) - 16 vCPU, 30Gi RAM - 234 pod capacity
Node 2: t3.large - 2 vCPU, 8Gi RAM - baseline system services
```

---

## Cost Breakdown

### Hourly Rates (us-east-1, Spot Pricing)

| Instance Type | vCPU | RAM   | Spot $/hr | On-Demand $/hr | Savings |
|---------------|------|-------|-----------|----------------|---------|
| t3.large      | 2    | 8Gi   | $0.033    | $0.0832        | 60%     |
| m5d.xlarge    | 4    | 16Gi  | $0.050    | $0.226         | 78%     |
| m5d.2xlarge   | 8    | 32Gi  | $0.100    | $0.452         | 78%     |
| c3.4xlarge    | 16   | 30Gi  | $0.168    | $0.840         | 80%     |
| c5.4xlarge    | 16   | 32Gi  | $0.204    | $0.680         | 70%     |
| m5.4xlarge    | 16   | 64Gi  | $0.230    | $0.768         | 70%     |

**Note**: Spot prices fluctuate based on demand. Prices shown are typical averages.

---

## Production Cost Scenarios

### Scenario 1: Low Traffic Baseline (Staging/Dev)
**Usage Pattern**:
- 1 small node for system services (24/7)
- Occasional clone creation testing (few hours/week)
- Auto-scales to zero during nights/weekends

**Monthly Breakdown**:
```
Base Node (t3.large):        $0.033/hr × 730 hrs = $24.09
Burst Nodes (8 hrs/week):    $0.168/hr × 32 hrs  = $5.38
Total:                                              $29.47/month
```

**Expected**: **$25-35/month**

---

### Scenario 2: Active Development/Testing
**Usage Pattern**:
- 1 baseline node (24/7)
- Clone testing 4 hours/day, 5 days/week
- 2-3 xlarge nodes during active testing

**Monthly Breakdown**:
```
Base Node (t3.large):        $0.033/hr × 730 hrs  = $24.09
Test Nodes (80 hrs/month):   $0.168/hr × 160 hrs  = $26.88
Total:                                               $50.97/month
```

**Expected**: **$45-60/month**

---

### Scenario 3: Production - Light Load
**Usage Pattern**:
- 2 nodes baseline (1 small + 1 medium for redundancy)
- Clone creation during business hours (8am-6pm weekdays)
- Peak: 3-4 nodes during busy periods

**Monthly Breakdown**:
```
Base Nodes (24/7):
  - t3.large:                $0.033/hr × 730 hrs  = $24.09
  - m5d.xlarge:              $0.050/hr × 730 hrs  = $36.50

Peak Nodes (200 hrs/month):
  - 2× c3.4xlarge:           $0.336/hr × 200 hrs  = $67.20

Total:                                              $127.79/month
```

**Expected**: **$100-150/month**

---

### Scenario 4: Production - High Volume
**Usage Pattern**:
- 3 nodes baseline (24/7)
- Frequent clone operations (12-16 hours/day)
- Peak: 5-6 nodes during business hours

**Monthly Breakdown**:
```
Base Nodes (24/7):
  - t3.large:                $0.033/hr × 730 hrs  = $24.09
  - 2× m5d.xlarge:           $0.100/hr × 730 hrs  = $73.00

Peak Nodes (400 hrs/month):
  - 3× c3.4xlarge:           $0.504/hr × 400 hrs  = $201.60

Total:                                              $298.69/month
```

**Expected**: **$250-350/month**

---

### Scenario 5: Maximum Capacity (Burst Testing)
**Usage Pattern**:
- Hitting Karpenter limits (100 vCPU)
- ~6 xlarge nodes running simultaneously
- Short duration testing (not sustained)

**Hourly Cost** (at max):
```
6× c3.4xlarge:               $0.168/hr × 6        = $1.008/hour
```

**Monthly Cost** (if sustained 24/7):
```
Max Capacity (730 hrs):      $1.008/hr × 730 hrs  = $735.84/month
```

**Realistic** (4 hours/day): ~$120/month additional

---

## Additional AWS Costs

### EKS Control Plane
- **Fixed Cost**: $0.10/hour = **$73/month**
- Per cluster, regardless of node count

### Data Transfer
- **Intra-AZ**: Free
- **Inter-AZ**: $0.01/GB
- **Internet Egress**: $0.09/GB (first 10TB)
- **Expected**: $5-20/month (depending on clone traffic)

### EBS Volumes (Node Storage)
- **gp3**: $0.08/GB-month
- **Estimated**: 50GB per node × 3 nodes = $12/month

### Load Balancer (ALB)
- **Fixed**: $0.0225/hour = $16.43/month
- **LCU**: $0.008/hour per LCU
- **Estimated**: $20-30/month total

### ECR (Container Registry)
- **Storage**: $0.10/GB-month
- **Images**: ~2GB total
- **Cost**: $0.20/month (negligible)

### CloudWatch Logs
- **Ingestion**: $0.50/GB
- **Storage**: $0.03/GB-month
- **Estimated**: $5-15/month

---

## Total Monthly Cost Projections

### Pre-Production Staging (Current)
```
EKS Control Plane:           $73.00
Nodes (Scenario 1):          $29.47
Data Transfer:               $5.00
EBS Storage:                 $12.00
Load Balancer:               $25.00
CloudWatch:                  $5.00
─────────────────────────────────
Total:                       $149.47/month
```

**Expected Range**: **$140-170/month**

---

### Production - Light Load
```
EKS Control Plane:           $73.00
Nodes (Scenario 3):          $127.79
Data Transfer:               $10.00
EBS Storage:                 $16.00
Load Balancer:               $30.00
CloudWatch:                  $10.00
─────────────────────────────────
Total:                       $266.79/month
```

**Expected Range**: **$250-300/month**

---

### Production - High Volume
```
EKS Control Plane:           $73.00
Nodes (Scenario 4):          $298.69
Data Transfer:               $20.00
EBS Storage:                 $20.00
Load Balancer:               $40.00
CloudWatch:                  $15.00
─────────────────────────────────
Total:                       $466.69/month
```

**Expected Range**: **$450-550/month**

---

## Cost Optimization Strategies

### 1. Aggressive Auto-Scaling (Already Enabled)
**Current Setting**: `consolidateAfter: 30s`
- Karpenter consolidates underutilized nodes within 30 seconds
- Scales down to minimum required capacity when idle
- **Savings**: 40-60% compared to always-on infrastructure

### 2. Spot Instance Usage (Already Enabled)
**Current Setting**: 100% Spot instances
- 70-90% cheaper than On-Demand
- Karpenter handles interruptions automatically
- **Savings**: 70-80% on compute costs

### 3. Instance Size Optimization (Recently Applied)
**Changed**: Excluded small instances (nano, micro, small, medium, large)
- Prevents IP allocation failures
- Ensures efficient prefix delegation usage
- Larger instances paradoxically more cost-effective (higher density)
- **Savings**: Reduced node count by 33% (3→2 nodes)

### 4. Node Expiry Policy
**Current Setting**: `expireAfter: 720h` (30 days)
- Forces node replacement monthly
- Ensures latest AMI and security patches
- No cost impact (continuous replacement)

### 5. Resource Limits
**Current Setting**: 100 vCPU, 200Gi RAM max
- Prevents runaway scaling
- Budget protection
- **Savings**: Prevents unexpected bills

---

## Cost Control Recommendations

### Immediate Actions

1. **Set Up AWS Budgets**
```
Monthly Budget: $200
Alert at: 80% ($160)
Alert at: 100% ($200)
```

2. **Enable Cost Anomaly Detection**
```
Service: EC2
Threshold: $50 daily increase
Notification: Email/Slack
```

3. **Tag Resources for Cost Tracking**
```yaml
Tags:
  Environment: wordpress-staging
  Project: clone-system
  ManagedBy: karpenter
  CostCenter: engineering
```

### Long-Term Optimizations

1. **Consider Savings Plans** (if predictable usage)
   - 1-year commitment: 40% savings
   - 3-year commitment: 60% savings
   - Only if sustained production usage

2. **Reserved Instances for EKS Control Plane**
   - Not currently possible (EKS is pay-per-use)
   - Consider consolidating multiple clusters if you have them

3. **Implement TTL Cleanup** (Already Enabled)
   - Clones auto-delete after 30 minutes
   - Prevents forgotten resources
   - Critical for cost control

4. **Monitor Warm Pool Size**
   - Current max: 20 pods
   - Consider reducing if over-provisioning
   - Balance between performance and cost

---

## Cost Monitoring Commands

### Check Current Node Costs
```bash
# List all nodes with instance types
kubectl get nodes -o custom-columns=\
NAME:.metadata.name,\
INSTANCE:.metadata.labels.node\\.kubernetes\\.io/instance-type,\
CAPACITY-TYPE:.metadata.labels.karpenter\\.sh/capacity-type,\
AGE:.metadata.creationTimestamp

# Calculate approximate hourly cost
# (Manual: multiply node count × instance spot price)
```

### Check Karpenter Scaling Events
```bash
kubectl logs -n karpenter -l app.kubernetes.io/name=karpenter --tail=100 | grep -E "consolidat|launch|terminat"
```

### Check Resource Utilization
```bash
kubectl top nodes
kubectl get pods -A -o json | jq '.items | length'
```

### AWS Cost Explorer CLI
```bash
# Last 30 days EC2 costs
aws ce get-cost-and-usage \
  --time-period Start=2024-01-01,End=2024-02-01 \
  --granularity MONTHLY \
  --metrics "UnblendedCost" \
  --filter file://ec2-filter.json
```

---

## Risk Factors & Mitigation

### Risk 1: Spot Instance Interruption
**Probability**: Low (5-10% monthly)
**Impact**: 2-3 minute interruption while Karpenter provisions replacement
**Mitigation**: 
- Karpenter automatically replaces interrupted instances
- Consider on-demand fallback for critical workloads
- Enable Spot interruption handling (already enabled)

### Risk 2: Scaling Limits Hit During Peak
**Probability**: Low (if 100 vCPU limit sufficient)
**Impact**: New pods wait in Pending state
**Mitigation**:
- Monitor peak usage patterns
- Increase limits if needed (current: 100 vCPU)
- Set up alerts for approaching limits

### Risk 3: Warm Pool Over-Provisioning
**Probability**: Medium (observed 43 pods vs 20 max)
**Impact**: Unnecessary cost (~$10-20/hour extra)
**Mitigation**:
- Fix warm pool controller race condition
- Implement rate limiting on pod creation
- Monitor warm pool size regularly

### Risk 4: Forgotten Resources
**Probability**: Low (TTL enabled)
**Impact**: Lingering clones consuming resources
**Mitigation**:
- 30-minute TTL on all clones (already enabled)
- Daily cleanup cronjob (already enabled)
- Weekly manual audit

### Risk 5: AWS Quota Limits
**Probability**: Low (64 vCPU approved)
**Impact**: Cannot scale beyond quota
**Mitigation**:
- Current quota: 64 vCPU (sufficient for 30 clones)
- Request increase if expanding
- Monitor quota usage in AWS console

---

## Break-Even Analysis

### Spot vs On-Demand

**Current Setup (Spot)**:
- Baseline: ~$150/month
- Production: ~$300/month

**If Using On-Demand**:
- Baseline: ~$500/month (3.3× more expensive)
- Production: ~$1000/month (3.3× more expensive)

**Monthly Savings with Spot**: $350-700/month

### Auto-Scaling vs Always-On

**Current Setup (Auto-Scaling)**:
- Scales to 1-2 nodes when idle
- Average: ~$150/month

**If Always-On (3 large nodes)**:
- 3× c3.4xlarge: $0.504/hr × 730 hrs = $368/month
- Plus fixed costs: ~$450/month total

**Monthly Savings with Auto-Scaling**: ~$300/month

---

## Cost Comparison: Alternative Architectures

### Option 1: Current (EKS + Karpenter + Spot)
**Monthly Cost**: $150-300
**Pros**: Flexible, auto-scales, production-ready
**Cons**: Complex to manage

### Option 2: EC2 Auto-Scaling Groups
**Monthly Cost**: $200-400
**Pros**: Simpler than EKS
**Cons**: Less flexible, manual scaling tuning

### Option 3: Fargate (Serverless)
**Monthly Cost**: $300-600
**Pros**: No node management
**Cons**: 2-3× more expensive, slower cold starts

### Option 4: Lambda + ECS
**Monthly Cost**: $100-200
**Pros**: Cheaper for intermittent workloads
**Cons**: Not suitable for long-running WordPress clones

**Recommendation**: **Current architecture is optimal** for this use case

---

## Summary & Recommendations

### Current State
- **Monthly Cost**: $140-170 (staging/light usage)
- **Architecture**: Cost-optimized with Spot + Auto-Scaling
- **Scaling**: Aggressive consolidation (30s)
- **Protection**: Resource limits + TTL cleanup

### For Production Launch

1. **Expected Cost**: $250-350/month (light-medium load)
2. **Budget**: Set $400/month buffer for safety
3. **Monitoring**: Enable AWS Budgets + Cost Anomaly Detection
4. **Optimization**: Already implemented (Spot + Auto-Scaling)
5. **Risk**: Low (Spot interruptions mitigated by Karpenter)

### Action Items

- [ ] Set up AWS Budget: $400/month with 80% alert
- [ ] Enable Cost Anomaly Detection (threshold: $50 daily)
- [ ] Add resource tags for cost tracking
- [ ] Weekly cost review (first 3 months)
- [ ] Fix warm pool over-provisioning issue
- [ ] Monitor and adjust Karpenter limits based on usage

### Bottom Line

**Your infrastructure is already cost-optimized**:
- ✅ Spot instances (70-80% savings)
- ✅ Auto-scaling (40-60% savings)
- ✅ Resource limits (budget protection)
- ✅ TTL cleanup (prevents waste)

**Expected production cost**: **$250-350/month** for light-to-medium workload.

This is **reasonable** for a production WordPress clone system serving multiple clients.
