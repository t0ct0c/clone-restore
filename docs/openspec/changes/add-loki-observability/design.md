# Design: Loki Observability

## Context
The project needs centralized logging to debug browser automation failures on the EC2 instance. The user has requested using Grafana Loki with the Docker Logging Driver for efficiency.

## Goals
- Centralized log aggregation.
- Minimal overhead (using Docker driver instead of sidecars like Promtail).
- Searchable logs via Grafana.

## Decisions

### 1. Logging Driver
We will use the `grafana/loki-docker-driver`. This allows the Docker daemon to ship logs directly to the Loki endpoint.

**Config per container:**
```yaml
logging:
  driver: loki
  options:
    loki-url: "http://localhost:3100/loki/api/v1/push"
    loki-external-labels: "job=wp-migration,container_name={{.Name}}"
```

### 2. Service Deployment
Loki and Grafana will be deployed as a separate Docker Compose stack to ensure they remain running even if the migration service is updated or restarted.

### 3. Data Retention
Loki will be configured with a 7-day retention period to manage disk space on the EC2 instance.

## Risks / Trade-offs
- **Network Dependency**: If Loki is down, log shipping might block container startup or cause log loss depending on the `loki-batch-wait` and `loki-retries` settings.
- **Disk Usage**: Loki stores logs on disk. We must monitor usage (already an issue previously).

## Migration Plan
1. Install plugin on EC2.
2. Start Loki/Grafana.
3. Update `deploy-service.sh` to include logging options for the `wp-setup-service`.
