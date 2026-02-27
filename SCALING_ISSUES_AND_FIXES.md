# Scaling Issues and Fixes - WordPress Clone System

**Date**: February 27, 2026  
**Goal**: Scale to 30 simultaneous WordPress clones for demo video  
**AWS Quota**: 64 vCPU approved

---

## Problems Encountered and Solutions

### 1. **Warm Pool Controller Bug - Queue Detection Failure**

**Problem**: 
- Warm pool controller couldn't detect queue depth
- Always read 0 jobs even when queue had 30 items
- Never scaled beyond 2 baseline warm pods
- Result: All clones used slow cold provisioning (160s) instead of fast warm pool (70s)

**Root Cause**:
```python
# WRONG - Line 60 in warm_pool_controller.py
queue_key = f"{self.queue_name}.msgs"  # Checked: "clone-queue.msgs"

# CORRECT
queue_key = f"dramatiq:{self.queue_name}"  # Should check: "dramatiq:clone-queue"
```

**Solution**:
- Fixed `kubernetes/wp-k8s-service/app/warm_pool_controller.py` line 60
- Built new image: `wp-k8s-service:warmpool-fix-20260227-093044`
- Deployed to EKS cluster

**Files Modified**:
- `kubernetes/wp-k8s-service/app/warm_pool_controller.py`

---

### 2. **VPC Subnet IP Exhaustion**

**Problem**:
- Cluster ran out of IPs after ~50 pods
- Error: "failed to assign an IP address to container"
- Happened in subnet `10.0.3.0/24` (251 IPs total, 70 available)
- Karpenter created 6 nodes in ONE subnet instead of distributing across all 6 subnets

**Root Cause**:
- AWS VPC CNI assigns pod IPs from VPC subnets (not overlay network)
- Each pod gets a real VPC IP address
- Karpenter created all nodes in same availability zone/subnet
- One subnet exhausted while others had plenty of IPs

**Initial Analysis**:
```
VPC: 10.0.0.0/16 (65,536 IPs) ✓ Plenty
Subnets: 6 × /24 = ~1,500 usable IPs ✓ Should be enough
Problem: All pods landed in ONE subnet (10.0.3.x)
```

**Solution Attempted**: Enable AWS VPC CNI Prefix Delegation
```bash
kubectl set env daemonset aws-node -n kube-system ENABLE_PREFIX_DELEGATION=true
kubectl set env daemonset aws-node -n kube-system WARM_PREFIX_TARGET=1
kubectl patch configmap amazon-vpc-cni -n kube-system --type merge -p '{"data":{"warm-prefix-target":"1"}}'
```

**What Prefix Delegation Does**:
- **Old**: Each node gets individual IPs, max ~35 pods/node
- **New**: Each node gets /28 prefixes (16 IPs each), max ~110 pods/node
- **Benefit**: 3x pod density without changing VPC

**Files Modified**:
- VPC CNI DaemonSet configuration (via kubectl)
- ConfigMap: `amazon-vpc-cni` in kube-system namespace

---

### 3. **Instance Type Matters - Small Nodes Can't Use Prefix Delegation Effectively**

**Problem**:
- Enabled prefix delegation but new nodes still showed only 29 pods capacity
- Expected 110+ pods but got same old limits
- Pods stuck in ContainerCreating with IP allocation failures

**Discovery**:
```
Node                    Instance Type    Pod Capacity
ip-10-0-3-129          c3.4xlarge       234 ✓ (Prefix delegation working!)
ip-10-0-3-205          m5d.large        29  ✗ (Small instance, limited ENIs)
ip-10-0-3-88           m5d.large        29  ✗ (Small instance, limited ENIs)
```

**Root Cause**:
- Prefix delegation requires multiple ENIs (Elastic Network Interfaces)
- **Large instances** (c3.4xlarge): 8 ENIs → can allocate many prefixes → 234 pods
- **Small instances** (m5d.large): 3 ENIs → limited prefixes → only 29 pods
- Karpenter chose small instances to save cost (Spot pricing)

**Impact**: 
- c3.4xlarge: 234 pods available
- m5d.large (×2): 58 pods available
- Total: 292 pods (but small nodes were problematic)

---

### 4. **The Kubernetes Cascade Failure - DNS Breakdown**

**Problem** (The Big One):
- CoreDNS pods stuck in ContainerCreating
- wp-k8s-service couldn't resolve Redis: "Error -3 Temporary failure in name resolution"
- Entire cluster became non-functional
- Workers couldn't connect to Redis → no clones could be processed
- Classic catch-22: Nodes looked fine, but AWS VPC CNI was failing

**Root Cause Chain**:
1. Cycled old nodes (35 pod limit) to enable prefix delegation
2. Karpenter created NEW nodes but chose small m5d.large instances
3. Small nodes got IP allocation failures even with prefix delegation enabled
4. CoreDNS scheduled on small nodes → couldn't get IPs → stuck in ContainerCreating
5. No DNS → entire cluster broken → no pods could resolve service names

**Errors Seen**:
```
CoreDNS: Failed to create pod sandbox: failed to assign an IP address to container
wp-k8s-service: Error -3 connecting to redis-master.wordpress-staging.svc.cluster.local
Warm pool controller: Failed to get queue depth (DNS resolution failed)
```

**Why Small Nodes Failed**:
- Even with prefix delegation enabled
- AWS CNI struggled on small instances due to:
  - Limited ENI count (only 3 ENIs on m5d.large)
  - WARM_IP_TARGET settings too high for small ENI capacity
  - IMDS latency during node churn

**Solution**: Force Karpenter to Use Only Large Instances

**Configuration Change**:
```yaml
# NodePool: general-purpose
spec:
  template:
    spec:
      requirements:
        - key: karpenter.k8s.aws/instance-size
          operator: NotIn
          values: ["nano", "micro", "small", "medium", "large"]
```

**Command Used**:
```bash
kubectl patch nodepool general-purpose --type='json' -p='[
  {
    "op": "add",
    "path": "/spec/template/spec/requirements/-",
    "value": {
      "key": "karpenter.k8s.aws/instance-size",
      "operator": "NotIn",
      "values": ["nano", "micro", "small", "medium", "large"]
    }
  }
]'
```

**Result**:
- Karpenter now only provisions xlarge or larger instances
- Ensures sufficient ENI capacity for prefix delegation
- Prevents small-node IP allocation failures

**Recovery Steps**:
1. Updated NodePool to exclude small instances
2. Deleted pods from small nodes to trigger Karpenter provisioning
3. CoreDNS rescheduled to c3.4xlarge node → started successfully
4. DNS came back online
5. Restarted wp-k8s-service to pick up working DNS
6. Cluster fully operational again

**Files Modified**:
- Karpenter NodePool: `general-purpose`

---

### 5. **Warm Pool Over-Scaling**

**Problem**:
- Warm pool controller scaled to 43 pods instead of max 20
- Configuration says `max_burst_pods = 20`
- Contributed to IP exhaustion

**Root Cause** (Suspected):
- Race condition in controller loop
- Multiple loops running simultaneously
- Pods created before previous ones counted

**Status**: 
- Not fully resolved yet
- Needs rate limiting or pod creation cooldown
- Lower priority now that instance size is fixed

**Configuration**:
```python
# warm_pool_controller.py
self.min_warm_pods = 2
self.max_warm_pods = 4
self.max_burst_pods = 20  # Should cap here, but went to 43
```

---

### 6. **Bulk Clone Script - Source Configuration**

**Problem**:
- User wanted to clone 50% from betaweb.ai and 50% from bonnel.ai
- Script only supported single source

**Solution**: Modified script to alternate between sources
```python
SOURCES = [
    {
        "url": "https://betaweb.ai",
        "username": "Charles@toctoc.com.au",
        "password": "6(4b`Nde1i_D",
    },
    {
        "url": "https://bonnel.ai",
        "username": "charles@toctoc.com.au",
        "password": "6(4b`Nde1i_D",
    },
]

# Alternate between sources
source_index = (i - 1) % 2
result = create_clone(clone_id, source_index)
```

**Files Modified**:
- `scripts/bulk-create-clones.py`

---

## Summary of All Changes

### Code Changes
1. **warm_pool_controller.py** (Line 60): Fixed Redis key format
2. **bulk-create-clones.py**: Added multi-source support (50% betaweb, 50% bonnel)

### Infrastructure Changes
1. **VPC CNI Configuration**:
   - Enabled prefix delegation: `ENABLE_PREFIX_DELEGATION=true`
   - Set warm prefix target: `WARM_PREFIX_TARGET=1`
   - Updated ConfigMap: `warm-prefix-target=1`

2. **Karpenter NodePool** (general-purpose):
   - Added instance size exclusion
   - Blocks: nano, micro, small, medium, large
   - Forces: xlarge, 2xlarge, 4xlarge, etc.

3. **Docker Images**:
   - Built: `wp-k8s-service:warmpool-fix-20260227-093044`
   - Pushed to: `044514005641.dkr.ecr.us-east-1.amazonaws.com`

### Cluster State
- **Before**: 35 pods/node, single source cloning, broken DNS
- **After**: 234 pods/node (large instances), dual source cloning, working DNS

---

## Current Capacity

**Nodes** (as of fix):
- 1× c3.4xlarge: 234 pods
- 2× new xlarge+ instances: TBD (will be provisioned)
- **Total capacity**: 292+ pods

**Resource Usage**:
- 30 clones × 2 containers = 60 pods
- 20 warm pool pods (max burst) = 20 pods
- System pods (dns, monitoring, etc) = ~40 pods
- **Total needed**: ~120 pods

**Margin**: 172+ pods available for scaling

---

## Lessons Learned

1. **Always check instance type when using prefix delegation**
   - Prefix delegation only works well on large instances with many ENIs
   - Small instances can't fully utilize prefix delegation

2. **Karpenter will optimize for cost, not reliability**
   - Default behavior: choose cheapest instance
   - Must explicitly constrain instance sizes for critical workloads

3. **DNS is a single point of failure**
   - CoreDNS on bad nodes = entire cluster down
   - Always ensure CoreDNS can schedule on reliable nodes

4. **IP exhaustion symptoms can be misleading**
   - "Out of IPs" might mean subnet exhaustion OR node ENI exhaustion
   - Check both subnet capacity AND node instance type

5. **Cascade failures are real**
   - Cycling nodes → small instances → IP failures → DNS down → everything broken
   - Must plan entire sequence, not just first step

---

## Next Steps

1. ✅ Clean slate - delete all warm pods and test clones
2. ⏳ Run 30-clone test with both sources (betaweb.ai + bonnel.ai)
3. ⏳ Monitor warm pool scaling (should stay ≤20 pods)
4. ⏳ Verify performance: 30 clones in ~4-5 minutes
5. ⏳ Document final results

---

## Quick Reference Commands

### Check Queue Depth
```bash
kubectl exec -n wordpress-staging redis-master-0 -- redis-cli -a $(kubectl get secret -n wordpress-staging redis -o jsonpath='{.data.redis-password}' | base64 -d) LLEN dramatiq:clone-queue
```

### Check Node Capacity
```bash
kubectl get nodes -o custom-columns=NAME:.metadata.name,INSTANCE:.metadata.labels.node\\.kubernetes\\.io/instance-type,PODS:.status.allocatable.pods
```

### Check Subnet IPs
```bash
aws ec2 describe-subnets --subnet-ids subnet-05dc887631fa204ba --region us-east-1 --query 'Subnets[0].AvailableIpAddressCount'
```

### Restart wp-k8s-service
```bash
kubectl rollout restart deployment wp-k8s-service -n wordpress-staging
```

### Test DNS
```bash
kubectl run test-dns --image=busybox:1.28 --rm -it --restart=Never -- nslookup redis-master.wordpress-staging.svc.cluster.local
```
