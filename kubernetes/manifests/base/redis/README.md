# Redis Broker for Dramatiq

**Created**: 2026-02-20  
**Task**: 1.1 - Deploy Redis to cluster  
**Status**: ✅ COMPLETED

---

## Deployment Details

- **Chart**: bitnami/redis v25.3.0
- **App Version**: Redis 8.6.0
- **Namespace**: wordpress-staging
- **Architecture**: Standalone (single master, no replication)
- **Persistence**: Disabled (ephemeral storage)

---

## Connection Details

### From within the cluster
```
Host: redis-master.wordpress-staging.svc.cluster.local
Port: 6379
Password: dramatiq-broker-password
```

### From outside the cluster (port-forward)
```bash
kubectl port-forward -n wordpress-staging svc/redis-master 6379:6379
redis-cli -a dramatiq-broker-password -h 127.0.0.1 -p 6379
```

### Get password from secret
```bash
export REDIS_PASSWORD=$(kubectl get secret --namespace wordpress-staging redis -o jsonpath="{.data.redis-password}" | base64 -d)
```

---

## Resource Configuration

```yaml
requests:
  cpu: 100m
  memory: 128Mi
limits:
  cpu: 500m
  memory: 512Mi
```

---

## Test Connection

```bash
# Run Redis client pod
kubectl run -n wordpress-staging redis-client --restart='Never' \
  --env REDIS_PASSWORD=dramatiq-broker-password \
  --image registry-1.docker.io/bitnami/redis:latest \
  --command -- sleep infinity

# Attach and test
kubectl exec -n wordpress-staging -it redis-client -- \
  REDISCLI_AUTH="dramatiq-broker-password" redis-cli -h redis-master ping
```

Expected response: `PONG`

---

## Usage in Dramatiq

```python
import dramatiq
from dramatiq.brokers.redis import RedisBroker

REDIS_URL = "redis://:dramatiq-broker-password@redis-master.wordpress-staging.svc.cluster.local:6379/0"
broker = RedisBroker(url=REDIS_URL)
dramatiq.set_broker(broker)
```

---

## Next Steps

1. ✅ Task 1.0: Deploy observability stack - **DONE**
2. ✅ Task 1.1: Deploy Redis broker - **DONE**
3. ⏸️ Task 1.2: Create jobs database table in shared RDS
4. ⏸️ Task 1.3: Update requirements.txt with Dramatiq dependencies
5. ⏸️ Task 1.4: Create Dramatiq OTLP middleware for tracing
6. ⏸️ Task 1.5: Update wp-k8s-service deployment with Dramatiq sidecar
