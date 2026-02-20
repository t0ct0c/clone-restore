# Grafana Loki Stack for Logging and Tracing

**Created**: 2026-02-20  
**Purpose**: Self-hosted observability stack (no AWS managed services)

---

## Components

1. **Grafana Loki** - Log aggregation (replaces CloudWatch Logs)
2. **Grafana Tempo** - Distributed tracing (replaces AWS X-Ray)
3. **Grafana** - Visualization and dashboards
4. **Promtail** - Log collector (already in pods via sidecar or DaemonSet)
5. **OpenTelemetry Collector** - Trace collector (already configured in wp-k8s-service)

---

## Architecture

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────┐
│  Application    │────▶│  Promtail    │────▶│    Loki     │
│  (FastAPI)      │logs │  (sidecar)   │     │  (storage)  │
└─────────────────┘     └──────────────┘     └─────────────┘
                              │
                              ▼
                         ┌──────────────┐
                         │   Grafana    │
                         │  (dashboard) │
                         └──────────────┘
                              ▲
┌─────────────────┐     ┌────┴──────┐     ┌─────────────┐
│  Application    │────▶│  OTel     │────▶│    Tempo    │
│  (FastAPI)      │traces│Collector │     │  (storage)  │
└─────────────────┘     └───────────┘     └─────────────┘
```

---

## Deployment Options

### Option A: Helm Charts (Recommended)

**Pros**: Easy to upgrade, well-maintained, good defaults  
**Cons**: Less customization than manifests

### Option B: Kubernetes Manifests

**Pros**: Full control, no Helm dependencies  
**Cons**: More maintenance, manual upgrades

**Recommendation**: **Option A** (Helm) for faster deployment

---

## Helm Chart Versions (as of 2026-02-20)

| Component | Chart | Version | Repository |
|-----------|-------|---------|------------|
| **Loki** | loki | 6.30.0 | grafana/charts |
| **Tempo** | tempo | 1.17.0 | grafana/charts |
| **Grafana** | grafana | 8.8.2 | grafana/charts |

---

## Resource Requirements

### Loki (Single Tenant)

```yaml
resources:
  requests:
    cpu: "500m"
    memory: "512Mi"
  limits:
    cpu: "2000m"
    memory: "2Gi"
```

**Storage**: 10GB (logs retention: 7 days)

### Tempo (Single Tenant)

```yaml
resources:
  requests:
    cpu: "250m"
    memory: "256Mi"
  limits:
    cpu: "1000m"
    memory: "1Gi"
```

**Storage**: 5GB (traces retention: 7 days)

### Grafana

```yaml
resources:
  requests:
    cpu: "100m"
    memory: "128Mi"
  limits:
    cpu: "500m"
    memory: "512Mi"
```

**Storage**: 1GB (dashboards, users)

---

## Total Cost Estimate

| Component | EBS Storage | EC2 (EKS) | Total/Month |
|-----------|-------------|-----------|-------------|
| **Loki** | $1 (10GB gp3) | $15 (t3.medium) | $16 |
| **Tempo** | $0.50 (5GB gp3) | $15 (t3.medium) | $15.50 |
| **Grafana** | $0.50 (1GB gp3) | $7.50 (t3.small) | $8 |
| **Total** | **$2/month** | **$37.50/month** | **~$40/month** |

**Note**: Much cheaper than AWS managed services (~$200-300/month for equivalent)

---

## Next Steps

1. Add Grafana Helm repository
2. Create values files for Loki, Tempo, Grafana
3. Deploy to `observability` namespace
4. Configure data sources in Grafana
5. Create dashboards for Dramatiq monitoring

---

## References

- [Grafana Loki Helm Chart](https://github.com/grafana/loki/tree/main/production/helm/loki)
- [Grafana Tempo Helm Chart](https://github.com/grafana/tempo/tree/main/operations/helm/charts/tempo)
- [Grafana Helm Chart](https://github.com/grafana/helm-charts/tree/main/charts/grafana)
- [Loki Documentation](https://grafana.com/docs/loki/latest/)
- [Tempo Documentation](https://grafana.com/docs/tempo/latest/)
