# Clone Optimization - Technical Design

**Phase 1**: Local DB + Warm Pod Pool

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│  Warm Pod Pool (2 pods always ready)                   │
│  ┌──────────────────────────────────────────────────┐  │
│  │ wordpress-clone-warm-1                           │  │
│  │ ├─ WordPress Container (port 80)                 │  │
│  │ └─ MySQL Container (port 3306, localhost)        │  │
│  │   └─ emptyDB (ready for import)                  │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │ wordpress-clone-warm-2                           │  │
│  │ ├─ WordPress Container (port 80)                 │  │
│  │ └─ MySQL Container (port 3306, localhost)        │  │
│  │   └─ emptyDB (ready for import)                  │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                        ↓
            Warm Pool Controller
            (maintains pool size = 2)
```

---

## Component Design

### 1. WordPress + MySQL Sidecar Image

**File**: `kubernetes/wp-k8s-service/wordpress-clone/Dockerfile`

```dockerfile
FROM wordpress:6.4-apache

# Install MySQL client (for health checks)
RUN apt-get update && apt-get install -y default-mysql-client

# Pre-install custom-migrator plugin
COPY custom-migrator/ /var/www/html/wp-content/plugins/custom-migrator/

# Custom entrypoint
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["apache2-foreground"]
```

**File**: `kubernetes/wp-k8s-service/wordpress-clone/docker-entrypoint.sh`

```bash
#!/bin/bash
set -e

# Wait for MySQL sidecar to be ready
echo "Waiting for MySQL..."
while ! mysqladmin ping -h"127.0.0.1" --silent; do
    sleep 1
done

# Check if this is a warm pod (empty DB expected)
if [[ "$WARM_POOL_MODE" == "true" ]]; then
    echo "Warm pod mode - skipping WordPress setup"
    # Just ensure MySQL is running, don't configure WordPress yet
    exec docker-entrypoint.sh apache2-foreground
else
    # Normal clone pod - configure WordPress with provided env vars
    exec docker-entrypoint.sh apache2-foreground
fi
```

### 2. MySQL Sidecar Container

**Image**: `mysql:8.0`

**Configuration**:
- Database: `wordpress` (created on startup)
- User: `wordpress` / random password (per pod)
- Port: 3306 (localhost only, not exposed)
- Volume: `emptyDir` (ephemeral, deleted with pod)

**Deployment Spec** (added to WordPress pod):

```yaml
containers:
- name: wordpress
  image: wp-k8s-service-clone:optimized
  env:
  - name: WORDPRESS_DB_HOST
    value: "127.0.0.1:3306"
  - name: WORDPRESS_DB_NAME
    value: "wordpress"
  - name: WORDPRESS_DB_USER
    value: "wordpress"
  - name: WORDPRESS_DB_PASSWORD
    valueFrom:
      secretKeyRef:
        name: {customer-id}-credentials
        key: db-password

- name: mysql
  image: mysql:8.0
  env:
  - name: MYSQL_DATABASE
    value: "wordpress"
  - name: MYSQL_USER
    value: "wordpress"
  - name: MYSQL_PASSWORD
    valueFrom:
      secretKeyRef:
        name: {customer-id}-credentials
        key: db-password
  - name: MYSQL_ALLOW_EMPTY_PASSWORD
    value: "no"
  - name: MYSQL_ROOT_PASSWORD
    valueFrom:
      secretKeyRef:
        name: {customer-id}-credentials
        key: db-password
  volumeMounts:
  - name: mysql-data
    mountPath: /var/lib/mysql
  livenessProbe:
    exec:
      command: ["mysqladmin", "ping", "-h127.0.0.1"]
    initialDelaySeconds: 30
    periodSeconds: 10
  readinessProbe:
    exec:
      command: ["mysqladmin", "ping", "-h127.0.0.1"]
    initialDelaySeconds: 5
    periodSeconds: 5

volumes:
- name: mysql-data
  emptyDir: {}
```

### 3. Warm Pool Controller

**File**: `kubernetes/wp-k8s-service/app/warm_pool_controller.py`

```python
import asyncio
from loguru import logger
from kubernetes import client
from typing import List, Optional
import uuid

class WarmPoolController:
    def __init__(self, namespace: str = "wordpress-staging"):
        self.namespace = namespace
        self.min_warm_pods = 1
        self.max_warm_pods = 2
        self.warm_label_selector = "pool-type=warm,pool-status=ready"
        self.v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()
    
    async def maintain_pool(self):
        """Background task: maintain 1-2 warm pods"""
        while True:
            try:
                warm_pods = self._get_warm_pods()
                available_count = len([p for p in warm_pods if self._is_pod_available(p)])
                
                if available_count < self.min_warm_pods:
                    await self._create_warm_pod()
                    logger.info(f"Created warm pod (pool: {available_count + 1})")
                
                elif available_count > self.max_warm_pods:
                    # Delete excess (oldest first)
                    await self._delete_warm_pod(warm_pods[0])
                    logger.info(f"Deleted excess warm pod (pool: {available_count - 1})")
                
                await asyncio.sleep(30)  # Check every 30s
            
            except Exception as e:
                logger.error(f"Pool maintenance error: {e}")
                await asyncio.sleep(60)
    
    async def assign_warm_pod(self, customer_id: str) -> Optional[str]:
        """Assign warm pod to clone, reset DB for new customer"""
        warm_pods = self._get_warm_pods()
        available = [p for p in warm_pods if self._is_pod_available(p)]
        
        if not available:
            logger.warning("No warm pods available")
            return None
        
        pod_name = available[0].metadata.name
        
        # Reset database for new customer
        await self._reset_pod_database(pod_name, customer_id)
        
        # Tag pod with customer_id
        await self._tag_pod(pod_name, customer_id)
        
        logger.info(f"Assigned warm pod {pod_name} to {customer_id}")
        return pod_name
    
    async def return_to_pool(self, pod_name: str):
        """Reset pod and return to warm pool after TTL"""
        try:
            # Clean database
            await self._reset_database(pod_name)
            
            # Clean filesystem
            await self._clean_filesystem(pod_name)
            
            # Remove customer labels
            await self._untag_pod(pod_name)
            
            # Mark as warm/ready
            await self._mark_pod_warm(pod_name)
            
            logger.info(f"Pod {pod_name} returned to warm pool")
        
        except Exception as e:
            logger.error(f"Failed to return pod to pool: {e}")
            # Delete pod if reset fails
            await self._delete_pod(pod_name)
    
    def _get_warm_pods(self) -> List:
        """Get all warm pool pods"""
        pods = self.v1.list_namespaced_pod(
            namespace=self.namespace,
            label_selector=self.warm_label_selector
        )
        return pods.items
    
    def _is_pod_available(self, pod) -> bool:
        """Check if pod is running and ready"""
        if pod.status.phase != "Running":
            return False
        
        for condition in pod.status.conditions:
            if condition.type == "Ready" and condition.status == "True":
                return True
        return False
    
    async def _create_warm_pod(self):
        """Create new warm pod"""
        pod_name = f"wordpress-warm-{uuid.uuid4().hex[:8]}"
        
        # Create pod spec with warm pool labels
        # ... (full deployment spec)
        
        self.v1.create_namespaced_pod(
            namespace=self.namespace,
            body=pod_spec
        )
    
    async def _reset_pod_database(self, pod_name: str, customer_id: str):
        """Reset database for new customer"""
        # Execute MySQL commands via kubectl exec
        commands = [
            f"DROP DATABASE IF EXISTS wordpress",
            f"CREATE DATABASE wordpress",
            f"GRANT ALL ON wordpress.* TO 'wordpress'@'localhost'"
        ]
        
        for cmd in commands:
            self.v1.connect_get_namespaced_pod_exec(
                name=pod_name,
                namespace=self.namespace,
                command=["mysql", "-uroot", f"-p{password}", "-e", cmd]
            )
    
    # ... (other helper methods)
```

### 4. Modified Clone Flow

**Current Flow**:
```
clone_endpoint
  ↓
provision_target
  ↓
_create_database_on_shared_rds (5-10s)
  ↓
_create_deployment (2-5s)
  ↓
_wait_for_pod_ready (30-60s)
  ↓
activate_plugin_in_container (10-20s)
  ↓
Clone ready (total: 90-180s)
```

**New Flow (with warm pool)**:
```
clone_endpoint
  ↓
assign_warm_pod (5s) ← from pool, already running
  ↓
reset_database (2-5s)
  ↓
import_data (30-60s)
  ↓
Clone ready (total: 35-65s) ✅
```

**Modified k8s_provisioner.py**:

```python
class K8sProvisioner:
    def __init__(self, namespace: str = "wordpress-staging"):
        self.namespace = namespace
        self.warm_pool = WarmPoolController(namespace)
    
    def provision_target(self, customer_id: str, ttl_minutes: int = 30) -> Dict:
        """Provision clone using warm pod or cold fallback"""
        
        # Try warm pool first
        pod_name = await self.warm_pool.assign_warm_pod(customer_id)
        
        if pod_name:
            logger.info(f"Using warm pod {pod_name}")
            return self._use_warm_pod(pod_name, customer_id, ttl_minutes)
        else:
            logger.warning("No warm pods, cold provisioning")
            return self._cold_provision(customer_id, ttl_minutes)
    
    def _use_warm_pod(self, pod_name: str, customer_id: str, ttl_minutes: int) -> Dict:
        """Use existing warm pod"""
        # Reset database for customer
        self.warm_pool.reset_database(pod_name, customer_id)
        
        # Update pod labels (assign to customer)
        self._tag_pod(pod_name, customer_id, ttl_minutes)
        
        # Create Service + Ingress
        self._create_service(customer_id, pod_name)
        self._create_ingress(customer_id)
        
        return {
            "success": True,
            "pod_name": pod_name,
            "target_url": f"http://{customer_id}.wordpress-staging.svc.cluster.local",
            "public_url": f"https://{customer_id}.clones.betaweb.ai"
        }
    
    def _cold_provision(self, customer_id: str, ttl_minutes: int) -> Dict:
        """Fallback: create new pod (if warm pool empty)"""
        # ... existing provision logic ...
```

---

## Database Design

### Per-Pod MySQL Configuration

Each pod has its own MySQL instance:

```
Pod: wordpress-clone-warm-1
├─ WordPress Container
│  ├─ WORDPRESS_DB_HOST=127.0.0.1
│  ├─ WORDPRESS_DB_NAME=wordpress
│  ├─ WORDPRESS_DB_USER=wordpress
│  └─ WORDPRESS_DB_PASSWORD={from-secret}
└─ MySQL Container
   ├─ MYSQL_DATABASE=wordpress
   ├─ MYSQL_USER=wordpress
   ├─ MYSQL_PASSWORD={from-secret}
   └─ MYSQL_ROOT_PASSWORD={from-secret}
```

### Database Reset (Pod Reuse)

When pod returns to pool after TTL:

```sql
-- Drop all WordPress tables
DROP DATABASE wordpress;

-- Recreate empty database
CREATE DATABASE wordpress;

-- Reset privileges
GRANT ALL ON wordpress.* TO 'wordpress'@'localhost';
FLUSH PRIVILEGES;
```

---

## Pod Lifecycle States

```
┌─────────────┐
│  CREATING   │ ← Initial warm pod creation
└──────┬──────┘
       │
       ↓ (pod ready, MySQL running)
┌─────────────┐
│   WARM      │ ← Label: pool-status=ready
│  (empty DB) │
└──────┬──────┘
       │
       ↓ (clone request)
┌─────────────┐
│  ASSIGNED   │ ← Label: clone-id={customer}
│ (importing) │
└──────┬──────┘
       │
       ↓ (import complete)
┌─────────────┐
│   READY     │ ← Serving clone traffic
│ (TTL active)│
└──────┬──────┘
       │
       ↓ (TTL expires)
┌─────────────┐
│  RESETTING  │ ← Cleaning DB + filesystem
└──────┬──────┘
       │
       ↓ (reset complete)
└──────┴──────┘
       │
       └─→ Back to WARM
```

---

## Error Handling

### Warm Pod Unavailable

```python
if not warm_pod:
    # Fallback: cold provision
    return self._cold_provision(customer_id, ttl_minutes)
```

### Pod Reset Fails

```python
try:
    await self._reset_database(pod_name)
except Exception as e:
    logger.error(f"Reset failed: {e}")
    # Delete pod, don't return to pool
    await self._delete_pod(pod_name)
    # Warm pool controller will create replacement
```

### MySQL Sidecar Crashes

```yaml
livenessProbe:
  exec:
    command: ["mysqladmin", "ping", "-h127.0.0.1"]
  initialDelaySeconds: 30
  periodSeconds: 10
```

Kubernetes auto-restarts MySQL container.

---

## Resource Requirements

### Warm Pod (per pod)

| Resource | Request | Limit |
|----------|---------|-------|
| CPU | 500m | 1000m |
| Memory | 512Mi | 1Gi |
| Storage | 1Gi (emptyDir) | - |

### Total (2 warm pods)

| Resource | Total | Monthly Cost |
|----------|-------|--------------|
| CPU | 1000m (1 core) | ~$11 |
| Memory | 1Gi | ~$11 |
| **Total** | | **~$21/month** |

---

## Migration Plan

### Phase 1A: Deploy Warm Pool (Parallel to Current)

1. Deploy WordPress + MySQL sidecar image
2. Deploy warm pool controller
3. Keep current RDS flow active
4. Test warm pool with manual clone assignments

### Phase 1B: Switch Clone Flow

1. Update `k8s_provisioner.py` to use warm pool
2. Disable RDS database creation
3. Monitor clone times + success rate

### Phase 1C: Remove RDS Dependency

1. Remove `use_shared_rds` flag
2. Delete RDS database user cleanup
3. Update documentation

---

## Testing Checklist

- [ ] Warm pod creates successfully
- [ ] MySQL sidecar connects from WordPress
- [ ] Warm pool maintains 1-2 pods
- [ ] Pod assignment works (clone gets warm pod)
- [ ] Database reset works (clean state)
- [ ] Pod return to pool works
- [ ] Cold provision fallback works (when pool empty)
- [ ] Clone time < 65s (p95)
- [ ] Success rate > 99%
- [ ] Cost < $166/month
