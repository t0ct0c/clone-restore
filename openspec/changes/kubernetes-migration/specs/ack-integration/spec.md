# Spec: ACK (AWS Controllers for Kubernetes) Integration

## Overview
Use ACK controllers to manage AWS resources (RDS, IAM) natively from Kubernetes using custom resource definitions (CRDs).

## ADDED Requirements

### REQ-ACK-001: RDS Controller Installation
**Priority**: Critical
**Category**: Infrastructure

The system MUST install ACK RDS controller to manage RDS databases via Kubernetes CRDs.

#### Scenario: RDS controller is deployed via Helm
**Given** EKS cluster is running
**When** `helm install ack-rds-controller` is executed
**Then** RDS controller pod is running in ack-system namespace
**And** RDS CRDs are registered (DBInstance, DBSubnetGroup, DBSecurityGroup)
**And** controller has IRSA role with RDS permissions

#### Scenario: RDS controller watches DBInstance resources
**Given** RDS controller is running
**When** DBInstance custom resource is created
**Then** controller calls AWS RDS API to provision database
**And** controller updates DBInstance status with endpoint address
**And** controller handles DBInstance deletion by calling AWS RDS DeleteDBInstance

### REQ-ACK-002: RDS Database Provisioning
**Priority**: Critical
**Category**: Database Management

The system MUST provision RDS MySQL databases via ACK DBInstance resources.

#### Scenario: DBInstance creates RDS MySQL database
**Given** DBInstance resource is created
**When** ACK RDS controller processes resource
**Then** RDS API creates db.t3.micro instance
**And** MySQL version 8.0.35 is provisioned
**And** 20GB gp3 storage is allocated
**And** database is placed in private subnets via dbSubnetGroupName
**And** security group allows access from EKS worker nodes

#### Scenario: DBInstance status reflects RDS state
**Given** DBInstance is provisioning
**When** RDS database becomes available
**Then** `status.endpoint.address` contains RDS endpoint hostname
**And** `status.endpoint.port` contains 3306
**And** `status.dbInstanceStatus` is "available"
**And** dependent resources can read endpoint from status

### REQ-ACK-003: RDS Subnet Group and Security Group
**Priority**: High
**Category**: Networking

The system MUST create RDS subnet group and security group before provisioning databases.

#### Scenario: DBSubnetGroup spans multiple AZs
**Given** VPC with private subnets exists
**When** DBSubnetGroup resource is created
**Then** subnet group includes subnets from 3 availability zones
**And** RDS databases can be provisioned in any AZ

#### Scenario: Security group allows EKS worker node access
**Given** Security group for RDS is created
**When** ingress rule is added
**Then** rule allows TCP port 3306 from EKS worker node security group
**And** RDS databases are accessible from Kubernetes pods

### REQ-ACK-004: Shared RDS for Staging
**Priority**: High
**Category**: Cost Optimization

The system MUST provision a single shared RDS instance for all staging clones.

#### Scenario: Staging namespace uses shared RDS
**Given** staging namespace exists
**When** first staging clone is created
**Then** DBInstance `wordpress-staging-shared-rds` is created (if not exists)
**And** database is db.t3.small (sufficient for multiple schemas)
**And** all staging clones connect to this RDS instance with separate database names

### REQ-ACK-005: Per-Clone RDS for Production
**Priority**: High
**Category**: Data Isolation

The system MUST support per-clone RDS databases for production critical clones.

#### Scenario: Production clone uses dedicated RDS
**Given** WordPressClone has `spec.useDedicatedDatabase: true`
**When** clone is created in production namespace
**Then** DBInstance `{clone-id}-db` is created
**And** database is isolated (no shared resources)
**And** clone connects to dedicated RDS endpoint

### REQ-ACK-006: RDS Cleanup on Clone Deletion
**Priority**: High
**Category**: Resource Management

The system MUST delete RDS databases when WordPressClone is deleted.

#### Scenario: DBInstance is deleted with clone
**Given** WordPressClone with dedicated RDS is deleted
**When** KRO garbage collection runs
**Then** DBInstance resource is deleted
**And** ACK RDS controller calls DeleteDBInstance API
**And** RDS database is terminated without final snapshot (dev/test databases)

### REQ-ACK-007: IAM Controller for IRSA
**Priority**: Medium
**Category**: Security

The system SHOULD install ACK IAM controller to manage IAM roles for service accounts.

#### Scenario: IAM controller creates roles for IRSA
**Given** ACK IAM controller is installed
**When** Role custom resource is created for wp-k8s-service
**Then** IAM role is provisioned with trust policy for OIDC provider
**And** role ARN is annotated on ServiceAccount
**And** pods assume role automatically

---

## Integration Points

### Related Capabilities
- `kubernetes-infrastructure`: Provides IRSA roles for ACK controllers
- `kro-orchestration`: KRO ResourceGroups reference ACK DBInstance CRD

### Modified Components
- **NEW**: `/kubernetes/bootstrap/terraform/ack-controllers.tf` - ACK controller installation via Helm
- **NEW**: `/kubernetes/bootstrap/terraform/rds-prerequisites.yaml` - DBSubnetGroup, Security Groups
- **NEW**: `/kubernetes/kro/resourcegroups/wordpress-clone.yaml` - References ACK DBInstance

---

## Non-Functional Requirements

### Performance
- RDS provisioning via ACK < 3 minutes (AWS API latency)
- DBInstance status updates every 30 seconds during provisioning
- ACK controller reconciliation loop < 5 seconds

### Reliability
- ACK controller retries failed AWS API calls with exponential backoff
- DBInstance status reflects real AWS state (not cached)
- Deletion of DBInstance guarantees AWS RDS cleanup (no orphaned databases)

### Security
- ACK controllers use IRSA (no hardcoded credentials)
- RDS master password stored in Kubernetes Secret
- RDS instances in private subnets (no public access)
- Security groups enforce least-privilege access

### Cost
- Shared RDS for staging reduces cost (1 db.t3.small vs 10 db.t3.micro)
- Per-clone RDS for critical production clones ensures isolation
- skipFinalSnapshot: true prevents snapshot storage costs for ephemeral clones
