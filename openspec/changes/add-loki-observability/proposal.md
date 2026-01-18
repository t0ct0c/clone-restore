# Change: Add Loki Observability

## Why
The WordPress cloning process is experiencing intermittent browser automation timeouts (120s) on source sites like bonnel.ai. Current logging is localized and difficult to analyze across distributed components. Adding Grafana Loki will provide centralized, searchable logging to diagnose these failures in real-time.

## What Changes
- **Infrastructure**: Deploy Loki and Grafana on the EC2 target instance.
- **Logging**: Install and configure the Loki Docker Logging Driver to ship container logs directly to Loki.
- **Monitoring**: Add a Grafana dashboard for WordPress migration logs.

## Impact
- Affected specs: `observability` (new)
- Affected code: `docker-compose.yml`, EC2 deployment scripts.
