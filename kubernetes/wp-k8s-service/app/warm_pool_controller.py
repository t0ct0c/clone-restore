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
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from kubernetes.stream import stream
from typing import List, Optional, Dict
import uuid
import time


class WarmPoolController:
    def __init__(self, namespace: str = "wordpress-staging"):
        self.namespace = namespace
        self.min_warm_pods = 2
        self.max_warm_pods = 4
        self.warm_label_selector = "pool-type=warm"

        # Load in-cluster Kubernetes config
        config.load_incluster_config()
        self.v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()

        # Pod configuration
        self.warm_pod_image = "044514005641.dkr.ecr.us-east-1.amazonaws.com/wp-k8s-service-clone:optimized-v13"
        self.mysql_image = "044514005641.dkr.ecr.us-east-1.amazonaws.com/mysql:8.0"
        self.resources = {
            "requests": {"cpu": "250m", "memory": "512Mi"},
            "limits": {"cpu": "500m", "memory": "1Gi"},
        }

    async def maintain_pool(self):
        """Background task: maintain 1-2 warm pods"""
        while True:
            try:
                warm_pods = self._get_warm_pods()

                # Install WordPress in initializing pods that are running
                for pod in warm_pods:
                    status = pod.metadata.labels.get("pool-status", "")
                    if status == "initializing" and self._is_pod_available(pod):
                        pod_name = pod.metadata.name
                        try:
                            await self._install_wordpress_in_pod(pod_name)
                        except Exception as e:
                            logger.error(
                                f"Failed to install WordPress in {pod_name}: {e}"
                            )

                # Count total warm pods and ready pods separately
                total_pods = len(warm_pods)
                available = len(
                    [
                        p
                        for p in warm_pods
                        if p.metadata.labels.get("pool-status") == "ready"
                    ]
                )

                if total_pods < self.min_warm_pods:
                    await self._create_warm_pod()
                    logger.info(
                        f"Created warm pod (total: {total_pods + 1}, available: {available})"
                    )

                elif total_pods > self.max_warm_pods:
                    # Only delete if we have excess AND they're old (> 2 minutes)
                    oldest = warm_pods[0]
                    pod_age = (
                        time.time() - oldest.metadata.creation_timestamp.timestamp()
                    )
                    if pod_age > 120:  # 2 minutes
                        await self._delete_pod(oldest.metadata.name)
                        logger.info(
                            f"Deleted excess warm pod (total: {total_pods - 1})"
                        )

                await asyncio.sleep(30)  # Check every 30s

            except Exception as e:
                logger.error(f"Pool maintenance error: {e}")
                await asyncio.sleep(60)

    async def assign_warm_pod(self, customer_id: str) -> Optional[str]:
        """Assign warm pod to clone, reset DB for new customer"""
        warm_pods = self._get_warm_pods()
        available = [
            p for p in warm_pods if p.metadata.labels.get("pool-status") == "ready"
        ]

        if not available:
            logger.warning("No warm pods available")
            return None

        pod_name = available[0].metadata.name

        # Reset database for new customer
        await self._reset_pod_database(pod_name, customer_id)

        # Tag pod with customer_id
        await self._tag_pod(pod_name, customer_id)

        # Rename credentials secret from warm pod to clone ID
        await self._rename_secret(pod_name, customer_id)

        logger.info(f"Assigned warm pod {pod_name} to {customer_id}")
        return pod_name

    async def return_to_pool(self, pod_name: str):
        """Reset pod and return to warm pool after TTL"""
        try:
            # Get clone-id before untagging (for secret cleanup)
            pod = self.v1.read_namespaced_pod(pod_name, self.namespace)
            clone_id = (
                pod.metadata.labels.get("clone-id") if pod.metadata.labels else None
            )

            # Clean database
            await self._reset_database(pod_name)

            # Clean filesystem
            await self._clean_filesystem(pod_name)

            # Remove customer labels
            await self._untag_pod(pod_name)

            # Delete clone-specific secret if exists
            if clone_id:
                await self._delete_clone_secret(clone_id)

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
        """Check if pod is running and ready (regardless of pool-status)"""
        if pod.status.phase != "Running":
            return False

        for condition in pod.status.conditions or []:
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

    async def _install_wordpress_in_pod(self, pod_name: str):
        """Install WordPress in warm pod using WP-CLI"""
        logger.info(f"Installing WordPress in {pod_name}...")

        # Get admin password from secret
        try:
            secret = self.v1.read_namespaced_secret(
                f"{pod_name}-credentials", self.namespace
            )
            admin_password = self._from_base64(secret.data["wordpress-password"])
            db_password = self._from_base64(secret.data["db-password"])
        except Exception as e:
            logger.error(f"Failed to get admin password: {e}")
            return

        # Download WP-CLI if not present
        try:
            stream(
                self.v1.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self.namespace,
                command=[
                    "sh",
                    "-c",
                    "which wp || curl -O https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar && chmod +x wp-cli.phar && mv wp-cli.phar /usr/local/bin/wp",
                ],
                container="wordpress",
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
            )
        except Exception as e:
            logger.error(f"Failed to download WP-CLI: {e}")
            return

        # WordPress installation is handled by docker-entrypoint.sh
        # Just activate the plugin (entrypoint already created wp-config.php and installed WP)
        try:
            stream(
                self.v1.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self.namespace,
                command=[
                    "wp",
                    "plugin",
                    "install",
                    "/plugin.zip",
                    "--activate",
                    "--force",
                    "--allow-root",
                ],
                container="wordpress",
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
            )
            logger.info(f"Activated plugin in warm pod {pod_name}")
        except Exception as e:
            logger.error(f"Failed to activate plugin: {e}")
            return

        # Set the plugin API key to a known value for warm pool
        try:
            stream(
                self.v1.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self.namespace,
                command=[
                    "wp",
                    "option",
                    "update",
                    "custom_migrator_api_key",
                    "migration-master-key",
                    "--allow-root",
                ],
                container="wordpress",
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
            )
            logger.info(f"Set plugin API key for warm pod {pod_name}")
        except Exception as e:
            logger.error(f"Failed to set API key: {e}")

        # Create wp-config.php first (required for WP-CLI commands)
        try:
            import base64

            wp_config = f"""<?php
define('DB_NAME', 'wordpress');
define('DB_USER', 'wordpress');
define('DB_PASSWORD', '{db_password}');
define('DB_HOST', '127.0.0.1:3306');
define('DB_CHARSET', 'utf8');
define('DB_COLLATE', '');
$table_prefix = 'wp_';
define('WP_DEBUG', false);
define('WP_SITEURL', 'http://{pod_name}.wordpress-staging.svc.cluster.local');
define('WP_HOME', 'http://{pod_name}.wordpress-staging.svc.cluster.local');
if ( ! defined( 'ABSPATH' ) ) {{
    define( 'ABSPATH', __DIR__ . '/' );
}}
require_once ABSPATH . 'wp-settings.php';
"""
            encoded_config = base64.b64encode(wp_config.encode()).decode()
            stream(
                self.v1.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self.namespace,
                command=[
                    "sh",
                    "-c",
                    f"echo '{encoded_config}' | base64 -d > /var/www/html/wp-config.php && chown www-data:www-data /var/www/html/wp-config.php",
                ],
                container="wordpress",
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
            )
            logger.info(f"Created wp-config.php for warm pod {pod_name}")
        except Exception as e:
            logger.error(f"Failed to create wp-config.php: {e}")
            return

        # Run WordPress installation via WP-CLI
        install_commands = [
            [
                "wp",
                "core",
                "install",
                f"--url=http://{pod_name}.wordpress-staging.svc.cluster.local",
                "--title=My Awesome Website",
                "--admin_user=admin",
                f"--admin_password={admin_password}",
                "--admin_email=admin@clones.betaweb.ai",
                "--skip-email",
            ],
            ["wp", "plugin", "install", "/plugin.zip", "--activate", "--force"],
        ]

        for cmd in install_commands:
            try:
                stream(
                    self.v1.connect_get_namespaced_pod_exec,
                    name=pod_name,
                    namespace=self.namespace,
                    command=cmd,
                    container="wordpress",
                    stderr=True,
                    stdin=False,
                    stdout=True,
                    tty=False,
                )
                logger.info(f"Executed: {' '.join(cmd)}")
            except Exception as e:
                logger.error(f"WP-CLI command failed: {e}")
                return

        # Mark pod as ready
        body = {"metadata": {"labels": {"pool-status": "ready"}}}
        self.v1.patch_namespaced_pod(pod_name, self.namespace, body)
        logger.info(f"WordPress installed in {pod_name}")

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
                image_pull_secrets=[
                    client.V1LocalObjectReference(name="ecr-registry-secret"),
                    client.V1LocalObjectReference(name="dockerhub-secret"),
                ],
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
                        # The import can make WP unresponsive for 30-60s
                        # while it drops/recreates all tables and runs
                        # search-replace.  Use generous thresholds so the
                        # liveness probe does not kill the container mid-import.
                        liveness_probe=client.V1Probe(
                            http_get=client.V1HTTPGetAction(path="/", port=80),
                            initial_delay_seconds=60,
                            period_seconds=10,
                            timeout_seconds=5,
                            failure_threshold=12,
                        ),
                        readiness_probe=client.V1Probe(
                            http_get=client.V1HTTPGetAction(path="/", port=80),
                            initial_delay_seconds=20,
                            period_seconds=5,
                        ),
                        volume_mounts=[
                            client.V1VolumeMount(
                                name="wordpress-data",
                                mount_path="/var/www/html",
                            )
                        ],
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
                            _exec=client.V1ExecAction(
                                command=[
                                    "sh",
                                    "-c",
                                    "mysqladmin ping -h127.0.0.1 -u root -p$MYSQL_ROOT_PASSWORD",
                                ]
                            ),
                            initial_delay_seconds=30,
                            period_seconds=10,
                        ),
                        readiness_probe=client.V1Probe(
                            _exec=client.V1ExecAction(
                                command=[
                                    "sh",
                                    "-c",
                                    "mysqladmin ping -h127.0.0.1 -u root -p$MYSQL_ROOT_PASSWORD",
                                ]
                            ),
                            initial_delay_seconds=45,
                            failure_threshold=12,
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
                        name="mysql-data",
                        empty_dir=client.V1EmptyDirVolumeSource(),
                    ),
                    client.V1Volume(
                        name="wordpress-data",
                        empty_dir=client.V1EmptyDirVolumeSource(),
                    ),
                ],
            ),
        )

        return pod

    async def _reset_pod_database(self, pod_name: str, customer_id: str):
        """Reset database for new customer via full wp core reinstall.

        The docker-entrypoint.sh creates tables with wrong schemas (e.g.
        ``CREATE TABLE wp_terms LIKE wp_posts``).  Neither TRUNCATE nor
        ``wp site empty`` can fix broken schemas — they leave WordPress in an
        unbootable state (missing wp_posts, wp_terms, etc.) which crashes
        Apache and causes "Connection refused" on import.

        The reliable fix is: ``wp db reset`` (drops all tables) followed by
        ``wp core install`` (recreates them with correct schemas).  This adds
        ~2-3 s to warm-pool assignment but guarantees a working WordPress.
        """
        logger.info(f"Starting database reset for pod {pod_name}")
        secret_name = f"{pod_name}-credentials"
        secret = self.v1.read_namespaced_secret(secret_name, self.namespace)
        db_password = self._from_base64(secret.data["db-password"])
        wp_password = self._from_base64(secret.data["wordpress-password"])

        # Step 1: Write wp-config.php so WP-CLI can connect to the database.
        await self._create_wp_config(pod_name, db_password)

        # Step 2: Drop ALL tables — clean slate.
        try:
            stream(
                self.v1.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self.namespace,
                command=["wp", "db", "reset", "--yes", "--allow-root"],
                container="wordpress",
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
            )
            logger.info(f"wp db reset completed for pod {pod_name}")
        except Exception as e:
            logger.warning(f"wp db reset failed: {e}")

        # Step 3: Reinstall WordPress core (creates all tables correctly).
        site_url = f"http://{pod_name}.wordpress-staging.svc.cluster.local"
        try:
            stream(
                self.v1.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self.namespace,
                command=[
                    "wp",
                    "core",
                    "install",
                    f"--url={site_url}",
                    "--title=WordPress Clone",
                    "--admin_user=admin",
                    f"--admin_password={wp_password}",
                    "--admin_email=admin@clones.betaweb.ai",
                    "--skip-email",
                    "--allow-root",
                ],
                container="wordpress",
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
            )
            logger.info(f"wp core install completed for pod {pod_name}")
        except Exception as e:
            logger.error(f"wp core install failed: {e}")

        # Step 4: Install and activate plugin, set API key.
        try:
            stream(
                self.v1.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self.namespace,
                command=[
                    "wp",
                    "plugin",
                    "install",
                    "/plugin.zip",
                    "--activate",
                    "--force",
                    "--allow-root",
                ],
                container="wordpress",
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
            )
            logger.info(f"Plugin installed and activated in pod {pod_name}")
        except Exception as e:
            logger.warning(f"Plugin install failed: {e}")

        # Step 4b: Create uploads directory and plugin temp directory.
        # wp core install does NOT create wp-content/uploads, so the import
        # plugin's download_archive() fails with "Destination directory …
        # does not exist or is not writable" when it tries to stream
        # the archive into wp-content/uploads/custom-migrator/tmp/.
        try:
            stream(
                self.v1.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self.namespace,
                command=[
                    "bash",
                    "-c",
                    "mkdir -p /var/www/html/wp-content/uploads/custom-migrator/tmp && "
                    "chown -R www-data:www-data /var/www/html/wp-content/uploads",
                ],
                container="wordpress",
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
            )
            logger.info(f"Created uploads directory in pod {pod_name}")
        except Exception as e:
            logger.warning(f"Failed to create uploads directory: {e}")

        try:
            stream(
                self.v1.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self.namespace,
                command=[
                    "wp",
                    "option",
                    "update",
                    "custom_migrator_api_key",
                    "migration-master-key",
                    "--allow-root",
                ],
                container="wordpress",
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
            )
        except Exception as e:
            logger.warning(f"Failed to set API key: {e}")

        # Step 5: Enable import on this target clone
        try:
            stream(
                self.v1.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self.namespace,
                command=[
                    "wp",
                    "option",
                    "update",
                    "custom_migrator_import_enabled",
                    "1",
                    "--allow-root",
                ],
                container="wordpress",
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
            )
        except Exception as e:
            logger.warning(f"Failed to enable import: {e}")

        # Step 6: Verify WordPress is serving HTTP requests.
        await self._verify_wordpress_health(pod_name)

        logger.info(f"Database reset complete for pod {pod_name}")

    async def _create_wp_config(self, pod_name: str, db_password: str):
        """Create wp-config.php in warm pod after database reset"""
        try:
            # Get pod IP for WP_HOME and WP_SITEURL
            pod = self.v1.read_namespaced_pod(pod_name, self.namespace)
            pod_ip = pod.status.pod_ip

            wp_config = f"""<?php
define('DB_NAME', 'wordpress');
define('DB_USER', 'wordpress');
define('DB_PASSWORD', '{db_password}');
define('DB_HOST', '127.0.0.1:3306');
define('DB_CHARSET', 'utf8');
define('DB_COLLATE', '');
$table_prefix = 'wp_';
define('WP_DEBUG', false);
define('WP_SITEURL', 'http://{pod_ip}');
define('WP_HOME', 'http://{pod_ip}');
if ( ! defined( 'ABSPATH' ) ) {{
    define( 'ABSPATH', __DIR__ . '/' );
}}
require_once ABSPATH . 'wp-settings.php';
"""

            # Write wp-config.php via k8s exec
            import base64

            encoded_config = base64.b64encode(wp_config.encode()).decode()

            stream(
                self.v1.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self.namespace,
                command=[
                    "sh",
                    "-c",
                    f"echo '{encoded_config}' | base64 -d > /var/www/html/wp-config.php && chown www-data:www-data /var/www/html/wp-config.php",
                ],
                container="wordpress",
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
            )
            logger.info(f"Created wp-config.php for pod {pod_name}")
        except Exception as e:
            logger.error(f"Failed to create wp-config.php: {e}")

    async def _activate_plugin_in_pod(self, pod_name: str):
        """Activate custom-migrator plugin using WP-CLI"""
        try:
            stream(
                self.v1.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self.namespace,
                command=["wp", "plugin", "activate", "custom-migrator", "--allow-root"],
                container="wordpress",
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
            )
            logger.info(f"Re-activated plugin in pod {pod_name}")
        except Exception as e:
            logger.error(f"Failed to activate plugin: {e}")

    async def _reset_database(self, pod_name: str):
        """Reset WordPress database via full reinstall for warm pool reuse.

        Uses ``wp db reset`` + ``wp core install`` to guarantee all tables
        exist with correct schemas.  This is the same strategy as
        ``_reset_pod_database`` — see its docstring for rationale.
        """
        secret_name = f"{pod_name}-credentials"
        secret = self.v1.read_namespaced_secret(secret_name, self.namespace)
        db_password = self._from_base64(secret.data["db-password"])
        wp_password = self._from_base64(secret.data["wordpress-password"])

        # Write wp-config.php first
        await self._create_wp_config(pod_name, db_password)

        # Drop all tables
        try:
            stream(
                self.v1.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self.namespace,
                command=["wp", "db", "reset", "--yes", "--allow-root"],
                container="wordpress",
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
            )
            logger.info(f"wp db reset completed for {pod_name}")
        except Exception as e:
            logger.warning(f"wp db reset failed for {pod_name}: {e}")

        # Reinstall WordPress core
        site_url = f"http://{pod_name}.wordpress-staging.svc.cluster.local"
        try:
            stream(
                self.v1.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self.namespace,
                command=[
                    "wp",
                    "core",
                    "install",
                    f"--url={site_url}",
                    "--title=WordPress Clone",
                    "--admin_user=admin",
                    f"--admin_password={wp_password}",
                    "--admin_email=admin@clones.betaweb.ai",
                    "--skip-email",
                    "--allow-root",
                ],
                container="wordpress",
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
            )
            logger.info(f"wp core install completed for {pod_name}")
        except Exception as e:
            logger.error(f"wp core install failed for {pod_name}: {e}")

        # Reinstall and activate plugin, set API key
        try:
            stream(
                self.v1.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self.namespace,
                command=[
                    "wp",
                    "plugin",
                    "install",
                    "/plugin.zip",
                    "--activate",
                    "--force",
                    "--allow-root",
                ],
                container="wordpress",
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
            )
        except Exception as e:
            logger.warning(f"Plugin install failed for {pod_name}: {e}")

        # Create uploads directory (wp core install doesn't create it)
        try:
            stream(
                self.v1.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self.namespace,
                command=[
                    "bash",
                    "-c",
                    "mkdir -p /var/www/html/wp-content/uploads/custom-migrator/tmp && "
                    "chown -R www-data:www-data /var/www/html/wp-content/uploads",
                ],
                container="wordpress",
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
            )
        except Exception as e:
            logger.warning(f"Failed to create uploads dir for {pod_name}: {e}")

        try:
            stream(
                self.v1.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self.namespace,
                command=[
                    "wp",
                    "option",
                    "update",
                    "custom_migrator_api_key",
                    "migration-master-key",
                    "--allow-root",
                ],
                container="wordpress",
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
            )
        except Exception as e:
            logger.warning(f"Failed to reset API key for {pod_name}: {e}")

    async def _verify_wordpress_health(
        self, pod_name: str, retries: int = 5, delay: float = 2.0
    ):
        """Verify WordPress is responding to HTTP requests after a reset.

        Runs curl inside the wordpress container to confirm Apache + PHP are
        serving pages.  This catches the exact failure mode where a bad DB
        reset crashes Apache and leaves the pod in a Connection-refused state.
        """
        for attempt in range(1, retries + 1):
            try:
                result = stream(
                    self.v1.connect_get_namespaced_pod_exec,
                    name=pod_name,
                    namespace=self.namespace,
                    command=[
                        "sh",
                        "-c",
                        "curl -sf -o /dev/null -w '%{http_code}' http://localhost/ || echo 'FAIL'",
                    ],
                    container="wordpress",
                    stderr=True,
                    stdin=False,
                    stdout=True,
                    tty=False,
                )
                result_str = str(result).strip()
                if "200" in result_str or "301" in result_str or "302" in result_str:
                    logger.info(
                        f"WordPress health check passed for {pod_name} (attempt {attempt})"
                    )
                    return True
                logger.warning(
                    f"WordPress health check returned {result_str} for {pod_name} (attempt {attempt})"
                )
            except Exception as e:
                logger.warning(
                    f"WordPress health check failed for {pod_name} (attempt {attempt}): {e}"
                )

            if attempt < retries:
                await asyncio.sleep(delay)

        logger.error(
            f"WordPress health check FAILED after {retries} attempts for {pod_name}"
        )
        return False

    async def _clean_filesystem(self, pod_name: str):
        """Clean WordPress uploads and cache"""
        commands = [
            "rm -rf /var/www/html/wp-content/uploads/*",
            "rm -rf /var/www/html/wp-content/cache/*",
            "rm -rf /var/www/html/wp-content/debug.log",
            "chown -R www-data:www-data /var/www/html/wp-content/uploads",
            "chmod 755 /var/www/html/wp-content/uploads",
        ]

        for cmd in commands:
            try:
                stream(
                    self.v1.connect_get_namespaced_pod_exec,
                    name=pod_name,
                    namespace=self.namespace,
                    command=["sh", "-c", cmd],
                    container="wordpress",
                    stderr=True,
                    stdin=False,
                    stdout=True,
                    tty=False,
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

    async def _rename_secret(self, old_name: str, customer_id: str):
        """Rename credentials secret from warm pod name to clone ID"""
        old_secret_name = f"{old_name}-credentials"
        new_secret_name = f"{customer_id}-credentials"

        try:
            # Get old secret
            old_secret = self.v1.read_namespaced_secret(old_secret_name, self.namespace)

            # Create new secret with clone ID
            new_secret = client.V1Secret(
                metadata=client.V1ObjectMeta(
                    name=new_secret_name,
                    namespace=self.namespace,
                    labels={"clone-id": customer_id, "app": "wordpress-clone"},
                ),
                data=old_secret.data,
            )

            self.v1.create_namespaced_secret(self.namespace, new_secret)

            # Delete old secret
            self.v1.delete_namespaced_secret(old_secret_name, self.namespace)

            logger.info(f"Renamed secret {old_secret_name} -> {new_secret_name}")

        except Exception as e:
            logger.error(f"Failed to rename secret: {e}")

    async def _delete_clone_secret(self, clone_id: str):
        """Delete clone-specific credentials secret"""
        secret_name = f"{clone_id}-credentials"
        try:
            self.v1.delete_namespaced_secret(secret_name, self.namespace)
            logger.info(f"Deleted clone secret: {secret_name}")
        except ApiException as e:
            if e.status != 404:
                logger.warning(f"Failed to delete secret {secret_name}: {e}")

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

    async def _mark_pod_ready(self, pod_name: str):
        """Mark initializing pod as ready"""
        body = {"metadata": {"labels": {"pool-status": "ready"}}}
        self.v1.patch_namespaced_pod(pod_name, self.namespace, body)
        logger.info(f"Marked pod {pod_name} as ready")

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
