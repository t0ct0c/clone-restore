# Tasks: MySQL Migration and Observability Infrastructure

## Phase 1: MySQL Infrastructure (Priority: CRITICAL)

### 1.1 Update EC2 User Data for MySQL Container
- [ ] Add MySQL 8.0 container to `ec2-user-data.sh`
  - Generate root password via Terraform random_password
  - Configure persistent volume at `/var/lib/mysql`
  - Set restart policy to `unless-stopped`
  - Add health check (wait for port 3306)
- [ ] Test: Verify MySQL starts on fresh EC2 instance
- [ ] Test: Verify MySQL survives host restart

### 1.2 Update Terraform for MySQL Configuration
- [ ] Add `random_password` resource for MySQL root
- [ ] Pass MySQL root password to user-data via template
- [ ] Add Terraform output for MySQL connection string
- [ ] Test: `terraform apply` succeeds without errors
- [ ] Test: `terraform destroy && terraform apply` recreates cleanly

### 1.3 Update WordPress Docker Image
- [ ] Remove SQLite plugin from `wordpress-target-image/Dockerfile`
- [ ] Remove SQLite dropin file installation
- [ ] Keep standard WordPress with MySQL support
- [ ] Build and tag as `wordpress-mysql:latest`
- [ ] Push to ghcr.io/t0ct0c/wordpress-migrator:mysql
- [ ] Test: Container starts and connects to MySQL

### 1.4 Update EC2 Provisioner for Database Management
- [ ] Add `_create_mysql_database()` method to EC2Provisioner
  - Execute `CREATE DATABASE wp_{customer_id}`
  - Execute `CREATE USER` with generated password
  - Execute `GRANT ALL` on database
- [ ] Update `_start_container()` to call database creation
- [ ] Pass MySQL env vars to WordPress container:
  - `WORDPRESS_DB_HOST=host.docker.internal:3306`
  - `WORDPRESS_DB_NAME=wp_{customer_id}`
  - `WORDPRESS_DB_USER=wp_{customer_id}`
  - `WORDPRESS_DB_PASSWORD={generated}`
- [ ] Update `_schedule_cleanup()` to drop database on TTL
- [ ] Test: Provision creates database successfully
- [ ] Test: WordPress connects and creates tables
- [ ] Test: TTL cleanup drops database

### 1.5 Update Import Plugin for MySQL-to-MySQL
- [ ] Remove SQLite detection from `class-importer.php`
- [ ] Remove `truncate_all_tables()` SQLite-specific logic
- [ ] Use standard MySQL `DROP TABLE` approach
- [ ] Remove SQLite-specific permission fixes
- [ ] Remove wp-cron disable hack (no longer needed)
- [ ] Test: Import MySQL dump to MySQL target
- [ ] Test: No "readonly database" errors

### 1.6 Integration Testing
- [ ] Deploy updated infrastructure to staging
- [ ] Create test clone from Railway source
- [ ] Verify: Images load correctly
- [ ] Verify: No database errors in logs
- [ ] Verify: Import completes in <2 minutes
- [ ] Load test: 5 concurrent clones
- [ ] Test: Old SQLite clones age out cleanly

## Phase 2: Observability Infrastructure (Priority: HIGH)

### 2.1 Create Observability Terraform Module
- [ ] Create `infra/observability/` directory
- [ ] Write `main.tf`:
  - EC2 t3.small instance resource
  - Security group (allow 3100 from wp-targets, 3000 from admin)
  - IAM instance profile
  - User data script
- [ ] Write `variables.tf`:
  - `vpc_id` (from wp-targets output)
  - `subnet_ids`
  - `wp_targets_sg_id` (for Loki ingress)
  - `admin_cidr` (for Grafana access)
  - `grafana_admin_password` (sensitive)
- [ ] Write `outputs.tf`:
  - `loki_endpoint` (http://{private_ip}:3100)
  - `grafana_url` (http://{public_ip}:3000)
- [ ] Test: `terraform init && terraform validate`

### 2.2 Create Observability User Data Script
- [ ] Write `infra/observability/user-data.sh`:
  - Install Docker
  - Start Loki container with 7-day retention
  - Start Grafana container with Loki datasource preconfigured
  - Configure Grafana admin password
  - Create WordPress logs dashboard
- [ ] Add health checks for both containers
- [ ] Test: Script runs successfully on EC2

### 2.3 Update wp-targets for Promtail
- [ ] Add Promtail container to `ec2-user-data.sh`:
  - Configure to read Docker logs
  - Set Loki endpoint from Terraform output
  - Add labels: container_name, instance_id, customer_id
- [ ] Pass Loki endpoint to user-data via template
- [ ] Test: Promtail ships logs to Loki
- [ ] Test: Logs appear in Grafana within 10 seconds

### 2.4 Create Grafana Dashboards
- [ ] Create "WordPress Container Logs" dashboard:
  - Panel: Log stream by customer_id
  - Panel: Error count by container
  - Panel: Top 10 error messages
  - Panel: Import duration metrics
- [ ] Export dashboard JSON to repo
- [ ] Configure dashboard provisioning in user-data
- [ ] Test: Dashboard loads on Grafana startup

### 2.5 Integration Testing
- [ ] Deploy observability module to staging
- [ ] Trigger WordPress clone
- [ ] Verify: Logs appear in Grafana
- [ ] Verify: Can filter by customer_id
- [ ] Verify: Search for "error" returns relevant logs
- [ ] Test: Observability survives EC2 restart
- [ ] Test: Can deploy wp-targets without observability

## Phase 3: Documentation and Rollout (Priority: MEDIUM)

### 3.1 Update Documentation
- [ ] Update `README.md` with MySQL architecture
- [ ] Document Terraform module usage
- [ ] Add Grafana access instructions
- [ ] Document rollback procedure
- [ ] Add troubleshooting guide

### 3.2 Production Rollout
- [ ] Tag current version as `sqlite-fallback`
- [ ] Deploy MySQL infrastructure to production
- [ ] Monitor for 24 hours
- [ ] Deploy observability infrastructure
- [ ] Create runbook for common issues
- [ ] Train team on Grafana usage

## Dependencies & Parallelization

### Can Start Immediately (Parallel)
- Task 1.1 (user-data) and 1.3 (Docker image) - no dependencies
- Task 2.1 (Terraform module) - independent from Phase 1

### Must Be Sequential
- 1.1 → 1.2 (Terraform needs user-data file)
- 1.3 → 1.4 (provisioner needs new image)
- 1.4 → 1.5 (plugin needs database available)
- Phase 1 complete → 1.6 (integration testing)
- 2.1 → 2.2 (user-data references Terraform resources)
- 2.2 → 2.3 (wp-targets needs Loki endpoint)

### Critical Path
1.1 → 1.2 → 1.4 → 1.5 → 1.6 (MySQL migration functional)

### Optional Path  
2.1 → 2.2 → 2.3 → 2.4 → 2.5 (Observability adds value but not blocking)

## Validation Checklist

- [ ] Zero "readonly database" errors in production logs
- [ ] 100% clone success rate over 48 hours
- [ ] All infrastructure recreates via `terraform destroy && terraform apply`
- [ ] Grafana shows logs from all containers
- [ ] No performance regression (import time <2min)
- [ ] Documentation complete and tested by team member
