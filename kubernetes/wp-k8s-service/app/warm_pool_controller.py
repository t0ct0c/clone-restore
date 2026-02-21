"""
Warm Pool Controller - maintains 1-2 WordPress pods ready for instant clone assignment

Usage:
    controller = WarmPoolController(namespace="wordpress-staging")
    await controller.maintain_pool()  # Background task

    # Assign pod to clone
    pod_name = await controller.assign_warm_pod(customer_id)

    # Return pod to pool after TTL
    await controller.return_to_pool(pod_name)
"""

import asyncio
from loguru import logger
from kubernetes import client
from kubernetes.client.rest import ApiException
from typing import List, Optional, Dict
import uuid
import time


class WarmPoolController:
    def __init__(self, namespace: str = "wordpress-staging"):
        self.namespace = namespace
        self.min_warm_pods = 1
        self.max_warm_pods = 2
        self.warm_label_selector = "pool-type=warm,pool-status=ready"
        self.v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()

        # Pod configuration
        self.warm_pod_image = (
            "wordpress:6.4-apache"  # Will be updated to optimized image
        )
        self.mysql_image = "mysql:8.0"
        self.resources = {
            "requests": {"cpu": "250m", "memory": "512Mi"},
            "limits": {"cpu": "500m", "memory": "1Gi"},
        }

    async def maintain_pool(self):
        """Background task: maintain 1-2 warm pods"""
        while True:
            try:
                warm_pods = self._get_warm_pods()
                available = len([p for p in warm_pods if self._is_pod_available(p)])

                if available < self.min_warm_pods:
                    await self._create_warm_pod()
                    logger.info(f"Created warm pod (pool size: {available + 1})")

                elif available > self.max_warm_pods:
                    # Delete excess (oldest first)
                    await self._delete_pod(warm_pods[0].metadata.name)
                    logger.info(f"Deleted excess warm pod (pool size: {available - 1})")

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
            namespace=self.namespace, label_selector=self.warm_label_selector
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

        # Generate random password for MySQL
        db_password = self._generate_password(32)

        # Create secret for credentials
        secret = client.V1Secret(
            metadata=client.V1ObjectMeta(
                name=f"{pod_name}-credentials",
                namespace=self.namespace,
                labels={"pool-type": "warm"},
            ),
            data={
                "db-password": self._to_base64(db_password),
                "wordpress-password": self._to_base64(self._generate_password(32)),
            },
        )

        try:
            self.v1.create_namespaced_secret(namespace=self.namespace, body=secret)
        except ApiException as e:
            if e.status != 409:
                raise

        # Create pod spec
        pod = self._create_warm_pod_spec(pod_name, db_password)

        self.v1.create_namespaced_pod(namespace=self.namespace, body=pod)
        logger.info(f"Created warm pod: {pod_name}")

    def _create_warm_pod_spec(self, pod_name: str, db_password: str) -> client.V1Pod:
        """Create warm pod specification with WordPress + MySQL sidecar"""

        pod = client.V1Pod(
            metadata=client.V1ObjectMeta(
                name=pod_name,
                namespace=self.namespace,
                labels={
                    "app": "wordpress-clone",
                    "pool-type": "warm",
                    "pool-status": "initializing",
                },
            ),
            spec=client.V1PodSpec(
                containers=[
                    # WordPress container
                    client.V1Container(
                        name="wordpress",
                        image=self.warm_pod_image,
                        ports=[client.V1ContainerPort(container_port=80, name="http")],
                        env=[
                            client.V1EnvVar(name="WARM_POOL_MODE", value="true"),
                            client.V1EnvVar(
                                name="WORDPRESS_DB_HOST", value="127.0.0.1:3306"
                            ),
                            client.V1EnvVar(
                                name="WORDPRESS_DB_NAME", value="wordpress"
                            ),
                            client.V1EnvVar(
                                name="WORDPRESS_DB_USER", value="wordpress"
                            ),
                            client.V1EnvVar(
                                name="WORDPRESS_DB_PASSWORD", value=db_password
                            ),
                        ],
                        resources=self.resources,
                        liveness_probe=client.V1Probe(
                            http_get=client.V1HTTPGetAction(path="/", port=80),
                            initial_delay_seconds=30,
                            period_seconds=10,
                        ),
                        readiness_probe=client.V1Probe(
                            http_get=client.V1HTTPGetAction(path="/", port=80),
                            initial_delay_seconds=20,
                            period_seconds=5,
                        ),
                    ),
                    # MySQL sidecar container
                    client.V1Container(
                        name="mysql",
                        image=self.mysql_image,
                        env=[
                            client.V1EnvVar(name="MYSQL_DATABASE", value="wordpress"),
                            client.V1EnvVar(name="MYSQL_USER", value="wordpress"),
                            client.V1EnvVar(name="MYSQL_PASSWORD", value=db_password),
                            client.V1EnvVar(
                                name="MYSQL_ROOT_PASSWORD", value=db_password
                            ),
                        ],
                        resources=self.resources,
                        liveness_probe=client.V1Probe(
                            exec=client.V1ExecAction(
                                command=["mysqladmin", "ping", "-h127.0.0.1"]
                            ),
                            initial_delay_seconds=30,
                            period_seconds=10,
                        ),
                        readiness_probe=client.V1Probe(
                            exec=client.V1ExecAction(
                                command=["mysqladmin", "ping", "-h127.0.0.1"]
                            ),
                            initial_delay_seconds=5,
                            period_seconds=5,
                        ),
                        volume_mounts=[
                            client.V1VolumeMount(
                                name="mysql-data", mount_path="/var/lib/mysql"
                            )
                        ],
                    ),
                ],
                volumes=[
                    client.V1Volume(
                        name="mysql-data", empty_dir=client.V1EmptyDirVolumeSource()
                    )
                ],
            ),
        )

        return pod

    async def _reset_pod_database(self, pod_name: str, customer_id: str):
        """Reset database for new customer"""
        # Get password from secret
        secret_name = f"{pod_name}-credentials"
        secret = self.v1.read_namespaced_secret(secret_name, self.namespace)
        db_password = self._from_base64(secret.data["db-password"])

        commands = [
            f"DROP DATABASE IF EXISTS wordpress",
            f"CREATE DATABASE wordpress",
            f"GRANT ALL ON wordpress.* TO 'wordpress'@'localhost' IDENTIFIED BY '{db_password}'",
            "FLUSH PRIVILEGES",
        ]

        for cmd in commands:
            try:
                self.v1.connect_get_namespaced_pod_exec(
                    name=pod_name,
                    namespace=self.namespace,
                    command=["mysql", f"-p{db_password}", "-e", cmd],
                    container="mysql",
                )
            except Exception as e:
                logger.warning(f"Database reset command failed: {e}")

        logger.info(f"Database reset for pod {pod_name}")

    async def _reset_database(self, pod_name: str):
        """Drop and recreate WordPress database"""
        secret_name = f"{pod_name}-credentials"
        secret = self.v1.read_namespaced_secret(secret_name, self.namespace)
        db_password = self._from_base64(secret.data["db-password"])

        commands = [
            "DROP DATABASE IF EXISTS wordpress",
            "CREATE DATABASE wordpress",
            "FLUSH PRIVILEGES",
        ]

        for cmd in commands:
            self.v1.connect_get_namespaced_pod_exec(
                name=pod_name,
                namespace=self.namespace,
                command=["mysql", f"-p{db_password}", "-e", cmd],
                container="mysql",
            )

    async def _clean_filesystem(self, pod_name: str):
        """Clean WordPress uploads and cache"""
        commands = [
            "rm -rf /var/www/html/wp-content/uploads/*",
            "rm -rf /var/www/html/wp-content/cache/*",
            "rm -rf /var/www/html/wp-content/debug.log",
        ]

        for cmd in commands:
            try:
                self.v1.connect_get_namespaced_pod_exec(
                    name=pod_name,
                    namespace=self.namespace,
                    command=["sh", "-c", cmd],
                    container="wordpress",
                )
            except Exception as e:
                logger.warning(f"Filesystem cleanup failed: {e}")

    async def _tag_pod(self, pod_name: str, customer_id: str):
        """Tag pod with customer_id"""
        body = {
            "metadata": {
                "labels": {
                    "clone-id": customer_id,
                    "pool-type": "assigned",
                    "pool-status": "assigned",
                }
            }
        }
        self.v1.patch_namespaced_pod(pod_name, self.namespace, body)

    async def _untag_pod(self, pod_name: str):
        """Remove customer labels from pod"""
        body = {
            "metadata": {
                "labels": {
                    "clone-id": None  # Remove label
                }
            }
        }
        self.v1.patch_namespaced_pod(pod_name, self.namespace, body)

    async def _mark_pod_warm(self, pod_name: str):
        """Mark pod as warm/ready"""
        body = {"metadata": {"labels": {"pool-type": "warm", "pool-status": "ready"}}}
        self.v1.patch_namespaced_pod(pod_name, self.namespace, body)

    async def _delete_pod(self, pod_name: str):
        """Delete pod and its secret"""
        try:
            self.v1.delete_namespaced_pod(pod_name, self.namespace)
            logger.info(f"Deleted pod: {pod_name}")
        except ApiException as e:
            if e.status != 404:
                raise

        # Delete secret
        try:
            self.v1.delete_namespaced_secret(f"{pod_name}-credentials", self.namespace)
        except ApiException as e:
            if e.status != 404:
                raise

    def _generate_password(self, length: int = 32) -> str:
        """Generate secure random password"""
        import secrets
        import string

        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(length))

    def _to_base64(self, value: str) -> str:
        """Convert string to base64 for Kubernetes secret"""
        import base64

        return base64.b64encode(value.encode()).decode()

    def _from_base64(self, value: str) -> str:
        """Convert base64 to string"""
        import base64

        return base64.b64decode(value.encode()).decode()
