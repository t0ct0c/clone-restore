# Design: MySQL Migration and Observability Infrastructure

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                         AWS VPC                              │
│                                                              │
│  ┌──────────────────┐         ┌─────────────────────────┐  │
│  │ Target EC2 Host  │         │ Observability EC2       │  │
│  │                  │         │                          │  │
│  │  ┌────────────┐  │         │  ┌──────────────────┐  │  │
│  │  │   MySQL    │◄─┼─────────┼──┤  Grafana :3000   │  │  │
│  │  │   :3306    │  │         │  └──────────────────┘  │  │
│  │  └────────────┘  │         │  ┌──────────────────┐  │  │
│  │  ┌────────────┐  │         │  │  Loki :3100      │◄─┼──┐
│  │  │WordPress 1 │──┼─logs────┼─►└──────────────────┘  │  │
│  │  │  :8001     │  │         │                          │  │
│  │  └────────────┘  │         └─────────────────────────┘  │
│  │  ┌────────────┐  │                                       │
│  │  │WordPress 2 │──┼─logs──────────────────────────────────┘
│  │  │  :8002     │  │
│  │  └────────────┘  │
│  └──────────────────┘
│          │
│     ┌────▼─────┐
│     │   ALB    │
│     └──────────┘
└─────────────────────────────────────────────────────────────┘
```

## Key Design Decisions

### 1. Shared MySQL Container per EC2 Host

**Decision**: Run one MySQL container per EC2 host, shared by all WordPress containers on that host.

**Rationale**:
- **Resource Efficiency**: 200MB for MySQL vs 200MB × N for per-container MySQL
- **Simplicity**: Single database server to manage per host
- **Isolation**: Each customer gets separate database (`wp_customer_id`)
- **Standard WordPress**: Uses host.docker.internal:3306 connection string

**Alternatives Considered**:
- ❌ Per-container MySQL: Wasteful, 200MB × 10 containers = 2GB
- ❌ RDS instance: Overkill for ephemeral clones, adds latency and cost
- ❌ Continue with SQLite: Unresolvable readonly errors, beta plugin

### 2. Separate Observability EC2 Instance

**Decision**: Dedicated t3.small EC2 for Loki + Grafana, separate from wp-target hosts.

**Rationale**:
- **Isolation**: Observability doesn't compete for resources with WordPress
- **Reliability**: Logs survive even if target hosts are terminated
- **Centralization**: Single endpoint for all logs across multiple hosts
- **Scalability**: Easy to upgrade observability without affecting workloads

**Alternatives Considered**:
- ❌ Same host as wp-targets: Resource contention, logs lost on host termination
- ❌ CloudWatch Logs: More expensive, less flexible querying
- ❌ No observability: Continue manual SSH debugging (current pain point)

### 3. Database Lifecycle Management

**Decision**: Databases are ephemeral, created/destroyed with WordPress containers.

**Database Naming**: `wp_{customer_id}` (e.g., `wp_clone-20260116-095447`)

**Rationale**:
- **Consistency**: Matches current SQLite behavior (ephemeral storage)
- **Simplicity**: No database migration/backup needed
- **Isolation**: Each clone is completely independent
- **TTL Cleanup**: Database dropped when container TTL expires

**Flow**:
```sql
-- On provision:
CREATE DATABASE wp_clone-20260116-095447;
CREATE USER 'wp_user'@'%' IDENTIFIED BY '{generated_password}';
GRANT ALL ON wp_clone-20260116-095447.* TO 'wp_user'@'%';

-- On cleanup (TTL expiration):
DROP DATABASE wp_clone-20260116-095447;
```

### 4. Log Shipping Architecture

**Decision**: Promtail as sidecar container, ships Docker logs to Loki.

**Log Flow**:
1. WordPress containers → Docker log driver
2. Promtail reads `/var/lib/docker/containers/*/*.log`
3. Promtail ships to Loki via HTTP
4. Grafana queries Loki for visualization

**Labels**:
- `container_name`: WordPress container ID
- `instance_id`: EC2 instance ID
- `customer_id`: Extracted from container name

### 5. Terraform Module Structure

**Decision**: Three Terraform modules for clean separation:

```
infra/
├── wp-targets/          # Existing (updated)
│   ├── main.tf          # Add MySQL container to user-data
│   └── variables.tf
├── wp-setup-service/    # Existing (no changes)
└── observability/       # NEW
    ├── main.tf          # EC2 + Loki/Grafana
    ├── outputs.tf       # Loki endpoint
    └── variables.tf
```

**Benefits**:
- **Modularity**: Can deploy wp-targets without observability
- **Reusability**: Observability module reusable for other projects
- **Maintainability**: Clear boundaries between concerns

## Security Considerations

### MySQL Security
- Root password generated via Terraform random_password
- Customer databases isolated with separate users
- No external MySQL access (Docker internal network only)
- Connection encrypted via Docker network namespace

### Observability Security
- Grafana admin password set via Terraform
- Loki ingestion port (3100) restricted to wp-targets security group
- Grafana UI (3000) accessible via SSH tunnel only (optional: add ALB)
- No authentication required for Promtail → Loki (internal network)

## Performance Implications

### MySQL Performance
- **Baseline**: 10 concurrent WordPress sites = ~50 queries/sec
- **MySQL Capacity**: 8.0 handles 10k+ queries/sec on t3.small
- **Overhead**: Negligible compared to SQLite file locking contention

### Logging Performance
- **Volume**: ~100 log lines/sec across all containers
- **Loki Capacity**: Handles 1GB/day easily on t3.small
- **Network**: <1Mbps for log shipping (negligible)

## Migration Path

### Phase 1: MySQL Infrastructure
1. Deploy updated Terraform (no downtime)
2. New clones use MySQL automatically
3. Old SQLite clones age out via TTL

### Phase 2: Observability
1. Deploy observability module
2. Update wp-targets user-data to install Promtail
3. Recreate ASG instances gradually

### Rollback Plan
- Keep SQLite-based Docker image tagged as `sqlite-fallback`
- Revert Terraform to previous version
- No data loss (both approaches are ephemeral)

## Cost Analysis

| Component | Monthly Cost | Notes |
|-----------|--------------|-------|
| MySQL (existing t3.small) | $0 | Runs on existing instances |
| Observability t3.small | ~$15 | 24/7 single instance |
| EBS storage (10GB) | ~$1 | For Loki log storage |
| **Total Increase** | **~$16/month** | Optional, can disable if not needed |

## Operational Considerations

### Monitoring Targets
- MySQL container health (Docker health check)
- Database count per host (prevent resource exhaustion)
- Loki ingestion rate (ensure logs flowing)
- Grafana dashboard load time

### Maintenance
- MySQL data is ephemeral (no backups needed)
- Loki retention: 7 days (configurable)
- Grafana dashboards version-controlled in repo
- Terraform state backup essential

## Success Metrics

- ✅ Zero "readonly database" errors in logs
- ✅ 99.9% WordPress clone success rate
- ✅ <30 seconds to find logs for any customer_id
- ✅ <5 minutes to recreate infrastructure via Terraform
