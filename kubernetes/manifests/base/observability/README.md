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

## Deployment Status

**✅ COMPLETED** - All components deployed and running

```
NAME                            READY   STATUS
grafana-6847d978ff-6gjmh        1/1     Running
loki-0                          2/2     Running
loki-canary-cbwqq               1/1     Running
loki-canary-w2qnf               1/1     Running
loki-gateway-54d4c5b8fb-xqqdh   1/1     Running
tempo-0                         1/1     Running
```

## Access

### Grafana Dashboard
```bash
kubectl port-forward -n observability svc/grafana 3000:80
```
- URL: http://localhost:3000
- Admin user: `admin`
- Admin password: `admin`
- Datasources: Loki and Tempo pre-configured

### Loki (for queries)
```bash
kubectl port-forward -n observability svc/loki-gateway 3100:80
```
- URL: http://localhost:3100/loki/api/v1/query_range

### Tempo (for traces)
```bash
kubectl port-forward -n observability svc/tempo 3200:3200
```
- URL: http://localhost:3200

## Next Steps

1. ✅ Deploy observability stack (Task 1.0) - **DONE**
2. Deploy Redis broker (Task 1.1)
3. Create jobs database table (Task 1.2)
4. Implement Dramatiq workers (Task 1.3-1.5)

---

## References

- [Grafana Loki Helm Chart](https://github.com/grafana/loki/tree/main/production/helm/loki)
- [Grafana Tempo Helm Chart](https://github.com/grafana/tempo/tree/main/operations/helm/charts/tempo)
- [Grafana Helm Chart](https://github.com/grafana/helm-charts/tree/main/charts/grafana)
- [Loki Documentation](https://grafana.com/docs/loki/latest/)
- [Tempo Documentation](https://grafana.com/docs/tempo/latest/)
