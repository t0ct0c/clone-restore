# Cost Calculation: 100 WordPress Clones Running 24/7

## Infrastructure Components

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

## Total Monthly Cost Summary

### Scenario A: On-Demand Instances
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

### Scenario B: Spot Instances (70% discount)
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

**Our Solution:**
- On-Demand: $16.14/site/month (competitive)
- Spot: $5.86/site/month (70% cheaper than shared hosting!)

---

## Key Takeaways

1. **Spot instances reduce costs by 64%** ($1,614 → $586/month)
2. **geoip=False saves ~$150-490/month** (1 fewer instance needed)
3. **Scale economics**: Cost per clone decreases with more clones
4. **24/7 operation is expensive**: TTL-based cleanup recommended for non-permanent clones
5. **Break-even**: Need ~35-40 traditional hosted sites to justify infrastructure costs

## Recommendations

1. ✅ **Use Spot instances** for production (70% cost savings)
2. ✅ **Enable geoip=False** (saves 1 instance = $150-490/month)
3. ✅ **Implement TTL cleanup** (don't run clones 24/7 unless needed)
4. ✅ **Use reserved instances** for predictable workloads (30-40% discount)
5. ✅ **Optimize warm pool size** (don't maintain 20 warm pods constantly)

## Realistic Usage Pattern

**Scenario C: Development/Testing (8 hours/day, 5 days/week)**
- Usage: ~40 hours/week = 173 hours/month
- Utilization: 173 / 720 = 24% of month
- **Cost**: $586 × 0.24 = **$140.64/month**
- **Per clone**: $1.41/clone/month

This is the most realistic scenario for a development/testing environment!
