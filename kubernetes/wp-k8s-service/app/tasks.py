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
from .browser_setup import AsyncCamoufox
from .wp_plugin import PluginClient


@dramatiq.actor(queue_name="clone-queue", max_retries=3)
async def clone_wordpress(job_id: str) -> Dict:
    """Clone WordPress site asynchronously."""
    job_store = get_job_store()
    provisioner = K8sProvisioner()
    
    try:
        job = await job_store.get_job(job_id)
        if not job:
            return {"success": False, "error": "Job not found"}
        
        request = job.request_payload
        customer_id = request.get("customer_id")
        
        logger.info(f"Starting clone job {job_id} for {customer_id}")
        await job_store.update_job_status(job_id, JobStatus.running, progress=10)
        
        # Provision target
        result = provisioner.provision_target(customer_id, request.get("ttl_minutes", 60))
        
        if result.get("success"):
            await job_store.update_job_status(
                job_id, JobStatus.completed, progress=100, result=result
            )
            return {"success": True, **result}
        else:
            await job_store.update_job_status(
                job_id, JobStatus.failed, error=result.get("message")
            )
            return {"success": False, **result}
            
    except Exception as e:
        logger.error(f"Clone job {job_id} failed: {e}")
        await job_store.update_job_status(job_id, JobStatus.failed, error=str(e))
        return {"success": False, "error": str(e)}
