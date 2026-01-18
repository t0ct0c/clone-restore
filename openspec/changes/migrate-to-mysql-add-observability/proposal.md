# Proposal: Migrate to MySQL and Add Observability Infrastructure

## Problem Statement

The current WordPress cloning system uses SQLite for target containers, which causes persistent "readonly database" errors after import. Research confirms the WordPress SQLite integration plugin is in beta with known MySQL-to-SQLite migration issues. Additionally, there's no centralized logging or observability for debugging production issues.

### Current Pain Points
1. **SQLite Readonly Errors**: After importing MySQL data, SQLite enters readonly mode due to connection pooling issues, file locking conflicts, and stale connections
2. **Limited Debugging**: No centralized logs make it difficult to diagnose issues across distributed WordPress containers
3. **Production Instability**: Beta SQLite plugin creates unpredictable behavior in production workloads
4. **Manual Troubleshooting**: Requires SSH into individual containers to check logs

## Proposed Solution

### 1. MySQL Migration
Replace SQLite with a shared MySQL container on each EC2 host. This provides:
- **Compatibility**: Perfect compatibility with source MySQL sites (no translation layer)
- **Reliability**: Production-grade database with proven concurrent write handling  
- **Simplicity**: Standard WordPress configuration everyone understands
- **Performance**: Better handling of multiple concurrent connections

### 2. Observability Infrastructure  
Add separate EC2 instance running Loki + Grafana for centralized logging:
- **Centralized Logs**: All container logs aggregated in one place
- **Search & Filter**: Query logs across all WordPress instances
- **Dashboards**: Pre-built Grafana dashboards for common issues
- **Alerting**: Optional alerts for errors or performance issues

## Success Criteria

- [ ] WordPress clones work without readonly database errors
- [ ] All infrastructure recreatable via `terraform apply`
- [ ] Logs from all containers visible in Grafana
- [ ] Zero manual SSH required for debugging
- [ ] Import time remains under 2 minutes for typical sites

## Risks & Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| MySQL resource usage | Medium | Shared container uses ~200MB, acceptable overhead |
| Migration complexity | High | Phased rollout, thorough testing before production |
| Observability costs | Low | Single t3.small instance, can be disabled if not needed |
| Data loss during migration | Medium | Document backup process, test rollback procedures |

## Dependencies

- Terraform AWS provider ~> 5.0
- Docker on EC2 instances
- MySQL 8.0 official image
- Grafana/Loki official images
- Existing VPC and security group infrastructure

## Timeline Estimate

- MySQL Migration: 2-3 days
- Observability Setup: 1-2 days
- Testing & Documentation: 1 day
- **Total**: 4-6 days
