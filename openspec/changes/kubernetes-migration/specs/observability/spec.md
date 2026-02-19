# Spec: Kubernetes Observability

## Capability
Comprehensive logging, metrics, and tracing for Kubernetes-based WordPress clone orchestration.

## Requirements

### Logging (Fluent Bit)
- **Collection**: All container logs from wordpress-staging and wordpress-production namespaces
- **Destination**: CloudWatch Logs (primary) or Grafana Loki (alternative)
- **Retention**: 7 days (configurable)
- **Format**: JSON with structured fields (timestamp, pod, namespace, message)

### Metrics (Prometheus + Grafana)
**System Metrics**:
- Node CPU/memory usage (via node-exporter)
- Pod CPU/memory usage
- Karpenter scaling events (node provisioned/deprovisioned)
- Kubernetes API server latency

**Application Metrics**:
- Clone provisioning time (p50, p95, p99)
- Active clones count
- Clone provisioning success rate
- API endpoint latency (/clone, /restore, /health)
- WordPress plugin installation time

**Business Metrics**:
- Clones created per day
- Average clone TTL
- Clone cleanup success rate

### Tracing (OpenTelemetry + Tempo)
- Distributed traces for /clone and /restore workflows
- Trace spans: API request → K8s API call → Pod creation → Ingress ready
- Trace retention: 48 hours

### Alerting
**Critical Alerts**:
- wp-k8s-service pod CrashLoopBackOff
- Clone provisioning failure rate > 5%
- RDS connection failures
- Karpenter unable to provision nodes

**Warning Alerts**:
- Clone provisioning time > 3 minutes (p95)
- Active clones > 50 (capacity planning)
- Disk usage on nodes > 80%

## Acceptance Criteria

**Fluent Bit**:
- [ ] DaemonSet deployed to all nodes
- [ ] Logs from wordpress-staging visible in CloudWatch/Loki
- [ ] Logs include pod name, namespace, timestamp
- [ ] Log retention policy set to 7 days

**Prometheus + Grafana**:
- [ ] Prometheus server deployed
- [ ] Grafana deployed with datasource configured
- [ ] Dashboard showing system metrics (CPU, memory, pods)
- [ ] Dashboard showing application metrics (clone count, provisioning time)
- [ ] Dashboard showing Karpenter metrics (nodes, scaling events)

**OpenTelemetry + Tempo**:
- [ ] OTel collector deployed
- [ ] wp-k8s-service instrumented with OTel SDK
- [ ] Traces visible in Tempo/Grafana
- [ ] Can trace full /clone workflow end-to-end

**Alerting**:
- [ ] AlertManager configured
- [ ] Alerts sent to Slack/email (configurable)
- [ ] Test alert fires successfully
- [ ] Alert runbooks documented

## Non-Requirements

- **Service mesh observability**: No Istio/Linkerd metrics for MVP
- **APM tools**: No Datadog/New Relic (using Prometheus + OTel)
- **Log aggregation from EC2**: Only K8s logs needed

## Edge Cases

**Fluent Bit buffer overflow**:
- Increase buffer size
- Add backpressure limits
- Drop oldest logs if buffer full

**Prometheus storage full**:
- Set retention policy (default: 15 days)
- Use remote write to long-term storage (Cortex/Thanos)

**Grafana dashboard load time**:
- Limit time range queries
- Use recording rules for expensive queries
- Cache dashboard results

**Trace sampling**:
- Sample 100% for MVP (low traffic)
- Add head-based sampling if traffic increases (sample 10%)

## Testing Strategy

**Fluent Bit Validation**:
```bash
# Deploy Fluent Bit
kubectl apply -f kubernetes/manifests/observability/fluentbit.yaml

# Generate test logs
kubectl run test-logger --image=busybox --restart=Never -- sh -c "while true; do echo 'Test log'; sleep 1; done"

# Check CloudWatch Logs
aws logs tail /aws/eks/wp-clone-restore/wordpress-staging --follow

# Cleanup
kubectl delete pod test-logger
```

**Prometheus Validation**:
```bash
# Port-forward to Prometheus
kubectl port-forward -n monitoring svc/prometheus 9090:9090

# Query metrics
curl http://localhost:9090/api/v1/query?query=up

# Check targets
curl http://localhost:9090/api/v1/targets
```

**Grafana Validation**:
```bash
# Port-forward to Grafana
kubectl port-forward -n monitoring svc/grafana 3000:80

# Open browser: http://localhost:3000
# Login with admin/<password>
# Verify datasources configured
# Verify dashboards load
```

**Tracing Validation**:
```bash
# Trigger /clone request with trace
curl -X POST https://<ingress>/clone \
  -H "traceparent: 00-$(openssl rand -hex 16)-$(openssl rand -hex 8)-01" \
  -H "Content-Type: application/json" \
  -d '{...}'

# Port-forward to Tempo
kubectl port-forward -n monitoring svc/tempo 3200:3200

# Query trace
curl "http://localhost:3200/api/traces/<trace-id>"
```

## Metrics

**Log Volume**:
- wp-k8s-service: ~10 MB/day
- WordPress clones: ~5 MB/day per clone
- System logs: ~50 MB/day

**Metrics Cardinality**:
- Time series: ~5,000 (low)
- Scrape interval: 30 seconds
- Retention: 15 days

**Trace Volume**:
- Traces per day: ~100 (low traffic MVP)
- Trace size: ~50 KB per trace
- Retention: 48 hours

## Dependencies

**Fluent Bit**:
- Helm chart: `fluent/fluent-bit`
- CloudWatch Logs IAM permissions (IRSA)

**Prometheus + Grafana**:
- Helm chart: `prometheus-community/kube-prometheus-stack`
- Persistent storage for Prometheus (optional, can use emptyDir)

**OpenTelemetry**:
- Helm chart: `open-telemetry/opentelemetry-operator`
- Python SDK: `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-instrumentation-fastapi`

**Tempo**:
- Helm chart: `grafana/tempo`
- S3 bucket for trace storage (optional for MVP)

## References

- Fluent Bit: https://docs.fluentbit.io/manual/
- Prometheus: https://prometheus.io/docs/
- Grafana: https://grafana.com/docs/
- OpenTelemetry: https://opentelemetry.io/docs/
- Tempo: https://grafana.com/docs/tempo/
- AWS CloudWatch Logs: https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/

## Dashboards

### Dashboard 1: System Overview
- Cluster CPU/memory usage
- Node count (Karpenter)
- Pod count by namespace
- API server request rate

### Dashboard 2: WordPress Clones
- Active clones count
- Clone provisioning time (heatmap)
- Clone provisioning success rate
- Clones created per day

### Dashboard 3: wp-k8s-service
- API request rate by endpoint
- API latency (p50, p95, p99)
- Error rate (4xx, 5xx)
- Kubernetes API call latency

### Dashboard 4: Karpenter
- Nodes provisioned/deprovisioned
- Provisioning time
- Node utilization
- Spot interruptions
