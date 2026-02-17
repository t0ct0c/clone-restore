# Spec: wp-k8s-service Deployment

## Overview

Deploy the WordPress Clone/Restore management service (wp-k8s-service) to Kubernetes, replacing the EC2-based wp-setup-service. This service orchestrates clone creation, browser automation, and restore operations.

**Reference**: See [KUBERNETES_IMPLEMENTATION_GUIDE.md](../../../../KUBERNETES_IMPLEMENTATION_GUIDE.md) for detailed implementation steps.

## Current EC2 Implementation

The existing `wp-setup-service` running on EC2 (`13.222.20.138:8000`) provides:
- `/clone` endpoint - Creates WordPress clones with auto-provisioning
- `/restore` endpoint - Restores clones to production with browser automation
- `/provision` endpoint - Provisions ephemeral EC2 containers
- `/health` endpoint - Health check
- `/setup` endpoint - Sets up WordPress sites with migrator plugin

**Key Dependencies**:
- Playwright/Camoufox for browser automation
- boto3 for AWS API calls (EC2, ELBv2, ECR)
- EC2Provisioner class (905 lines of SSH/Docker/Nginx/ALB management)

## ADDED Requirements

### REQ-WPK8S-001: Service Deployment
**Priority**: Critical
**Category**: Deployment

The system MUST deploy wp-k8s-service as a Kubernetes Deployment with high availability.

#### Scenario: Service deploys with multiple replicas
**Given** wp-k8s-service Docker image is available in ECR
**When** Deployment manifest is applied to `wordpress-migration-system` namespace
**Then** 2 replicas are created in production namespace
**And** pods are spread across multiple availability zones
**And** health checks pass on `/health` endpoint
**And** service account has IRSA annotation for AWS API access

### REQ-WPK8S-002: Browser Automation Support
**Priority**: Critical
**Category**: Functionality

The system MUST support Playwright/Camoufox browser automation for WordPress admin interactions.

#### Scenario: Browser automation works in container
**Given** wp-k8s-service pod is running
**When** `/setup` endpoint is called with WordPress credentials
**Then** Playwright launches headless browser
**And** browser automation logs into WordPress admin
**And** plugin is uploaded and activated successfully
**And** API key is retrieved from settings page

#### Scenario: Browser automation handles bot protection
**Given** target WordPress site has SiteGround security
**When** browser automation attempts login
**Then** Camoufox anti-detection features prevent blocking
**And** login succeeds within 60 seconds timeout
**And** session cookies are captured for subsequent requests

### REQ-WPK8S-003: KRO/Kubernetes Provisioner
**Priority**: Critical
**Category**: Provisioning

The system MUST replace EC2Provisioner with KROProvisioner for clone management.

#### Scenario: Clone creation uses Kubernetes API
**Given** `/clone` endpoint receives valid request
**When** clone provisioning starts
**Then** KROProvisioner creates WordPressClone custom resource
**And** KRO orchestrates Secret, Job, Service, Ingress creation
**And** ALB listener rule is created via AWS Load Balancer Controller
**And** clone URL is returned within 5 minutes

#### Scenario: Clone deletion cleans up all resources
**Given** WordPress clone exists with clone-id `clone-20260208-143022`
**When** TTL expires or manual deletion is triggered
**Then** KROProvisioner deletes WordPressClone resource
**And** KRO cascades deletion to child resources
**And** ALB listener rule is removed
**And** no orphaned resources remain

### REQ-WPK8S-004: Ingress and Load Balancing
**Priority**: High
**Category**: Networking

The system MUST expose wp-k8s-service via AWS ALB using Kubernetes Ingress.

#### Scenario: Service accessible via ALB
**Given** wp-k8s-service Deployment is running
**And** Ingress resource is created with ALB annotations
**When** HTTP request is sent to ALB DNS name
**Then** request is routed to wp-k8s-service pods
**And** SSL termination occurs at ALB
**And** response is returned successfully

### REQ-WPK8S-005: Horizontal Pod Autoscaling
**Priority**: Medium
**Category**: Auto-scaling

The system MUST auto-scale based on CPU and memory utilization.

#### Scenario: Service scales up under load
**Given** HPA is configured for wp-k8s-service
**And** CPU utilization exceeds 70% for 2 minutes
**When** HPA evaluates scaling decision
**Then** replica count increases (up to max 10)
**And** new pods are scheduled and become ready
**And** load is distributed across all replicas

#### Scenario: Service scales down during low traffic
**Given** CPU utilization is below 30% for 5 minutes
**When** HPA evaluates scaling decision
**Then** replica count decreases (down to min 2)
**And** pods are gracefully terminated
**And** in-flight requests complete before termination

### REQ-WPK8S-006: Configuration Management
**Priority**: High
**Category**: Configuration

The system MUST use Kubernetes-native configuration management.

#### Scenario: Environment variables from ConfigMaps and Secrets
**Given** wp-k8s-service pod starts
**When** environment variables are injected
**Then** `AWS_REGION` comes from ConfigMap
**And** `ALB_LISTENER_ARN` comes from Secret
**And** `PLUGIN_ZIP_PATH` points to mounted ConfigMap volume
**And** no hardcoded credentials in container image

---

## Container Specification

### Dockerfile Requirements
```dockerfile
# Base image with Python 3.11
FROM python:3.11-slim

# System dependencies for Playwright
- google-chrome-stable or chromium
- fonts for Unicode rendering
- dbus for browser communication

# Python dependencies
- fastapi
- uvicorn
- playwright
- camoufox
- kubernetes
- boto3
- pydantic
- loguru
- opentelemetry-*

# Application code
COPY app/ /app/
WORKDIR /app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Resource Requirements
```yaml
resources:
  requests:
    memory: "512Mi"
    cpu: "250m"
  limits:
    memory: "2Gi"     # Browser automation is memory-intensive
    cpu: "1000m"
```

### Health Checks
```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 30
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3

readinessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 5
  timeoutSeconds: 3
  failureThreshold: 3
```

---

## Integration Points

### Related Capabilities
- `kubernetes-infrastructure`: Provides EKS cluster and IRSA roles
- `kro-orchestration`: KRO ResourceGroups for WordPress clones
- `ack-integration`: ACK for RDS database management
- `gitops-cicd`: Argo CD deploys this service

### Modified Components
- **NEW**: `/kubernetes/wp-k8s-service/` - New service codebase
- **NEW**: `/kubernetes/wp-k8s-service/app/kro_provisioner.py` - KRO-based provisioner
- **NEW**: `/kubernetes/wp-k8s-service/Dockerfile` - Container image
- **NEW**: `/kubernetes/manifests/base/wp-k8s-service/` - Kubernetes manifests
- **UNCHANGED**: `/custom-wp-migrator-poc/wp-setup-service/` - EC2 version preserved for rollback

### API Compatibility
The wp-k8s-service MUST maintain API compatibility with wp-setup-service:

| Endpoint | Method | Request Body | Response |
|----------|--------|--------------|----------|
| `/clone` | POST | `{source: {url, username, password}}` | `{success, clone_url, wordpress_username, wordpress_password, api_key}` |
| `/restore` | POST | `{source: {...}, target: {...}, preserve_plugins, preserve_themes}` | `{success, message, integrity}` |
| `/setup` | POST | `{url, username, password, role}` | `{success, api_key, plugin_status}` |
| `/health` | GET | - | `{status: "healthy"}` |

---

## Non-Functional Requirements

### Performance
- Clone creation time: < 5 minutes (matches EC2 version)
- API response time: < 500ms for health checks
- Browser automation: < 120 seconds per WordPress site

### Reliability
- 99.9% uptime for clone/restore operations
- Graceful degradation if browser automation fails
- Automatic pod restart on failure

### Security
- No hardcoded credentials in images or manifests
- IRSA for AWS API access
- Network policies restrict pod-to-pod communication
- Secrets encrypted at rest in etcd

### Observability
- OpenTelemetry tracing for all API calls
- Structured JSON logging with trace IDs
- Prometheus metrics for request latency and error rates

---

## Test Cases

### Unit Tests
1. KROProvisioner.create_clone() creates WordPressClone resource
2. KROProvisioner._wait_for_clone_ready() polls status correctly
3. KROProvisioner.delete_clone() removes resources

### Integration Tests
1. Full clone workflow: `/clone` → WordPressClone → accessible URL
2. Restore workflow: `/restore` → browser automation → content migrated
3. TTL cleanup: Clone expires → resources deleted

### Load Tests
1. 10 concurrent clone requests → all succeed within 10 minutes
2. 100 clones exist simultaneously → system remains stable
3. HPA scales from 2 to 6 replicas under load

---

## Migration Path

### Phase 1: Parallel Deployment
1. Deploy wp-k8s-service to staging namespace
2. Test all endpoints with staging ALB
3. Verify clone creation works with KRO

### Phase 2: Traffic Splitting
1. Deploy wp-k8s-service to production namespace
2. Route 10% traffic to Kubernetes via weighted ALB rules
3. Monitor for errors, gradually increase to 100%

### Phase 3: EC2 Decommission
1. Route 100% traffic to Kubernetes
2. Monitor for 48 hours
3. Decommission EC2 wp-setup-service
4. Archive EC2 code for rollback reference
