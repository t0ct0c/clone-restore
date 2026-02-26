"""
Dramatiq tasks for async WordPress clone/restore operations.
"""

# Import broker to configure Dramatiq
from .dramatiq_config import broker  # noqa: F401

import dramatiq
from loguru import logger
from datetime import datetime
from typing import Dict, Optional

from .job_store import JobStore, JobType, JobStatus, get_job_store
from .k8s_provisioner import K8sProvisioner

from .wp_plugin import PluginClient


@dramatiq.actor(queue_name="clone-queue", max_retries=3)
async def clone_wordpress(job_id: str) -> Dict:
    """Clone WordPress site asynchronously (full clone with browser)."""
    from .browser_setup import setup_wordpress_with_browser
    from .main import perform_clone

    job_store = get_job_store()
    provisioner = K8sProvisioner()
    provision_result = None

    try:
        job = await job_store.get_job(job_id)
        if not job:
            return {"success": False, "error": "Job not found"}

        request = job.request_payload
        customer_id = request.get("customer_id")
        source_url = request.get("source_url")
        source_username = request.get("source_username")
        source_password = request.get("source_password")
        ttl_minutes = request.get("ttl_minutes", 30)

        logger.info(f"Starting clone job {job_id} for {customer_id} from {source_url}")
        await job_store.update_job_status(job_id, JobStatus.running, progress=10)

        # Step 1: Provision target WordPress
        logger.info(f"Provisioning target for {customer_id}")
        provision_result = provisioner.provision_target(customer_id, ttl_minutes)

        if not provision_result.get("success"):
            await job_store.update_job_status(
                job_id,
                JobStatus.failed,
                error=provision_result.get("message", "Unknown error"),
            )
            return {"success": False, **provision_result}

        await job_store.update_job_status(job_id, JobStatus.running, progress=30)

        target_url = provision_result.get("target_url")
        target_username = provision_result.get("wordpress_username", "admin")
        target_password = provision_result.get("wordpress_password")

        # Step 2: Setup source with browser to get API key
        logger.info(f"Setting up source {source_url}")
        source_result = await setup_wordpress_with_browser(
            str(source_url), source_username, source_password, role="source"
        )

        if not source_result.get("success"):
            error_msg = source_result.get("message", "Source setup failed")
            # Include provision credentials even on failure so users can access the clone
            await job_store.update_job_status(
                job_id, JobStatus.failed, error=error_msg, result=provision_result
            )
            return {"success": False, "error": error_msg, **provision_result}

        await job_store.update_job_status(job_id, JobStatus.running, progress=50)

        # Step 3: Setup target - skip browser for all provisioned targets (plugin pre-installed)
        # Both warm pool and cold provision have custom-migrator plugin ready
        logger.info(f"Target is provisioned, using direct API (plugin pre-installed)")
        target_result = {
            "success": True,
            "api_key": "migration-master-key",
            "import_enabled": True,
            "message": "Provisioned target - plugin pre-activated",
        }

        if not target_result.get("success"):
            error_msg = target_result.get("message", "Target setup failed")
            # Include provision credentials even on failure so users can access the clone
            await job_store.update_job_status(
                job_id, JobStatus.failed, error=error_msg, result=provision_result
            )
            return {"success": False, "error": error_msg, **provision_result}

        await job_store.update_job_status(job_id, JobStatus.running, progress=70)

        # Step 4: Perform clone
        logger.info(f"Cloning {source_url} to {target_url}")
        clone_result = perform_clone(
            str(source_url),
            source_result["api_key"],
            target_url,
            target_result["api_key"],
            public_target_url=provision_result.get("public_url"),
            admin_user=target_username,
            admin_password=target_password,
        )

        if not clone_result.get("success"):
            error_msg = clone_result.get("message", "Clone failed")
            # Include provision credentials even on failure so users can access the clone
            await job_store.update_job_status(
                job_id, JobStatus.failed, error=error_msg, result=provision_result
            )
            return {"success": False, "error": error_msg, **provision_result}

        # Step 5: Ensure HTTPS flag survives import plugin's wp-config rewrite.
        # Pods sit behind a TLS-terminating LB so WordPress always receives
        # HTTP; without $_SERVER['HTTPS']='on' the admin login redirect-loops.
        pod_name = provision_result.get("pod_name")
        if pod_name:
            try:
                from kubernetes import client as k8s_client, config as k8s_config
                from kubernetes.stream import stream as k8s_stream

                k8s_config.load_incluster_config()
                v1 = k8s_client.CoreV1Api()
                k8s_stream(
                    v1.connect_get_namespaced_pod_exec,
                    name=pod_name,
                    namespace="wordpress-staging",
                    command=[
                        "bash",
                        "-c",
                        # Inject the line only if not already present
                        "grep -q 'HTTPS.*on' /var/www/html/wp-config.php || "
                        "sed -i '/require_once.*wp-settings/i "
                        '\\$_SERVER["HTTPS"] = "on";\' '
                        "/var/www/html/wp-config.php",
                    ],
                    container="wordpress",
                    stderr=True,
                    stdin=False,
                    stdout=True,
                    tty=False,
                )
                logger.info(f"Ensured HTTPS flag in wp-config.php for {pod_name}")
            except Exception as e:
                logger.warning(f"Failed to inject HTTPS flag: {e}")

        await job_store.update_job_status(
            job_id, JobStatus.completed, progress=100, result=provision_result
        )
        logger.info(f"Clone job {job_id} completed successfully")
        return {"success": True, **provision_result}

    except Exception as e:
        logger.error(f"Clone job {job_id} failed: {e}")
        await job_store.update_job_status(job_id, JobStatus.failed, error=str(e))
        return {"success": False, "error": str(e)}

    finally:
        # If provision succeeded but job failed later, return pod to warm pool
        if (
            provision_result
            and provision_result.get("warm_pool")
            and not provision_result.get("success", True)
        ):
            try:
                from .warm_pool_controller import WarmPoolController
                import asyncio

                warm_pool = WarmPoolController(namespace=provisioner.namespace)
                pod_name = provision_result.get("pod_name")
                if pod_name:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(warm_pool.return_to_pool(pod_name))
                        logger.info(
                            f"Returned pod {pod_name} to warm pool after job failure"
                        )
                    finally:
                        loop.close()
            except Exception as e:
                logger.error(f"Failed to return pod to warm pool: {e}")


@dramatiq.actor(queue_name="clone-queue", max_retries=0, time_limit=600_000)
async def restore_wordpress(job_id: str) -> Dict:
    """Restore WordPress site asynchronously."""
    from .browser_setup import setup_wordpress_with_browser
    from .main import (
        perform_clone,
    )  # Reuse perform_clone for now, will extract perform_restore later
    from .job_store import get_job_store, JobStatus
    import requests

    job_store = get_job_store()

    try:
        job = await job_store.get_job(job_id)
        if not job:
            return {"success": False, "error": "Job not found"}

        request = job.request_payload
        source_url = request.get("source_url")
        source_username = request.get("source_username")
        source_password = request.get("source_password")
        target_url = request.get("target_url")
        target_username = request.get("target_username")
        target_password = request.get("target_password")
        preserve_plugins = request.get("preserve_plugins", True)
        preserve_themes = request.get("preserve_themes", False)

        logger.info(f"Starting restore job {job_id} from {source_url} to {target_url}")
        await job_store.update_job_status(job_id, JobStatus.running, progress=10)

        # Step 1: Setup source
        logger.info(f"Setting up source {source_url}")
        is_clone_source = "/clone-" in source_url or ".clones.betaweb.ai" in source_url

        if is_clone_source:
            # Try migration-master-key first for clones
            logger.info("Source is a clone, auto-detecting API key...")
            source_api_key = None
            candidate_keys = ["migration-master-key"]

            # Pre-check: verify clone is healthy and find working API key
            health_url = (
                f"{source_url.rstrip('/')}/?rest_route=/custom-migrator/v1/status"
            )

            for candidate_key in candidate_keys:
                try:
                    health_resp = requests.get(
                        health_url,
                        headers={"X-Migrator-Key": candidate_key},
                        timeout=15,
                    )
                    if health_resp.status_code == 200:
                        source_api_key = candidate_key
                        logger.info(f"Clone API key found: {candidate_key[:10]}...")
                        break
                except requests.RequestException as e:
                    logger.warning(f"Clone health check failed: {e}")
                    await job_store.update_job_status(
                        job_id,
                        JobStatus.failed,
                        error=f"Source clone is unreachable: {str(e)}",
                    )
                    return {
                        "success": False,
                        "error": f"Source clone is unreachable: {str(e)}",
                    }

            if source_api_key is None:
                # Fall back to browser automation
                logger.info(
                    "No candidate key worked for clone, using browser automation..."
                )
                source_result = await setup_wordpress_with_browser(
                    source_url, source_username, source_password, role="source"
                )
                if not source_result.get("success"):
                    error_msg = source_result.get("message", "Source setup failed")
                    await job_store.update_job_status(
                        job_id, JobStatus.failed, error=error_msg
                    )
                    return {"success": False, "error": error_msg}
                source_api_key = source_result["api_key"]
        else:
            # Use browser automation for regular sites
            source_result = await setup_wordpress_with_browser(
                source_url, source_username, source_password, role="source"
            )
            if not source_result.get("success"):
                error_msg = source_result.get("message", "Source setup failed")
                await job_store.update_job_status(
                    job_id, JobStatus.failed, error=error_msg
                )
                return {"success": False, "error": error_msg}
            source_api_key = source_result["api_key"]

        await job_store.update_job_status(job_id, JobStatus.running, progress=30)

        # Step 2: Setup target (always use browser)
        logger.info(f"Setting up target {target_url}")
        target_result = await setup_wordpress_with_browser(
            target_url, target_username, target_password, role="target"
        )
        if not target_result.get("success"):
            error_msg = target_result.get("message", "Target setup failed")
            await job_store.update_job_status(job_id, JobStatus.failed, error=error_msg)
            return {"success": False, "error": error_msg}
        target_api_key = target_result["api_key"]

        await job_store.update_job_status(job_id, JobStatus.running, progress=50)

        # Step 3: Perform restore (reusing clone logic for now)
        logger.info(f"Restoring from {source_url} to {target_url}")

        # Use perform_clone for now (preserve options not yet implemented)
        # TODO: Extract perform_restore function that handles preserve_plugins/preserve_themes
        restore_result = perform_clone(
            source_url,
            source_api_key,
            target_url,
            target_api_key,
        )

        if not restore_result.get("success"):
            error_msg = restore_result.get("message", "Restore failed")
            await job_store.update_job_status(job_id, JobStatus.failed, error=error_msg)
            return {"success": False, "error": error_msg}

        await job_store.update_job_status(
            job_id, JobStatus.completed, progress=100, result=restore_result
        )
        logger.info(f"Restore job {job_id} completed successfully")
        return {"success": True, **restore_result}

    except Exception as e:
        logger.error(f"Restore job {job_id} failed: {e}")
        await job_store.update_job_status(job_id, JobStatus.failed, error=str(e))
        return {"success": False, "error": str(e)}
