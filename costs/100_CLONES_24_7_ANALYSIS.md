# Cost Calculation: 100 WordPress Clones Running 24/7

## CURRENT CONFIGURATION

**Your Karpenter Setup (kubernetes/bootstrap/terraform/karpenter.tf:174):**
- **Instance Type:** Spot instances ONLY
- **Currently Running:** 3 nodes (no clones deployed right now)
- **Auto-scaling:** Karpenter manages node provisioning automatically
- **Instance Categories:** c, m, r, t (compute, memory, general purpose)
- **Cost Model:** ~70% cheaper than On-Demand

---

## Infrastructure Components (For 100 Clones)

### 1. EKS Cluster
- **EKS Control Plane**: $0.10/hour
- **Monthly**: $0.10 × 24 × 30 = $72/month

### 2. EC2 Nodes (Compute)

**Pod Requirements per Clone:**
- WordPress container: 250Mi memory, 100m CPU
- MySQL container: 512Mi memory, 250m CPU
- **Total per clone**: 762Mi memory, 350m CPU

**For 100 clones:**
- Memory needed: 100 × 762Mi = 76,200Mi = ~74.4GB
- CPU needed: 100 × 350m = 35,000m = 35 vCPU

**Additional pods:**
- System pods (CoreDNS, etc): ~2GB memory, ~2 vCPU
- wp-k8s-service: 512Mi memory, 250m CPU
- dramatiq-worker: 1Gi memory, 500m CPU
- Redis: 192Mi memory, 100m CPU
- Warm pool (assume 10 ready): 10 × 762Mi = ~7.6GB, 3.5 vCPU

**Total Resources:**
- Memory: 74.4 + 2 + 0.5 + 1 + 0.2 + 7.6 = ~85.7GB
- CPU: 35 + 2 + 0.25 + 0.5 + 0.1 + 3.5 = ~41.35 vCPU

**Instance Selection (with prefix delegation):**
Using c5.4xlarge instances (16 vCPU, 32GB RAM):
- Memory constraint: 85.7GB / 32GB = 2.68 → need 3 instances
- CPU constraint: 41.35 vCPU / 16 vCPU = 2.58 → need 3 instances
- **Instances needed**: 3 × c5.4xlarge

**Pricing (On-Demand, us-east-1):**
- c5.4xlarge: $0.68/hour
- 3 instances × $0.68 × 24 × 30 = $1,468.80/month

**Pricing (Spot, 70% discount):**
- c5.4xlarge spot: ~$0.204/hour (average)
- 3 instances × $0.204 × 24 × 30 = $440.64/month

### 3. Load Balancer (ALB)
- **ALB hours**: $0.0225/hour × 24 × 30 = $16.20/month
- **LCU costs**: Minimal for internal traffic
- **Estimated total**: ~$20/month

### 4. VPC & Networking
- **Data Transfer (internal)**: Mostly free within same AZ
- **Data Transfer (out)**: Minimal for clone traffic
- **NAT Gateway**: $0.045/hour × 24 × 30 = $32.40/month (per AZ)
- **Estimated total**: ~$35/month

### 5. EBS Storage
- **Per clone database**: ~1GB (small WordPress site)
- **100 clones**: 100GB
- **gp3 pricing**: $0.08/GB/month
- **Total**: 100 × $0.08 = $8/month

### 6. ECR (Container Registry)
- **Storage**: ~5GB for images
- **gp3 pricing**: $0.10/GB/month
- **Total**: 5 × $0.10 = $0.50/month

### 7. CloudWatch Logs (Optional)
- **Ingestion**: $0.50/GB
- **Storage**: $0.03/GB/month
- **Estimated**: ~$10/month (with log retention)

---

## Total Monthly Cost (YOUR CONFIGURATION = SPOT INSTANCES)
```
Component              | Cost/Month
-----------------------|------------
EKS Control Plane      | $72.00
EC2 Spot (3× c5.4xl)   | $440.64
Load Balancer (ALB)    | $20.00
VPC/NAT Gateway        | $35.00
EBS Storage (100GB)    | $8.00
ECR                    | $0.50
CloudWatch Logs        | $10.00
-----------------------|------------
TOTAL                  | $586.14/month
```

**Per clone**: $586.14 / 100 = **$5.86/clone/month**

---

## Alternative: If You Switched to On-Demand (NOT RECOMMENDED)

```
Component              | Cost/Month
-----------------------|------------
EKS Control Plane      | $72.00
EC2 (3× c5.4xlarge)    | $1,468.80
Load Balancer (ALB)    | $20.00
VPC/NAT Gateway        | $35.00
EBS Storage (100GB)    | $8.00
ECR                    | $0.50
CloudWatch Logs        | $10.00
-----------------------|------------
TOTAL                  | $1,614.30/month
```

**Per clone**: $1,614.30 / 100 = **$16.14/clone/month**
**Cost difference vs Spot**: +$1,028/month (64% more expensive)

---

## Cost Optimization with geoip=False

**Memory Savings per Worker:**
- With geoip=True: ~6GB per browser instance
- With geoip=False: ~1GB per browser instance
- **Savings**: ~5GB per worker

**With 4 workers:**
- Total savings: 4 × 5GB = 20GB

**Impact on Instance Count:**
- Without geoip optimization: Would need ~106GB memory → 4 instances
- With geoip=False: Need ~86GB memory → 3 instances
- **Cost savings**: 1 instance = $489.60/month (On-Demand) or $146.88/month (Spot)

---

## Comparison with Traditional Hosting

**Typical VPS/Cloud Hosting:**
- Shared hosting: $10-50/site/month
- VPS: $20-100/site/month
- Managed WordPress: $30-200/site/month

**Your Setup (Spot):** $5.86/site/month
- **70% cheaper** than cheapest shared hosting ($10/month)
- **83% cheaper** than typical managed WordPress ($30/month)

---

## Key Takeaways

1. ✅ **You're already using Spot** - saving 64% vs On-Demand ($1,028/month savings)
2. ✅ **geoip=False is enabled** - saves 1 instance ($150-490/month)
3. **24/7 operation costs $586/month** for 100 clones
4. **Per-clone cost: $5.86/month** - 70% cheaper than shared hosting

## Next Steps to Reduce Costs

1. ✅ **Already done:** Spot instances enabled
2. ✅ **Already done:** geoip=False enabled
3. 🔲 **Implement TTL cleanup** - don't run clones 24/7 unless needed
4. 🔲 **Optimize warm pool size** - only keep what you need ready

## If You Use It Less (Development/Testing Pattern)

**Development/Testing (8 hours/day, 5 days/week):**
- Usage: ~40 hours/week = 173 hours/month  
- Utilization: 24% of full-time
- **Cost**: $586 × 0.24 = **$140.64/month**
- **Per clone**: $1.41/clone/month

If you only run clones during work hours, your cost drops to **$141/month** instead of $586/month!
