# Clone Optimization - Implementation Tasks

**Status**: PLANNING  
**Created**: 2026-02-21  
**Branch**: feat/optimization  

---

## Phase 1: Local DB + Warm Pool (3-4 days)

### Task 1.1: Create WordPress + MySQL Sidecar Image

**Effort**: 1 day  
**Priority**: HIGH

**Steps**:

1. Create Dockerfile
   ```bash
   mkdir -p kubernetes/wp-k8s-service/wordpress-clone
   ```
   
   ```dockerfile
   # kubernetes/wp-k8s-service/wordpress-clone/Dockerfile
   FROM wordpress:6.4-apache
   
   RUN apt-get update && apt-get install -y default-mysql-client
   
   COPY custom-migrator/ /var/www/html/wp-content/plugins/custom-migrator/
   
   COPY docker-entrypoint.sh /usr/local/bin/
   RUN chmod +x /usr/local/bin/docker-entrypoint.sh
   
   ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
   CMD ["apache2-foreground"]
   ```

2. Create entrypoint script
   ```bash
   # kubernetes/wp-k8s-service/wordpress-clone/docker-entrypoint.sh
   #!/bin/bash
   set -e
   
   # Wait for MySQL sidecar
   while ! mysqladmin ping -h"127.0.0.1" --silent; do
       sleep 1
   done
   
   if [[ "$WARM_POOL_MODE" == "true" ]]; then
       echo "Warm pod mode"
   fi
   
   exec docker-entrypoint.sh apache2-foreground
   ```

3. Build and push image
   ```bash
   docker build -t <account>.dkr.ecr.us-east-1.amazonaws.com/wp-k8s-service-clone:optimized \
     kubernetes/wp-k8s-service/wordpress-clone
   
   docker push <account>.dkr.ecr.us-east-1.amazonaws.com/wp-k8s-service-clone:optimized
   ```

**Acceptance Criteria**:
- [ ] Docker image builds successfully
- [ ] MySQL client installed
- [ ] Custom-migrator plugin included
- [ ] Image pushed to ECR

---

### Task 1.2: Create Warm Pool Controller

**Effort**: 1 day  
**Priority**: HIGH

**Steps**:

1. Create controller
   ```python
   # kubernetes/wp-k8s-service/app/warm_pool_controller.py
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
       
       async def maintain_pool(self):
           """Background task: maintain 1-2 warm pods"""
           while True:
               warm_pods = self._get_warm_pods()
               available = len([p for p in warm_pods if self._is_pod_available(p)])
               
               if available < self.min_warm_pods:
                   await self._create_warm_pod()
               elif available > self.max_warm_pods:
                   await self._delete_warm_pod(warm_pods[0])
               
               await asyncio.sleep(30)
       
       async def assign_warm_pod(self, customer_id: str) -> Optional[str]:
           """Assign warm pod to clone"""
           warm_pods = self._get_warm_pods()
           available = [p for p in warm_pods if self._is_pod_available(p)]
           
           if not available:
               return None
           
           pod_name = available[0].metadata.name
           await self._reset_pod_database(pod_name, customer_id)
           await self._tag_pod(pod_name, customer_id)
           
           return pod_name
       
       async def return_to_pool(self, pod_name: str):
           """Reset pod and return to pool after TTL"""
           await self._reset_database(pod_name)
           await self._clean_filesystem(pod_name)
           await self._untag_pod(pod_name)
           await self._mark_pod_warm(pod_name)
       
       # ... (helper methods)
   ```

2. Add to main.py startup
   ```python
   # kubernetes/wp-k8s-service/app/main.py
   from .warm_pool_controller import WarmPoolController
   
   warm_pool = WarmPoolController()
   
   @app.on_event("startup")
   async def startup_event():
       # Start warm pool maintenance
       asyncio.create_task(warm_pool.maintain_pool())
   ```

**Acceptance Criteria**:
- [ ] Controller maintains 1-2 warm pods
- [ ] Pod assignment works
- [ ] Pod return to pool works
- [ ] Background task runs on startup

---

### Task 1.3: Modify k8s_provisioner.py for Local DB

**Effort**: 1 day  
**Priority**: HIGH

**Steps**:

1. Remove RDS dependency
   ```python
   # kubernetes/wp-k8s-service/app/k8s_provisioner.py
   
   # REMOVE: _create_database_on_shared_rds() method
   # REMOVE: shared_rds_host, shared_rds_password config
   
   # CHANGE: _create_deployment to use sidecar MySQL
   def _create_deployment(self, customer_id: str, ttl_minutes: int) -> bool:
       # DB host is always localhost for sidecar
       db_host = "127.0.0.1"
       
       # ... rest of deployment spec with MySQL sidecar
   ```

2. Add MySQL sidecar to deployment
   ```python
   containers=[
       client.V1Container(
           name="wordpress",
           image=self.docker_image,
           env=[
               client.V1EnvVar(
                   name="WORDPRESS_DB_HOST",
                   value="127.0.0.1:3306"
               ),
               # ... other env vars
           ]
       ),
       client.V1Container(
           name="mysql",
           image="mysql:8.0",
           env=[
               client.V1EnvVar(
                   name="MYSQL_DATABASE",
                   value="wordpress"
               ),
               client.V1EnvVar(
                   name="MYSQL_USER",
                   value="wordpress"
               ),
               client.V1EnvVar(
                   name="MYSQL_PASSWORD",
                   value_from=client.V1EnvVarSource(
                       secret_key_ref=client.V1SecretKeySelector(
                           name=f"{customer_id}-credentials",
                           key="db-password"
                       )
                   )
               ),
           ]
       )
   ]
   ```

3. Update provision_target to use warm pool
   ```python
   def provision_target(self, customer_id: str, ttl_minutes: int = 30) -> Dict:
       # Try warm pool first
       pod_name = await self.warm_pool.assign_warm_pod(customer_id)
       
       if pod_name:
           return self._use_warm_pod(pod_name, customer_id, ttl_minutes)
       else:
           return self._cold_provision(customer_id, ttl_minutes)
   ```

**Acceptance Criteria**:
- [ ] No RDS calls in provision_target
- [ ] MySQL sidecar in deployment
- [ ] Warm pool integration works
- [ ] Cold provision fallback works

---

### Task 1.4: Add Pod Reset Logic

**Effort**: 0.5 day  
**Priority**: HIGH

**Steps**:

1. Implement database reset
   ```python
   async def _reset_database(self, pod_name: str):
       """Drop and recreate WordPress database"""
       commands = [
           "DROP DATABASE IF EXISTS wordpress",
           "CREATE DATABASE wordpress",
           "GRANT ALL ON wordpress.* TO 'wordpress'@'localhost'"
       ]
       
       for cmd in commands:
           self.v1.connect_get_namespaced_pod_exec(
               name=pod_name,
               namespace=self.namespace,
               command=["mysql", "-uroot", f"-p{password}", "-e", cmd]
           )
   ```

2. Implement filesystem cleanup
   ```python
   async def _clean_filesystem(self, pod_name: str):
       """Clean WordPress uploads and plugins"""
       commands = [
           "rm -rf /var/www/html/wp-content/uploads/*",
           "rm -rf /var/www/html/wp-content/cache/*",
       ]
       
       for cmd in commands:
           self.v1.connect_get_namespaced_pod_exec(
               name=pod_name,
               namespace=self.namespace,
               command=["sh", "-c", cmd]
           )
   ```

**Acceptance Criteria**:
- [ ] Database reset works
- [ ] Filesystem cleanup works
- [ ] Pod returns to clean state

---

### Task 1.5: Update TTL Cleaner to Return Pods

**Effort**: 0.5 day  
**Priority**: MEDIUM

**Steps**:

1. Modify clone-ttl-cleaner-cronjob
   ```python
   # Instead of deleting pods:
   # 1. Check if pod is from warm pool
   # 2. If yes, call warm_pool.return_to_pool()
   # 3. If no, delete as before
   ```

**Acceptance Criteria**:
- [ ] Warm pool pods returned to pool
- [ ] Non-warm pods deleted as before

---

## Phase 2: Parallel Execution (1 day)

### Task 2.1: Parallel Browser + Pod Assignment

**Effort**: 0.5 day  
**Priority**: HIGH

**Steps**:

1. Update clone_endpoint
   ```python
   # kubernetes/wp-k8s-service/app/main.py
   
   # CURRENT (sequential):
   source_result = await setup_wordpress_with_browser(...)
   provision_result = provisioner.provision_target(...)
   
   # NEW (parallel):
   source_task = asyncio.create_task(setup_wordpress_with_browser(...))
   target_task = asyncio.create_task(provisioner.provision_target(...))
   source_result, provision_result = await asyncio.gather(source_task, target_task)
   ```

**Acceptance Criteria**:
- [ ] Browser + K8s run in parallel
- [ ] Clone time reduced by 30-60s

---

### Task 2.2: Plugin Status Cache

**Effort**: 0.5 day  
**Priority**: MEDIUM

**Steps**:

1. Add Redis cache
   ```python
   # kubernetes/wp-k8s-service/app/wp_plugin.py
   import redis
   import hashlib
   
   redis_client = redis.Redis(host='redis-master.wordpress-staging')
   
   async def setup_source(url, username, password):
       domain_hash = hashlib.md5(url.encode()).hexdigest()
       cached = redis_client.get(f"plugin_status:{domain_hash}")
       
       if cached == b"installed":
           return await setup_source_direct(url, username, password)
       
       result = await setup_wordpress_with_browser(url, username, password)
       
       if result.get("success"):
           redis_client.setex(f"plugin_status:{domain_hash}", 3600, "installed")
       
       return result
   ```

**Acceptance Criteria**:
- [ ] Cache hit skips browser
- [ ] Cache expires after 1 hour

---

## Phase 3: Go K8s Sidecar (1 week)

### Task 3.1: Create Go K8s Service

**Effort**: 1 week  
**Priority**: MEDIUM

**Steps**:

1. Create Go service
   ```bash
   mkdir -p kubernetes/wp-k8s-service/k8s-sidecar
   ```

2. Implement gRPC endpoints
   - CreateSecret
   - CreateDeployment
   - WaitForPodReady (watch API)
   - CreateService
   - CreateIngress

3. Update Python to call Go service

**Acceptance Criteria**:
- [ ] Go service runs as sidecar
- [ ] Python calls Go via gRPC
- [ ] Pod ready detection < 15s

---

## Testing Checklist

- [ ] Warm pod creates successfully
- [ ] MySQL sidecar connects
- [ ] Warm pool maintains 1-2 pods
- [ ] Pod assignment works
- [ ] Database reset works
- [ ] Pod return to pool works
- [ ] Cold provision fallback works
- [ ] Clone time < 65s
- [ ] Success rate > 99%
- [ ] 10 concurrent clones
- [ ] 50 clones/hour sustained

---

## Definition of Done

- [ ] All Phase 1 tasks complete
- [ ] Clone time < 65s (p95)
- [ ] Cost < $166/month
- [ ] Success rate > 99%
- [ ] Documentation updated
- [ ] Tests passing
