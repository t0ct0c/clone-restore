# Dramatiq Setup Guide

**Created**: 2026-02-20  
**Task**: 1.3-1.5 - Dramatiq Integration

---

## Dependencies Added (requirements.txt)

```
dramatiq[redis,watch]==1.15.0
redis==5.0.1
aioredis==2.0.1
```

---

## Components

### 1. OpenTelemetry Middleware (`dramatiq_otlp_middleware.py`)

Integrates Dramatiq with existing OTLP tracing:
- Creates spans for each message processed
- Propagates trace context through message headers
- Records errors as span exceptions
- Adds message metadata as span attributes

### 2. Broker Configuration

```python
from dramatiq.brokers.redis import RedisBroker

REDIS_URL = "redis://:dramatiq-broker-password@redis-master.wordpress-staging.svc.cluster.local:6379/0"
broker = RedisBroker(url=REDIS_URL)
dramatiq.set_broker(broker)
```

### 3. Worker Setup (Sidecar Container)

```python
from dramatiq_otlp_middleware import DramatiqTracing

# Setup tracing
DramatiqTracing.setup(service_name="wp-k8s-service-worker")

# Run worker
import dramatiq
dramatiq.run()
```

---

## Deployment Architecture

```
┌─────────────────────────────────────────────────────┐
│  wp-k8s-service Pod                                 │
│  ┌─────────────────┐  ┌─────────────────────────┐  │
│  │  FastAPI        │  │  Dramatiq Worker        │  │
│  │  Container      │  │  (Sidecar Container)    │  │
│  │                 │  │                         │  │
│  │  - REST API     │  │  - Process jobs         │  │
│  │  - Enqueue jobs │  │  - OpenTelemetry trace  │  │
│  │  - OTLP traces  │  │  - Redis broker         │  │
│  └────────┬────────┘  └───────────┬─────────────┘  │
│           │                       │                │
│           └───────────┬───────────┘                │
│                       ▼                            │
│              ┌─────────────────┐                   │
│              │   Redis Broker  │                   │
│              │  (shared svc)   │                   │
│              └─────────────────┘                   │
└─────────────────────────────────────────────────────┘
```

---

## Configuration

### Redis Connection

```yaml
# From Secret or ConfigMap
REDIS_URL: redis://:dramatiq-broker-password@redis-master.wordpress-staging.svc.cluster.local:6379/0
```

### Environment Variables

```bash
DRAMATIQ_SERVICE_NAME=wp-k8s-service-worker
OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo.observability.svc.cluster.local:4318
OTEL_SERVICE_NAME=wp-k8s-service-worker
OTEL_RESOURCE_ATTRIBUTES=deployment.environment=staging
```

---

## Usage Examples

### Enqueue a Job

```python
import dramatiq
from .tasks import clone_wordpress

# Fire and forget
clone_wordpress.send(source_url, target_url, options)

# With delay (in milliseconds)
clone_wordpress.send_with_options(
    args=(source_url, target_url, options),
    delay=5000  # 5 seconds
)
```

### Define a Task

```python
import dramatiq
from dramatiq_otlp_middleware import OpenTelemetryMiddleware

@dramatiq.actor(queue_name="clone-queue")
def clone_wordpress(source_url: str, target_url: str, options: dict):
    """Clone WordPress site asynchronously."""
    # Implementation here
    pass
```

---

## Monitoring

### Grafana Dashboards

1. **Worker Metrics**: Queue depth, processing rate, error rate
2. **Trace Dashboard**: End-to-end job execution traces
3. **Log Dashboard**: Structured logs from workers

### Key Metrics

- `dramatiq_messages_processed_total`: Total messages processed
- `dramatiq_message_processing_time`: Time to process messages
- `dramatiq_queue_depth`: Current queue depth
- `dramatiq_errors_total`: Total processing errors

---

## Next Steps

1. ✅ Task 1.3: Update requirements.txt - **DONE**
2. ✅ Task 1.4: Create Dramatiq OTLP middleware - **DONE**
3. ⏸️ Task 1.5: Update wp-k8s-service deployment with Dramatiq sidecar
