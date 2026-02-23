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
            await job_store.update_job_status(job_id, JobStatus.failed, error=error_msg)
            return {"success": False, "error": error_msg}

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
            await job_store.update_job_status(job_id, JobStatus.failed, error=error_msg)
            return {"success": False, "error": error_msg}

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
            await job_store.update_job_status(job_id, JobStatus.failed, error=error_msg)
            return {"success": False, "error": error_msg}

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
