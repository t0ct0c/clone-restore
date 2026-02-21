"""
Kubernetes Provisioning Module

Handles ephemeral WordPress clone provisioning on Kubernetes using Deployments with TTL labels.
Cleanup is handled by a CronJob that deletes expired clones every 5 minutes.
"""

from loguru import logger
import time
import secrets
import string
from datetime import datetime, timedelta
from typing import Optional, Dict
from kubernetes import client, config, dynamic
from kubernetes.client.rest import ApiException
import os


class K8sProvisioner:
    """Provision ephemeral WordPress clones on Kubernetes with Deployments + TTL labels"""

    def __init__(self, namespace: str = "wordpress-staging"):
        """
        Initialize Kubernetes provisioner

        Args:
            namespace: Kubernetes namespace for WordPress clones
        """
        # Load kubeconfig from default location or in-cluster config
        try:
            config.load_incluster_config()
            logger.info("Loaded in-cluster Kubernetes configuration")
        except:
            config.load_kube_config()
            logger.info("Loaded kubeconfig from local config file")

        self.core_api = client.CoreV1Api()
        self.batch_api = client.BatchV1Api()
        self.apps_api = client.AppsV1Api()
        self.networking_api = client.NetworkingV1Api()
        self.dynamic_client = dynamic.DynamicClient(client.ApiClient())
        self.namespace = namespace

        # Configuration from environment variables
        self.docker_image = os.getenv(
            "WORDPRESS_IMAGE",
            "044514005641.dkr.ecr.us-east-1.amazonaws.com/wp-k8s-service-clone:optimized",
        )
        self.traefik_dns = os.getenv("TRAEFIK_DNS", "clones.betaweb.ai")

        # Warm pool enabled
        self.use_warm_pool = os.getenv("USE_WARM_POOL", "true").lower() == "true"

        logger.info(f"K8sProvisioner initialized for namespace: {namespace}")
        logger.info(f"Warm pool: {self.use_warm_pool}, Image: {self.docker_image}")

    def provision_target(self, customer_id: str, ttl_minutes: int = 30) -> Dict:
        """
        Provision ephemeral WordPress clone using warm pool or cold fallback

        Args:
            customer_id: Unique clone identifier
            ttl_minutes: Time-to-live in minutes (default: 30)

        Returns:
            Dict with clone details (URL, credentials, status)
        """
        if self.use_warm_pool:
            return self._provision_from_warm_pool(customer_id, ttl_minutes)
        else:
            return self._provision_cold(customer_id, ttl_minutes)

    def _provision_from_warm_pool(self, customer_id: str, ttl_minutes: int) -> Dict:
        """Assign warm pod from pool (fast path)"""
        import asyncio
        from .warm_pool_controller import WarmPoolController

        try:
            logger.info(f"Assigning warm pod for {customer_id}")
            warm_pool = WarmPoolController(namespace=self.namespace)
            pod_name = asyncio.run(warm_pool.assign_warm_pod(customer_id))

            if not pod_name:
                logger.warning("No warm pods available, falling back to cold provision")
                return self._provision_cold(customer_id, ttl_minutes)

            # Get credentials from secret
            secret = self.core_api.read_namespaced_secret(
                f"{pod_name}-credentials", self.namespace
            )
            import base64

            wp_password = base64.b64decode(secret.data["wordpress-password"]).decode()

            # Tag pod for customer
            self._tag_pod_for_customer(pod_name, customer_id, ttl_minutes)

            # Create Service and Ingress
            self._create_service_for_pod(customer_id, pod_name)
            self._create_ingress(customer_id)

            logger.info(f"Warm pod {pod_name} assigned to {customer_id}")
            return {
                "success": True,
                "pod_name": pod_name,
                "target_url": f"http://{customer_id}.wordpress-staging.svc.cluster.local",
                "public_url": f"https://{customer_id}.clones.betaweb.ai",
                "wordpress_username": "admin",
                "wordpress_password": wp_password,
                "api_key": "migration-master-key",
                "expires_at": self._calculate_ttl_expires(ttl_minutes),
                "namespace": self.namespace,
                "warm_pool": True,
            }

        except Exception as e:
            logger.error(f"Failed to assign warm pod: {e}")
            return self._provision_cold(customer_id, ttl_minutes)

    def _provision_cold(self, customer_id: str, ttl_minutes: int) -> Dict:
        """Cold provision new pod with MySQL sidecar (fallback)"""
        try:
            logger.info(f"Cold provisioning for {customer_id}")

            # Generate credentials
            wp_password = self._generate_password()
            db_password = self._generate_password()
            api_key = "migration-master-key"

            # Create Secret
            secret_created, _ = self._create_secret(
                customer_id=customer_id,
                wp_password=wp_password,
                db_password=db_password,
                api_key=api_key,
            )

            if not secret_created:
                return {
                    "success": False,
                    "error_code": "SECRET_CREATE_FAILED",
                    "message": "Failed to create Kubernetes Secret",
                }

            # Create Deployment with MySQL sidecar
            deployment_created = self._create_deployment_with_mysql_sidecar(
                customer_id=customer_id,
                ttl_minutes=ttl_minutes,
                db_password=db_password,
                wp_password=wp_password,
            )

            if not deployment_created:
                self._cleanup_secret(customer_id)
                return {
                    "success": False,
                    "error_code": "DEPLOYMENT_CREATE_FAILED",
                    "message": "Failed to create Kubernetes Deployment",
                }

            # Wait for pod
            pod_ready = self._wait_for_pod_ready(customer_id, timeout=180)
            if not pod_ready:
                logger.warning(f"Pod not ready after 180s")

            # Plugin is pre-installed, no activation needed
            logger.info(f"Cold provision complete for {customer_id}")

            return {
                "success": True,
                "pod_name": customer_id,
                "target_url": f"http://{customer_id}.wordpress-staging.svc.cluster.local",
                "public_url": f"https://{customer_id}.clones.betaweb.ai",
                "wordpress_username": "admin",
                "wordpress_password": wp_password,
                "api_key": "migration-master-key",
                "expires_at": self._calculate_ttl_expires(ttl_minutes),
                "namespace": self.namespace,
                "warm_pool": False,
            }

        except Exception as e:
            logger.error(f"Cold provision failed: {e}")
            return {
                "success": False,
                "error_code": "PROVISION_ERROR",
                "message": f"Provisioning failed: {str(e)}",
            }

            # 7b. Wait for WordPress to be configured and responding
            logger.info(f"Waiting for WordPress to be ready in {customer_id}...")
            wp_ready = self._wait_for_wordpress_ready(customer_id, timeout=120)

            if not wp_ready:
                logger.warning(f"WordPress not ready after 120s, clone may fail")

            # 8. Calculate expiration time
            expires_at = datetime.utcnow() + timedelta(minutes=ttl_minutes)

            # 9. Construct URLs
            # Direct service URL (for internal testing)
            direct_url = f"http://{customer_id}.{self.namespace}.svc.cluster.local"
            # Public Traefik URL (subdomain-based)
            public_url = f"https://{customer_id}.clones.betaweb.ai"

            logger.info(f"Clone provisioned successfully: {public_url}")

            return {
                "success": True,
                "target_url": direct_url,
                "public_url": public_url,
                "wordpress_username": "admin",
                "wordpress_password": wp_password,
                "api_key": api_key,
                "expires_at": expires_at.isoformat() + "Z",
                "status": "running",
                "message": "Clone provisioned successfully",
                "customer_id": customer_id,
                "namespace": self.namespace,
            }

        except Exception as e:
            logger.error(f"Provisioning failed: {e}", exc_info=True)
            return {
                "success": False,
                "error_code": "PROVISION_ERROR",
                "message": f"Provisioning failed: {str(e)}",
            }

    def _generate_password(self, length: int = 16) -> str:
        """Generate secure random password"""
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(length))

    def _get_secret_db_password(self, customer_id: str):
        """Get DB password from existing secret if it exists"""
        try:
            secret = self.core_api.read_namespaced_secret(
                name=f"{customer_id}-credentials",
                namespace=self.namespace,
            )
            password = secret.data.get("db-password", "")
            if password:
                import base64

                return base64.b64decode(password).decode("utf-8")
        except:
            pass
        return None

    def _db_user_exists(self, customer_id: str, cursor) -> bool:
        """Check if database user exists on RDS"""
        db_name = f"wp_{customer_id.replace('-', '_')}"
        db_user = db_name
        try:
            cursor.execute(
                "SELECT 1 FROM mysql.user WHERE User = %s AND Host = '%'", (db_user,)
            )
            return cursor.fetchone() is not None
        except:
            return False

    def _create_secret(
        self, customer_id: str, wp_password: str, db_password: str, api_key: str
    ) -> tuple:
        """Create Kubernetes Secret for WordPress credentials

        Returns:
            tuple: (success: bool, password_from_secret: str or None)
                   If secret existed, returns the existing password
        """
        try:
            secret = client.V1Secret(
                metadata=client.V1ObjectMeta(
                    name=f"{customer_id}-credentials",
                    namespace=self.namespace,
                    labels={"app": "wordpress-clone", "clone-id": customer_id},
                ),
                string_data={
                    "wordpress-username": "admin",
                    "wordpress-password": wp_password,
                    "db-password": db_password,
                    "api-key": api_key,
                },
            )

            self.core_api.create_namespaced_secret(
                namespace=self.namespace, body=secret
            )

            logger.info(f"Secret created: {customer_id}-credentials")
            return True, None

        except ApiException as e:
            if e.status == 409:
                logger.warning(f"Secret already exists: {customer_id}-credentials")
                # Get the existing password from the secret
                existing_password = self._get_secret_db_password(customer_id)
                if existing_password:
                    logger.info(
                        f"Using existing DB password from secret for {customer_id}"
                    )
                    return True, existing_password
                return True, None
            logger.error(f"Failed to create Secret: {e}")
            return False, None

    def _create_database_on_shared_rds(
        self, customer_id: str, db_password: str, existing_password: str = None
    ) -> bool:
        """Create MySQL database on shared RDS instance

        Args:
            customer_id: Clone identifier
            db_password: New password to use (if creating user)
            existing_password: Password from existing secret (if secret already existed)
        """
        try:
            import pymysql

            # Sanitize customer_id for database name
            db_name = f"wp_{customer_id.replace('-', '_')}"
            db_user = db_name

            # Connect to shared RDS
            connection = pymysql.connect(
                host=self.shared_rds_host,
                user="admin",
                password=self.shared_rds_password,
                connect_timeout=10,
            )

            cursor = connection.cursor()

            # Create database
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {db_name}")

            # Check if user exists
            user_exists = self._db_user_exists(customer_id, cursor)

            if user_exists and existing_password:
                # User exists and we have password from secret - ensure they match
                # Update password to match secret (handles case where DB was recreated)
                cursor.execute(
                    f"ALTER USER '{db_user}'@'%' IDENTIFIED BY '{existing_password}'"
                )
                logger.info(f"Updated existing DB user password for {db_user}")
            elif user_exists:
                # User exists but no existing password - use new password
                cursor.execute(
                    f"ALTER USER '{db_user}'@'%' IDENTIFIED BY '{db_password}'"
                )
                logger.info(f"Updated DB user password for {db_user}")
            else:
                # Create new user
                cursor.execute(
                    f"CREATE USER '{db_user}'@'%' IDENTIFIED BY '{db_password}'"
                )
                logger.info(f"Created new DB user: {db_user}")

            # Grant privileges (idempotent)
            cursor.execute(f"GRANT ALL PRIVILEGES ON {db_name}.* TO '{db_user}'@'%'")
            cursor.execute("FLUSH PRIVILEGES")

            cursor.close()
            connection.close()

            logger.info(f"Database configured on shared RDS: {db_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to create database on shared RDS: {e}")
            return False

    def _create_deployment(self, customer_id: str, ttl_minutes: int) -> bool:
        """Create Kubernetes Deployment with TTL label for auto-cleanup"""
        try:
            from datetime import datetime, timedelta

            # Sanitize customer_id for database name
            db_name = f"wp_{customer_id.replace('-', '_')}"
            db_user = db_name

            # Determine database host
            if self.use_shared_rds:
                db_host = self.shared_rds_host
            else:
                db_host = f"mysql.{self.namespace}.svc.cluster.local"

            # Calculate TTL expiration time
            ttl_expires_at = datetime.utcnow() + timedelta(minutes=ttl_minutes)
            # Use Unix timestamp for label (K8s labels can't contain colons)
            ttl_label = str(int(ttl_expires_at.timestamp()))

            # Deployment spec with TTL label
            deployment = client.V1Deployment(
                metadata=client.V1ObjectMeta(
                    name=customer_id,
                    namespace=self.namespace,
                    labels={
                        "app": "wordpress-clone",
                        "clone-id": customer_id,
                        "ttl-expires-at": ttl_label,
                    },
                ),
                spec=client.V1DeploymentSpec(
                    replicas=1,
                    selector=client.V1LabelSelector(
                        match_labels={"clone-id": customer_id}
                    ),
                    template=client.V1PodTemplateSpec(
                        metadata=client.V1ObjectMeta(
                            labels={
                                "app": "wordpress-clone",
                                "clone-id": customer_id,
                                "ttl-expires-at": ttl_label,
                            }
                        ),
                        spec=client.V1PodSpec(
                            restart_policy="Always",
                            containers=[
                                client.V1Container(
                                    name="wordpress",
                                    image=self.docker_image,
                                    ports=[
                                        client.V1ContainerPort(
                                            container_port=80, name="http"
                                        )
                                    ],
                                    env=[
                                        # Database configuration
                                        client.V1EnvVar(
                                            name="WORDPRESS_DB_HOST",
                                            value=f"{db_host}:3306",
                                        ),
                                        client.V1EnvVar(
                                            name="WORDPRESS_DB_NAME", value=db_name
                                        ),
                                        client.V1EnvVar(
                                            name="WORDPRESS_DB_USER", value=db_user
                                        ),
                                        client.V1EnvVar(
                                            name="WORDPRESS_DB_PASSWORD",
                                            value_from=client.V1EnvVarSource(
                                                secret_key_ref=client.V1SecretKeySelector(
                                                    name=f"{customer_id}-credentials",
                                                    key="db-password",
                                                )
                                            ),
                                        ),
                                        # WordPress admin credentials
                                        client.V1EnvVar(
                                            name="WP_ADMIN_USER", value="admin"
                                        ),
                                        client.V1EnvVar(
                                            name="WP_ADMIN_PASSWORD",
                                            value_from=client.V1EnvVarSource(
                                                secret_key_ref=client.V1SecretKeySelector(
                                                    name=f"{customer_id}-credentials",
                                                    key="wordpress-password",
                                                )
                                            ),
                                        ),
                                        client.V1EnvVar(
                                            name="WP_ADMIN_EMAIL",
                                            value="admin@example.com",
                                        ),
                                        # Site URL uses subdomain routing
                                        client.V1EnvVar(
                                            name="WP_SITE_URL",
                                            value=f"https://{customer_id}.clones.betaweb.ai",
                                        ),
                                    ],
                                    resources=client.V1ResourceRequirements(
                                        requests={"cpu": "250m", "memory": "512Mi"},
                                        limits={"cpu": "500m", "memory": "1Gi"},
                                    ),
                                    liveness_probe=client.V1Probe(
                                        http_get=client.V1HTTPGetAction(
                                            path="/", port=80
                                        ),
                                        initial_delay_seconds=30,
                                        period_seconds=10,
                                        timeout_seconds=5,
                                        failure_threshold=3,
                                    ),
                                    readiness_probe=client.V1Probe(
                                        http_get=client.V1HTTPGetAction(
                                            path="/",
                                            port=80,
                                        ),
                                        initial_delay_seconds=20,
                                        period_seconds=5,
                                        timeout_seconds=3,
                                        failure_threshold=6,
                                    ),
                                )
                            ],
                        ),
                    ),
                ),
            )

            self.apps_api.create_namespaced_deployment(
                namespace=self.namespace, body=deployment
            )

            logger.info(
                f"Deployment created: {customer_id} (TTL: {ttl_minutes}min, expires: {ttl_label})"
            )
            return True

        except ApiException as e:
            if e.status == 409:
                logger.warning(f"Deployment already exists: {customer_id}")
                return True
            logger.error(f"Failed to create Deployment: {e}")
            return False

    def _wait_for_pod_ready(self, customer_id: str, timeout: int = 180) -> bool:
        """Wait for pod to be in Running state"""
        try:
            start_time = time.time()

            while time.time() - start_time < timeout:
                pods = self.core_api.list_namespaced_pod(
                    namespace=self.namespace, label_selector=f"clone-id={customer_id}"
                )

                if pods.items:
                    pod = pods.items[0]

                    if pod.status.phase == "Running":
                        logger.info(f"Pod {pod.metadata.name} is running")
                        return True

                    logger.debug(f"Pod {pod.metadata.name} status: {pod.status.phase}")

                time.sleep(5)

            logger.warning(f"Pod not ready after {timeout}s")
            return False

        except Exception as e:
            logger.error(f"Failed to check pod status: {e}")
            return False

    def _create_service(self, customer_id: str) -> bool:
        """Create ClusterIP Service to expose WordPress pod"""
        try:
            service = client.V1Service(
                metadata=client.V1ObjectMeta(
                    name=customer_id,
                    namespace=self.namespace,
                    labels={"app": "wordpress-clone", "clone-id": customer_id},
                ),
                spec=client.V1ServiceSpec(
                    type="ClusterIP",
                    selector={"clone-id": customer_id},
                    ports=[
                        client.V1ServicePort(
                            name="http", port=80, target_port=80, protocol="TCP"
                        )
                    ],
                ),
            )

            self.core_api.create_namespaced_service(
                namespace=self.namespace, body=service
            )

            logger.info(f"Service created: {customer_id}")
            return True

        except ApiException as e:
            if e.status == 409:
                logger.warning(f"Service already exists: {customer_id}")
                return True
            logger.error(f"Failed to create Service: {e}")
            return False

    def _create_ingress(self, customer_id: str) -> bool:
        """Create standard Kubernetes Ingress for Traefik subdomain routing"""
        try:
            from kubernetes.client import V1Ingress, V1ObjectMeta, V1IngressSpec
            from kubernetes.client import V1IngressRule, V1HTTPIngressRuleValue
            from kubernetes.client import V1HTTPIngressPath, V1IngressBackend
            from kubernetes.client import V1IngressServiceBackend, V1ServiceBackendPort

            subdomain = f"{customer_id}.clones.betaweb.ai"

            ingress = V1Ingress(
                metadata=V1ObjectMeta(
                    name=customer_id,
                    namespace=self.namespace,
                    labels={"app": "wordpress-clone", "clone-id": customer_id},
                    annotations={
                        "traefik.ingress.kubernetes.io/router.entrypoints": "web,websecure",
                    },
                ),
                spec=V1IngressSpec(
                    ingress_class_name="traefik",
                    rules=[
                        V1IngressRule(
                            host=subdomain,
                            http=V1HTTPIngressRuleValue(
                                paths=[
                                    V1HTTPIngressPath(
                                        path="/",
                                        path_type="Prefix",
                                        backend=V1IngressBackend(
                                            service=V1IngressServiceBackend(
                                                name=customer_id,
                                                port=V1ServiceBackendPort(number=80),
                                            )
                                        ),
                                    )
                                ]
                            ),
                        )
                    ],
                ),
            )

            self.networking_api.create_namespaced_ingress(
                namespace=self.namespace, body=ingress
            )

            logger.info(f"Ingress created: {customer_id} (subdomain: {subdomain})")
            return True

        except ApiException as e:
            if e.status == 409:
                logger.warning(f"Ingress already exists: {customer_id}")
                return True
            logger.error(f"Failed to create Ingress: {e}")
            return False

    def _cleanup_secret(self, customer_id: str):
        """Delete Secret"""
        try:
            self.core_api.delete_namespaced_secret(
                name=f"{customer_id}-credentials", namespace=self.namespace
            )
            logger.info(f"Deleted Secret: {customer_id}-credentials")
        except ApiException:
            pass

    def _cleanup_deployment(self, customer_id: str):
        """Delete Deployment (and its pods)"""
        try:
            self.apps_api.delete_namespaced_deployment(
                name=customer_id,
                namespace=self.namespace,
                propagation_policy="Foreground",
            )
            logger.info(f"Deleted Deployment: {customer_id}")
        except ApiException:
            pass

    def run_wp_cli_in_container(self, customer_id: str, wp_cli_command: str) -> bool:
        """
        Run WP-CLI command inside WordPress container via kubectl exec

        Args:
            customer_id: Clone identifier
            wp_cli_command: WP-CLI command (without 'wp' prefix)

        Returns:
            True if successful, False otherwise
        """
        try:
            # Find the pod
            pods = self.core_api.list_namespaced_pod(
                namespace=self.namespace, label_selector=f"clone-id={customer_id}"
            )

            if not pods.items:
                logger.error(f"No pod found for clone {customer_id}")
                return False

            pod_name = pods.items[0].metadata.name

            # Execute WP-CLI command
            from kubernetes.stream import stream

            exec_command = [
                "/bin/sh",
                "-c",
                f"wp {wp_cli_command} --path=/var/www/html --allow-root",
            ]

            resp = stream(
                self.core_api.connect_get_namespaced_pod_exec,
                pod_name,
                self.namespace,
                command=exec_command,
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
            )

            logger.info(f"WP-CLI command output: {resp}")
            return True

        except Exception as e:
            logger.error(f"Failed to run WP-CLI command: {e}")
            return False

    def update_wordpress_urls(self, customer_id: str, public_url: str) -> bool:
        """
        Update WordPress home/siteurl via WP-CLI

        Args:
            customer_id: Clone identifier
            public_url: Public ALB URL for the clone

        Returns:
            True if successful, False otherwise
        """
        try:
            # Update database URLs
            self.run_wp_cli_in_container(
                customer_id,
                f'db query "UPDATE wp_options SET option_value = \\"{public_url}\\" WHERE option_name IN (\\"home\\", \\"siteurl\\");"',
            )

            # Lock URLs in wp-config.php
            self.run_wp_cli_in_container(
                customer_id, f'config set WP_HOME "{public_url}" --type=constant'
            )

            self.run_wp_cli_in_container(
                customer_id, f'config set WP_SITEURL "{public_url}" --type=constant'
            )

            logger.info(f"WordPress URLs updated to {public_url}")
            return True

        except Exception as e:
            logger.warning(f"Failed to update WordPress URLs: {e}")
            return False

    def activate_plugin_in_container(
        self, customer_id: str, plugin_slug: str = "custom-migrator"
    ) -> bool:
        """
        Activate WordPress plugin via WP-CLI

        Args:
            customer_id: Clone identifier
            plugin_slug: Plugin slug to activate

        Returns:
            True if successful, False otherwise
        """
        return self.run_wp_cli_in_container(
            customer_id, f"plugin activate {plugin_slug}"
        )

    def _tag_pod_for_customer(self, pod_name: str, customer_id: str, ttl_minutes: int):
        """Tag pod with customer_id and TTL"""
        import base64

        ttl_label = str(
            int((datetime.utcnow() + timedelta(minutes=ttl_minutes)).timestamp())
        )

        body = {
            "metadata": {
                "labels": {
                    "clone-id": customer_id,
                    "ttl-expires-at": ttl_label,
                    "pool-type": "assigned",
                }
            }
        }
        self.core_api.patch_namespaced_pod(pod_name, self.namespace, body)
        logger.info(f"Tagged pod {pod_name} for customer {customer_id}")

    def _create_service_for_pod(self, customer_id: str, pod_name: str) -> bool:
        """Create ClusterIP Service for specific pod"""
        try:
            service = client.V1Service(
                metadata=client.V1ObjectMeta(
                    name=customer_id,
                    namespace=self.namespace,
                ),
                spec=client.V1ServiceSpec(
                    selector={"clone-id": customer_id},
                    ports=[client.V1ServicePort(port=80, target_port=80)],
                    type="ClusterIP",
                ),
            )
            self.core_api.create_namespaced_service(self.namespace, service)
            logger.info(f"Service created for pod {pod_name}: {customer_id}")
            return True
        except ApiException as e:
            if e.status == 409:
                logger.warning(f"Service already exists: {customer_id}")
                return True
            logger.error(f"Service creation failed: {e}")
            return False

    def _calculate_ttl_expires(self, ttl_minutes: int) -> str:
        """Calculate TTL expiration time as ISO string"""
        expires_at = datetime.utcnow() + timedelta(minutes=ttl_minutes)
        return expires_at.isoformat() + "Z"

    def _create_deployment_with_mysql_sidecar(
        self, customer_id: str, ttl_minutes: int, db_password: str, wp_password: str
    ) -> bool:
        """Create Deployment with WordPress + MySQL sidecar"""
        try:
            from datetime import datetime, timedelta

            ttl_expires_at = datetime.utcnow() + timedelta(minutes=ttl_minutes)
            ttl_label = str(int(ttl_expires_at.timestamp()))

            deployment = client.V1Deployment(
                metadata=client.V1ObjectMeta(
                    name=customer_id,
                    namespace=self.namespace,
                    labels={
                        "app": "wordpress-clone",
                        "clone-id": customer_id,
                        "ttl-expires-at": ttl_label,
                    },
                ),
                spec=client.V1DeploymentSpec(
                    replicas=1,
                    selector=client.V1LabelSelector(
                        match_labels={"clone-id": customer_id}
                    ),
                    template=client.V1PodTemplateSpec(
                        metadata=client.V1ObjectMeta(
                            labels={
                                "app": "wordpress-clone",
                                "clone-id": customer_id,
                                "ttl-expires-at": ttl_label,
                            }
                        ),
                        spec=client.V1PodSpec(
                            restart_policy="Always",
                            containers=[
                                # WordPress container
                                client.V1Container(
                                    name="wordpress",
                                    image=self.docker_image,
                                    ports=[
                                        client.V1ContainerPort(
                                            container_port=80, name="http"
                                        )
                                    ],
                                    env=[
                                        client.V1EnvVar(
                                            name="WORDPRESS_DB_HOST",
                                            value="127.0.0.1:3306",
                                        ),
                                        client.V1EnvVar(
                                            name="WORDPRESS_DB_NAME",
                                            value="wordpress",
                                        ),
                                        client.V1EnvVar(
                                            name="WORDPRESS_DB_USER",
                                            value="wordpress",
                                        ),
                                        client.V1EnvVar(
                                            name="WORDPRESS_DB_PASSWORD",
                                            value=db_password,
                                        ),
                                        client.V1EnvVar(
                                            name="WP_ADMIN_USER", value="admin"
                                        ),
                                        client.V1EnvVar(
                                            name="WP_ADMIN_PASSWORD",
                                            value=wp_password,
                                        ),
                                        client.V1EnvVar(
                                            name="WP_ADMIN_EMAIL",
                                            value="admin@example.com",
                                        ),
                                        client.V1EnvVar(
                                            name="WP_SITE_URL",
                                            value=f"https://{customer_id}.clones.betaweb.ai",
                                        ),
                                    ],
                                    resources=client.V1ResourceRequirements(
                                        requests={"cpu": "250m", "memory": "512Mi"},
                                        limits={"cpu": "500m", "memory": "1Gi"},
                                    ),
                                    liveness_probe=client.V1Probe(
                                        http_get=client.V1HTTPGetAction(
                                            path="/", port=80
                                        ),
                                        initial_delay_seconds=30,
                                        period_seconds=10,
                                    ),
                                    readiness_probe=client.V1Probe(
                                        http_get=client.V1HTTPGetAction(
                                            path="/", port=80
                                        ),
                                        initial_delay_seconds=20,
                                        period_seconds=5,
                                    ),
                                ),
                                # MySQL sidecar container
                                client.V1Container(
                                    name="mysql",
                                    image="mysql:8.0",
                                    env=[
                                        client.V1EnvVar(
                                            name="MYSQL_DATABASE",
                                            value="wordpress",
                                        ),
                                        client.V1EnvVar(
                                            name="MYSQL_USER",
                                            value="wordpress",
                                        ),
                                        client.V1EnvVar(
                                            name="MYSQL_PASSWORD",
                                            value=db_password,
                                        ),
                                        client.V1EnvVar(
                                            name="MYSQL_ROOT_PASSWORD",
                                            value=db_password,
                                        ),
                                    ],
                                    resources=client.V1ResourceRequirements(
                                        requests={"cpu": "250m", "memory": "512Mi"},
                                        limits={"cpu": "500m", "memory": "1Gi"},
                                    ),
                                    liveness_probe=client.V1Probe(
                                        exec=client.V1ExecAction(
                                            command=[
                                                "mysqladmin",
                                                "ping",
                                                "-h127.0.0.1",
                                            ]
                                        ),
                                        initial_delay_seconds=30,
                                        period_seconds=10,
                                    ),
                                    readiness_probe=client.V1Probe(
                                        exec=client.V1ExecAction(
                                            command=[
                                                "mysqladmin",
                                                "ping",
                                                "-h127.0.0.1",
                                            ]
                                        ),
                                        initial_delay_seconds=5,
                                        period_seconds=5,
                                    ),
                                    volume_mounts=[
                                        client.V1VolumeMount(
                                            name="mysql-data",
                                            mount_path="/var/lib/mysql",
                                        )
                                    ],
                                ),
                            ],
                            volumes=[
                                client.V1Volume(
                                    name="mysql-data",
                                    empty_dir=client.V1EmptyDirVolumeSource(),
                                )
                            ],
                        ),
                    ),
                ),
            )

            self.apps_api.create_namespaced_deployment(self.namespace, deployment)
            logger.info(f"Deployment created with MySQL sidecar: {customer_id}")
            return True

        except ApiException as e:
            if e.status == 409:
                logger.warning(f"Deployment already exists: {customer_id}")
                return True
            logger.error(f"Deployment creation failed: {e}")
            return False

    def _wait_for_wordpress_ready(self, customer_id: str, timeout: int = 120) -> bool:
        """Wait for WordPress to be configured and responding"""
        try:
            import requests

            start_time = time.time()
            service_url = f"http://{customer_id}.{self.namespace}.svc.cluster.local"

            while time.time() - start_time < timeout:
                try:
                    resp = requests.get(
                        f"{service_url}/wp-json/custom-migrator/v1/status", timeout=5
                    )
                    if resp.status_code == 200:
                        logger.info(f"WordPress ready: {customer_id}")
                        return True
                except:
                    pass
                time.sleep(3)

            logger.warning(f"WordPress not ready after {timeout}s")
            return False
        except Exception as e:
            logger.error(f"Error waiting for WordPress: {e}")
            return False
