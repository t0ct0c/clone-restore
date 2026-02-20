"""
Kubernetes Provisioning Module

Handles ephemeral WordPress clone provisioning on Kubernetes using Jobs with TTL.
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
    """Provision ephemeral WordPress clones on Kubernetes with Jobs + TTL"""

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
        self.networking_api = client.NetworkingV1Api()
        self.dynamic_client = dynamic.DynamicClient(client.ApiClient())
        self.namespace = namespace

        # Configuration from environment variables
        self.docker_image = os.getenv(
            "WORDPRESS_IMAGE",
            "044514005641.dkr.ecr.us-east-1.amazonaws.com/wordpress-target-sqlite:latest",
        )
        self.traefik_dns = os.getenv("TRAEFIK_DNS", "clones.betaweb.ai")

        # Shared RDS configuration (from ConfigMap)
        self.use_shared_rds = os.getenv("USE_SHARED_RDS", "true").lower() == "true"
        self.shared_rds_host = os.getenv("SHARED_RDS_HOST", "")
        self.shared_rds_password = os.getenv("SHARED_RDS_PASSWORD", "")

        logger.info(f"K8sProvisioner initialized for namespace: {namespace}")
        logger.info(f"Shared RDS: {self.use_shared_rds}, Host: {self.shared_rds_host}")

    def provision_target(self, customer_id: str, ttl_minutes: int = 30) -> Dict:
        """
        Provision ephemeral WordPress clone using Kubernetes Job with TTL

        Args:
            customer_id: Unique clone identifier
            ttl_minutes: Time-to-live in minutes (default: 30)

        Returns:
            Dict with clone details (URL, credentials, status)
        """
        try:
            logger.info(f"Provisioning Kubernetes clone for customer {customer_id}")

            # 1. Generate credentials
            wp_password = self._generate_password()
            db_password = self._generate_password()
            api_key = "migration-master-key"  # Fixed key for setup phase

            # 2. Create Secret for credentials
            secret_created = self._create_secret(
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

            # 3. Create database for this clone
            if self.use_shared_rds:
                db_created = self._create_database_on_shared_rds(
                    customer_id=customer_id, db_password=db_password
                )

                if not db_created:
                    self._cleanup_secret(customer_id)
                    return {
                        "success": False,
                        "error_code": "DB_CREATE_FAILED",
                        "message": "Failed to create database on shared RDS",
                    }

            # 4. Create Job with TTL for WordPress container
            job_created = self._create_job(
                customer_id=customer_id, ttl_minutes=ttl_minutes
            )

            if not job_created:
                self._cleanup_secret(customer_id)
                return {
                    "success": False,
                    "error_code": "JOB_CREATE_FAILED",
                    "message": "Failed to create Kubernetes Job",
                }

            # 5. Wait for pod to be running
            pod_ready = self._wait_for_pod_ready(customer_id, timeout=180)

            if not pod_ready:
                logger.warning(f"Pod not ready after 180s, but continuing...")

            # 6. Create Service to expose the pod
            service_created = self._create_service(customer_id)

            if not service_created:
                self._cleanup_job(customer_id)
                self._cleanup_secret(customer_id)
                return {
                    "success": False,
                    "error_code": "SERVICE_CREATE_FAILED",
                    "message": "Failed to create Kubernetes Service",
                }

            # 7. Create Kubernetes Ingress for Traefik subdomain routing
            ingress_created = self._create_ingress(customer_id)

            if not ingress_created:
                logger.warning("Ingress creation failed, clone may not be accessible")

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

    def _create_secret(
        self, customer_id: str, wp_password: str, db_password: str, api_key: str
    ) -> bool:
        """Create Kubernetes Secret for WordPress credentials"""
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
            return True

        except ApiException as e:
            logger.error(f"Failed to create Secret: {e}")
            return False

    def _create_database_on_shared_rds(
        self, customer_id: str, db_password: str
    ) -> bool:
        """Create MySQL database on shared RDS instance"""
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

            # Create database and user
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {db_name}")
            cursor.execute(
                f"CREATE USER IF NOT EXISTS '{db_user}'@'%' IDENTIFIED BY '{db_password}'"
            )
            cursor.execute(f"GRANT ALL PRIVILEGES ON {db_name}.* TO '{db_user}'@'%'")
            cursor.execute("FLUSH PRIVILEGES")

            cursor.close()
            connection.close()

            logger.info(f"Database created on shared RDS: {db_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to create database on shared RDS: {e}")
            return False

    def _create_job(self, customer_id: str, ttl_minutes: int) -> bool:
        """Create Kubernetes Job with TTL for auto-cleanup"""
        try:
            # Sanitize customer_id for database name
            db_name = f"wp_{customer_id.replace('-', '_')}"
            db_user = db_name

            # Determine database host
            if self.use_shared_rds:
                db_host = self.shared_rds_host
            else:
                db_host = f"mysql.{self.namespace}.svc.cluster.local"

            # Job spec with TTL
            job = client.V1Job(
                metadata=client.V1ObjectMeta(
                    name=customer_id,
                    namespace=self.namespace,
                    labels={"app": "wordpress-clone", "clone-id": customer_id},
                ),
                spec=client.V1JobSpec(
                    # TTL for automatic cleanup after completion
                    ttl_seconds_after_finished=ttl_minutes * 60,
                    # Job should complete after starting (keeps pod running)
                    completions=1,
                    parallelism=1,
                    backoff_limit=0,  # Don't retry on failure
                    template=client.V1PodTemplateSpec(
                        metadata=client.V1ObjectMeta(
                            labels={"app": "wordpress-clone", "clone-id": customer_id}
                        ),
                        spec=client.V1PodSpec(
                            restart_policy="Never",
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

            self.batch_api.create_namespaced_job(namespace=self.namespace, body=job)

            logger.info(f"Job created: {customer_id} (TTL: {ttl_minutes}min)")
            return True

        except ApiException as e:
            logger.error(f"Failed to create Job: {e}")
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

        except Exception as e:
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

    def _cleanup_job(self, customer_id: str):
        """Delete Job (and its pods)"""
        try:
            self.batch_api.delete_namespaced_job(
                name=customer_id,
                namespace=self.namespace,
                propagation_policy="Foreground",
            )
            logger.info(f"Deleted Job: {customer_id}")
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
