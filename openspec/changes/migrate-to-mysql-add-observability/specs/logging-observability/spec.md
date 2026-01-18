# Spec: Logging and Observability

## ADDED Requirements

### Requirement: Centralized Logging Infrastructure

The system MUST provide centralized logging using Loki for storage and Grafana for visualization.

#### Scenario: Observability EC2 instance deployed via Terraform
**Given** Terraform infra/observability module  
**When** terraform apply executes  
**Then** t3.small EC2 instance launches in wp-targets VPC  
**And** Loki container starts on port 3100  
**And** Grafana container starts on port 3000  
**And** both containers restart automatically on failure

#### Scenario: Grafana accessible for log queries
**Given** observability instance is running  
**When** user accesses Grafana UI  
**Then** Loki is configured as datasource  
**And** user can query logs by customer_id label  
**And** user can search logs by text content

### Requirement: Log Shipping from WordPress Containers

All WordPress container logs MUST be shipped to Loki in real-time.

#### Scenario: Promtail ships container logs
**Given** a WordPress container is running  
**When** the container writes to stdout/stderr  
**Then** Promtail reads logs from Docker socket  
**And** enriches logs with container_name label  
**And** enriches logs with customer_id extracted from container name  
**And** ships logs to Loki within 5 seconds

#### Scenario: Historical logs queryable in Grafana
**Given** logs shipped for past 24 hours  
**When** user queries Grafana for customer_id="clone-20260116-095447"  
**Then** all logs for that customer are returned  
**And** logs include timestamps and full text  
**And** logs are searchable by error keywords

### Requirement: Security Group Configuration

Loki ingestion MUST be restricted to wp-targets security group.

#### Scenario: wp-target hosts can reach Loki
**Given** observability instance security group  
**When** wp-target host sends logs to Loki port 3100  
**Then** connection succeeds  
**And** logs are ingested

#### Scenario: External traffic blocked
**Given** observability instance security group  
**When** external IP attempts to connect to Loki port 3100  
**Then** connection is denied by security group rules

### Requirement: Terraform-Managed Infrastructure

All observability infrastructure MUST be defined in Terraform for reproducibility.

#### Scenario: Clean recreation via Terraform
**Given** observability infrastructure running  
**When** terraform destroy executes  
**Then** all resources are cleaned up  
**When** terraform apply executes again  
**Then** infrastructure recreates identically  
**And** Grafana dashboards are pre-configured  
**And** Loki retention is set to 7 days

#### Scenario: Observability optional
**Given** wp-targets Terraform module  
**When** deployed without observability module  
**Then** WordPress cloning still works  
**And** logs are available via docker logs command  
**And** no errors occur from missing Loki endpoint

## MODIFIED Requirements

### Requirement: EC2 User Data Configuration

wp-targets user-data script MUST install and configure Promtail.

#### Scenario: Promtail configured on instance launch
**Given** EC2 instance launches from ASG  
**When** user-data script executes  
**Then** Promtail Docker container starts  
**And** configured with Loki endpoint from Terraform output  
**And** configured to scrape Docker logs  
**And** restarts automatically on failure
