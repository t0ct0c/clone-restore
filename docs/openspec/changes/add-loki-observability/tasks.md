# Tasks: Add Loki Observability

## 1. Infrastructure Setup
- [ ] 1.1 Install Loki Docker Logging Driver on EC2 instance `13.222.20.138`
- [ ] 1.2 Create `observability/docker-compose.loki.yml` with Loki and Grafana services
- [ ] 1.3 Deploy Loki and Grafana to EC2

## 2. Configuration
- [ ] 2.1 Configure Loki as a datasource in Grafana
- [ ] 2.2 Update `wp-setup-service` deployment to use Loki logging driver
- [ ] 2.3 Update target WordPress containers to use Loki logging driver

## 3. Verification
- [ ] 3.1 Verify Loki connectivity from EC2 host
- [ ] 3.2 Verify logs appear in Grafana Explore view
- [ ] 3.3 Create a basic dashboard for "Cloning Errors"
