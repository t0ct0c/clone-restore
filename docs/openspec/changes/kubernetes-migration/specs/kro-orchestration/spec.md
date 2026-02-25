# Spec: KRO Orchestration for WordPress Clones

## Overview
Use KRO (Kube Resource Orchestrator) ResourceGroups to manage WordPress clones as atomic units (Job + Service + Ingress + Secret + RDS).

## ADDED Requirements

### REQ-KRO-001: WordPress Clone ResourceGroup Definition
**Priority**: Critical
**Category**: Orchestration

The system MUST define a KRO ResourceGroup that represents a WordPress clone with all required resources.

#### Scenario: ResourceGroup creates all dependencies automatically
**Given** WordPressClone ResourceGroup is deployed
**When** WordPressClone custom resource is created
**Then** KRO creates Secret for WordPress credentials
**And** KRO creates RDS DBInstance (if `useDedicatedDatabase: true`)
**And** KRO creates Job for WordPress container
**And** KRO creates Service for internal routing
**And** KRO creates Ingress for ALB path-based routing

#### Scenario: KRO enforces dependency order
**Given** WordPressClone custom resource is created with `useDedicatedDatabase: true`
**When** KRO begins provisioning
**Then** Secret is created first
**And** RDS DBInstance waits for Secret to be ready
**And** Job waits for RDS DBInstance status.endpoint.address to be populated
**And** Service waits for Job pod to be running
**And** Ingress is created after Service

### REQ-KRO-002: Clone TTL Management
**Priority**: High
**Category**: Resource Cleanup

The system MUST automatically delete WordPress clones after TTL expires using Kubernetes Job TTL.

#### Scenario: Clone Job deletes after TTL expires
**Given** WordPressClone is created with `ttlSeconds: 7200` (2 hours)
**When** Job completes (or fails)
**And** TTL duration passes
**Then** Kubernetes TTL controller deletes Job
**And** KRO garbage collection deletes dependent resources (Service, Ingress, Secret, RDS)

#### Scenario: User can extend TTL before expiration
**Given** WordPressClone is created with `ttlSeconds: 3600`
**When** user updates `spec.ttlSeconds: 7200` before expiration
**Then** Job's `ttlSecondsAfterFinished` is updated
**And** clone remains active for additional time

### REQ-KRO-003: Clone Status Reporting
**Priority**: High
**Category**: Observability

The system MUST populate WordPressClone status fields with clone URL, credentials, and readiness state.

#### Scenario: Status fields are populated by KRO statusCollectors
**Given** WordPressClone resources are provisioned
**When** all resources are ready
**Then** `status.cloneUrl` contains ALB URL with path prefix
**And** `status.wordpressUsername` contains generated username
**And** `status.wordpressPassword` contains generated password
**And** `status.apiKey` contains migration-master-key
**And** `status.expiresAt` contains TTL expiration timestamp

#### Scenario: Status reflects resource readiness
**Given** WordPressClone is created
**When** RDS is still provisioning
**Then** `status.conditions` includes "RDS provisioning in progress"
**When** RDS is ready
**Then** `status.conditions` includes "RDS ready"
**When** all resources are ready
**Then** `status.ready: true`

### REQ-KRO-004: Database Strategy Configuration
**Priority**: High
**Category**: Cost Optimization

The system MUST support both dedicated RDS per-clone and shared RDS based on `useDedicatedDatabase` flag.

#### Scenario: Production critical clones use dedicated RDS
**Given** WordPressClone is created in `wordpress-production` namespace
**And** `spec.useDedicatedDatabase: true`
**When** KRO provisions resources
**Then** RDS DBInstance is created for this clone
**And** Job's WORDPRESS_DB_HOST points to dedicated RDS endpoint

#### Scenario: Staging clones use shared RDS
**Given** WordPressClone is created in `wordpress-staging` namespace
**And** `spec.useDedicatedDatabase: false`
**When** KRO provisions resources
**Then** RDS DBInstance resource is skipped (includeWhen condition false)
**And** Job's WORDPRESS_DB_HOST points to shared RDS endpoint from environment variable

### REQ-KRO-005: KROProvisioner Python Client
**Priority**: Critical
**Category**: API Integration

The system MUST provide Python client (`kro_provisioner.py`) to create/delete WordPressClone resources via Kubernetes API.

#### Scenario: Python client creates WordPressClone
**Given** wp-k8s-service receives POST /clone request
**When** KROProvisioner.create_clone() is called
**Then** WordPressClone custom resource is created via Kubernetes API
**And** client polls WordPressClone status until ready
**And** client returns clone URL, credentials, expiration time to user

#### Scenario: Python client deletes WordPressClone
**Given** WordPressClone exists
**When** KROProvisioner.delete_clone() is called
**Then** WordPressClone custom resource is deleted
**And** KRO automatically deletes all child resources
**And** RDS database is terminated (if dedicated)

### REQ-KRO-006: Clone ID Generation
**Priority**: Medium
**Category**: Resource Naming

The system MUST generate unique clone IDs with timestamp format for resource naming.

#### Scenario: Clone ID follows timestamp pattern
**Given** POST /clone request is received
**When** KROProvisioner generates clone ID
**Then** ID format is `clone-YYYYMMDD-HHMMSS`
**And** timestamp is UTC
**And** ID is unique (timestamp precision to seconds)

### REQ-KRO-007: Ingress Path-Based Routing
**Priority**: Critical
**Category**: Load Balancing

The system MUST configure Ingress with path-based routing that shares ALB across clones.

#### Scenario: All clones share single ALB via group annotation
**Given** multiple WordPressClone Ingresses are created
**When** Ingress includes annotation `alb.ingress.kubernetes.io/group.name: wordpress-clones`
**Then** all Ingresses share same ALB
**And** each Ingress path rule creates separate ALB listener rule
**And** path `/clone-20260205-143022/*` routes to corresponding Service

---

## Integration Points

### Related Capabilities
- `kubernetes-infrastructure`: Provides EKS cluster where KRO runs
- `ack-integration`: RDS DBInstance is ACK custom resource used by ResourceGroup
- `gitops-cicd`: ResourceGroup definitions deployed via Argo CD

### Modified Components
- **NEW**: `/kubernetes/kro/resourcegroups/wordpress-clone.yaml` - ResourceGroup definition
- **NEW**: `/kubernetes/wp-k8s-service/app/kro_provisioner.py` - Python client for KRO API
- **NEW**: `/kubernetes/bootstrap/scripts/install-kro.sh` - KRO installation script

---

## Non-Functional Requirements

### Performance
- Clone provisioning time < 5 minutes (same as EC2)
- RDS provisioning time < 3 minutes (ACK async operation)
- KRO resource creation < 10 seconds (Secret, Job, Service, Ingress)

### Reliability
- KRO handles partial failures gracefully (rollback on error)
- Dependency ordering prevents race conditions
- TTL cleanup guarantees no orphaned resources

### Code Simplicity
- KROProvisioner.create_clone() < 100 lines (vs ec2_provisioner.py 905 lines)
- Declarative ResourceGroup definition (vs imperative SSH commands)
- No manual ALB API calls (AWS Load Balancer Controller handles it)

### Observability
- WordPressClone status reflects real-time resource state
- KRO events logged to Kubernetes events API
- kubectl describe wordpressclone shows full resource tree
