# Kubernetes Deployment Plan for WordPress Clone/Restore System

**Based on:** `feat/repair-endpoints` branch analysis  
**Date:** 2026-02-08  
**Target Environment:** EKS Cluster (wp-clone-restore, version 1.35)

## Executive Summary

This document outlines a plan to migrate the existing WordPress Clone/Restore system from EC2-based Docker containers to Kubernetes. The current system (documented in `OPERATIONAL_MEMORY.md`) is fully functional but runs on EC2 instances with manual Docker management. Kubernetes will provide better scalability, reliability, and automation.

## Current Architecture Analysis

### ✅ **Working Components (from OPERATIONAL_MEMORY.md):**

1. **Management Server** (EC2: `13.222.20.138`)
   - `wp-setup-service`: FastAPI service with browser automation (Playwright/Camoufox)
   - Orchestrates clone/restore operations
   - Port 8000

2. **Target Server** (EC2: `10.0.13.72`)
   - WordPress clone containers (dynamic ports: 8021, 8022, etc.)
   - Nginx reverse proxy for path-based routing
   - MySQL containers (one per clone)

3. **Load Balancer Infrastructure**
   - ALB: `wp-targets-alb-1392351630.us-east-1.elb.amazonaws.com`
   - Custom domain: `clones.betaweb.ai` (HTTPS with ACM cert)
   - Path-based routing: `/clone-YYYYMMDD-HHMMSS/*`
   - Dynamic ALB listener rule creation per clone

4. **Core Services**
   - WordPress containers with custom migrator plugin
   - MySQL databases (per clone)
   - Nginx reverse proxy
   - Browser automation service

### 🔄 **Current Workflow:**
```
Source WordPress → Clone endpoint → EC2 container → ALB routing → Clone accessible at https://clones.betaweb.ai/clone-XXX/
Clone → Restore endpoint → Production WordPress (with browser automation re-activation)
```

## Kubernetes Migration Strategy

### Phase 1: Foundation Setup

#### 1.1 **Namespace Structure**
```yaml
# Create dedicated namespaces
- wordpress-migration-system (management services)
- wordpress-clones (ephemeral clone containers)
- wordpress-databases (MySQL instances)
- monitoring (observability stack)
```

#### 1.2 **Storage Strategy**
- **Persistent Volumes**: For WordPress uploads and MySQL data
- **Storage Classes**: Use EBS CSI driver for dynamic provisioning
- **Backup Strategy**: Implement Velero for disaster recovery

#### 1.3 **Networking**
- **Ingress Controller**: AWS Load Balancer Controller (already configured via Terraform)
- **Service Mesh**: Consider Linkerd for service-to-service communication
- **DNS**: ExternalDNS for automatic DNS record management

### Phase 2: Service Migration

#### 2.1 **wp-setup-service Deployment**
```yaml
# Key requirements:
- FastAPI application (port 8000)
- Playwright/Camoufox for browser automation
- Access to AWS APIs (EC2, ELBv2, ECR)
- Persistent storage for plugin ZIP files
- Environment variables for configuration
```

**Challenges:**
- Browser automation in containers requires proper display server
- AWS credentials management
- Large container image with browser dependencies

#### 2.2 **WordPress Clone Containers**
```yaml
# Each clone needs:
- WordPress container with custom migrator plugin
- MySQL container (or RDS instance)
- Unique port assignment
- Persistent storage for uploads
- Health checks
- Resource limits
```

**Optimization:**
- Use init containers for plugin injection
- Consider SQLite instead of MySQL for ephemeral clones
- Implement sidecar for log aggregation

#### 2.3 **Reverse Proxy (Nginx Replacement)**
```yaml
# Replace EC2 Nginx with:
- Ingress resources per clone
- Path-based routing via Ingress annotations
- SSL termination at ALB level
- Header manipulation for WordPress
```

### Phase 3: ALB Integration

#### 3.1 **Dynamic Ingress Creation**
```python
# Strategy: Modify wp-setup-service to create Kubernetes Ingress resources
# Instead of: EC2Provisioner._create_alb_listener_rule()
# Use: k8s_client.create_namespaced_ingress()

# Example flow:
1. Clone request received
2. Create WordPress Deployment + Service
3. Create Ingress with path: /clone-YYYYMMDD-HHMMSS/*
4. Ingress creates ALB listener rule automatically via AWS Load Balancer Controller
```

#### 3.2 **ALB Configuration**
- Reuse existing ALB (`wp-targets-alb`)
- Update Ingress annotations to target correct ALB
- Maintain HTTPS configuration with ACM cert
- Implement proper security groups

### Phase 4: Database Strategy

#### 4.1 **Options Analysis**
1. **Per-Pod MySQL**: Simple but resource-intensive
2. **Shared RDS**: Cost-effective but requires connection management
3. **SQLite**: Lightweight for ephemeral clones (current approach)
4. **MySQL Operator**: Automated management but complex

**Recommendation:** Start with SQLite (current approach) for simplicity, migrate to RDS later.

#### 4.2 **Data Persistence**
- WordPress uploads: PersistentVolumeClaims
- MySQL data: PersistentVolumeClaims or RDS
- Plugin files: ConfigMaps

### Phase 5: Observability & Monitoring

#### 5.1 **Logging**
- FluentBit → CloudWatch Logs
- Structured logging with OpenTelemetry
- Per-clone log aggregation

#### 5.2 **Metrics**
- Prometheus scraping
- WordPress-specific metrics
- Resource utilization monitoring

#### 5.3 **Tracing**
- Continue OpenTelemetry integration
- Jaeger for distributed tracing
- Performance monitoring

## Implementation Roadmap

### Week 1-2: Foundation & wp-setup-service
1. Create Kubernetes namespaces and RBAC
2. Deploy wp-setup-service with browser automation
3. Test basic API endpoints
4. Implement Kubernetes client in wp-setup-service

### Week 3-4: WordPress Clone Deployment
1. Create WordPress Deployment templates
2. Implement dynamic resource creation
3. Test single clone creation
4. Verify ALB integration

### Week 5-6: Database & Storage
1. Implement SQLite/MySQL strategy
2. Configure persistent storage
3. Test data persistence
4. Implement backup procedures

### Week 7-8: Migration & Testing
1. Gradual migration from EC2 to Kubernetes
2. End-to-end testing
3. Performance benchmarking
4. Documentation and runbooks

## Technical Specifications

### Container Images
```dockerfile
# wp-setup-service
FROM python:3.11-slim
# Install Playwright, FastAPI, AWS SDK, Kubernetes client

# wordpress-clone
FROM wordpress:latest
# Add custom migrator plugin, WP-CLI, must-use plugins
```

### Resource Requirements
```yaml
# wp-setup-service
resources:
  requests:
    memory: "512Mi"
    cpu: "250m"
  limits:
    memory: "2Gi"
    cpu: "1000m"

# wordpress-clone
resources:
  requests:
    memory: "256Mi"
    cpu: "100m"
  limits:
    memory: "1Gi"
    cpu: "500m"
```

### Environment Variables
```yaml
# wp-setup-service
env:
  - name: KUBECONFIG
    value: /var/run/secrets/kubernetes.io/serviceaccount
  - name: AWS_REGION
    value: us-east-1
  - name: ALB_DNS
    value: clones.betaweb.ai
  - name: ALB_LISTENER_ARN
    valueFrom:
      secretKeyRef:
        name: alb-config
        key: listener-arn
```

## Risk Assessment & Mitigation

### High Risk
1. **Browser automation in containers**: May require Xvfb or headless Chrome adjustments
   - **Mitigation**: Test extensively in staging, have fallback to EC2

2. **ALB integration complexity**: Dynamic Ingress creation
   - **Mitigation**: Implement gradual rollout, monitor ALB rules

3. **Data migration**: Moving from EC2 volumes to Kubernetes PVs
   - **Mitigation**: Dual-write during migration, comprehensive backups

### Medium Risk
1. **Resource contention**: Multiple clones on same node
   - **Mitigation**: Resource limits, node affinity, pod anti-affinity

2. **Service discovery**: WordPress containers finding MySQL
   - **Mitigation**: Kubernetes Services, DNS-based discovery

3. **Security**: AWS credentials in containers
   - **Mitigation**: IAM roles for service accounts (IRSA)

## Success Criteria

### Phase 1 Complete
- [ ] wp-setup-service running in Kubernetes
- [ ] Basic API endpoints responding
- [ ] Kubernetes client integrated
- [ ] No regression from EC2 version

### Phase 2 Complete
- [ ] Single WordPress clone deployable via API
- [ ] Clone accessible via ALB
- [ ] REST API functional on clone
- [ ] Basic clone-to-production restore working

### Phase 3 Complete
- [ ] Multiple concurrent clones supported
- [ ] Resource isolation between clones
- [ ] Automated cleanup of expired clones
- [ ] Performance matches or exceeds EC2 version

### Phase 4 Complete
- [ ] Full migration from EC2 to Kubernetes
- [ ] Zero-downtime for existing clones
- [ ] Comprehensive monitoring
- [ ] Production-ready documentation

## Next Steps

### Immediate Actions (Day 1)
1. **Review this plan** with stakeholders
2. **Set up development environment** with KinD or minikube
3. **Create proof-of-concept** for wp-setup-service in Kubernetes
4. **Test browser automation** in container environment

### Short-term (Week 1)
1. **Implement Kubernetes client** in wp-setup-service
2. **Create Helm charts** for WordPress clones
3. **Test ALB integration** with simple Ingress
4. **Document migration procedures**

### Medium-term (Month 1)
1. **Gradual migration** of non-critical clones
2. **Performance testing** and optimization
3. **Implement monitoring** and alerting
4. **Create rollback plan**

## Appendix

### A. Current EC2 to Kubernetes Mapping
```
EC2 Component          → Kubernetes Equivalent
-------------------    → ---------------------
wp-setup-service       → Deployment + Service
WordPress containers   → Deployments (per clone)
MySQL containers       → StatefulSets or RDS
Nginx reverse proxy    → Ingress + ALB
EC2 provisioning       → Kubernetes API calls
ALB rule creation      → Ingress creation
```

### B. Required Kubernetes Resources
```bash
# Custom Resource Definitions (if needed)
- CloneRequest CRD (for declarative clone management)
- RestoreJob CRD (for restore operations)

# Controllers/Operators
- WordPress Clone Operator (long-term)
- ALB Rule Controller (short-term)
```

### C. Testing Strategy
1. **Unit tests**: API endpoints, Kubernetes client
2. **Integration tests**: Clone creation, ALB routing
3. **End-to-end tests**: Full clone → restore workflow
4. **Load tests**: Multiple concurrent clones
5. **Failure tests**: Node failures, network partitions

### D. Rollback Plan
1. **Phase 1 rollback**: Revert to EC2 wp-setup-service
2. **Phase 2 rollback**: Keep EC2 clones, pause Kubernetes deployment
3. **Phase 3 rollback**: Dual-run both systems
4. **Complete rollback**: Redirect traffic back to EC2 ALB

---

**Document Status**: Draft v1.0  
**Last Updated**: 2026-02-08  
**Author**: Analysis of feat/repair-endpoints branch  
**Reviewers**: [To be assigned]