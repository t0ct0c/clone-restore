"""
Redis-based job store for tracking Dramatiq background tasks.
"""

import json
import redis.asyncio as redis
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Dict, Any
from loguru import logger
import uuid

class JobType(str, Enum):
    clone = "clone"
    restore = "restore"
    delete = "delete"

class JobStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"

class Job:
    def __init__(self, job_id: str, job_type: JobType, request_payload: dict, ttl_minutes: int = 60):
        self.job_id = job_id
        self.type = job_type
        self.status = JobStatus.pending
        self.progress = 0
        self.request_payload = request_payload
        self.result = None
        self.error = None
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
        self.completed_at = None
        self.ttl_expires_at = datetime.utcnow() + timedelta(minutes=ttl_minutes)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "type": self.type.value,
            "status": self.status.value,
            "progress": self.progress,
            "request_payload": self.request_payload,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "ttl_expires_at": self.ttl_expires_at.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Job':
        job = cls(
            job_id=data["job_id"],
            job_type=JobType(data["type"]),
            request_payload=data["request_payload"],
        )
        job.status = JobStatus(data["status"])
        job.progress = data["progress"]
        job.result = data.get("result")
        job.error = data.get("error")
        job.created_at = datetime.fromisoformat(data["created_at"])
        job.updated_at = datetime.fromisoformat(data["updated_at"])
        job.completed_at = datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None
        job.ttl_expires_at = datetime.fromisoformat(data["ttl_expires_at"])
        return job

class JobStore:
    def __init__(self, redis_url: str = "redis://redis-master.wordpress-staging.svc.cluster.local:6379/0"):
        self.redis_url = redis_url
        self.redis_client = None
        self.key_prefix = "job:"
        logger.info("Redis JobStore initialized")
    
    async def initialize(self) -> None:
        logger.info(f"Connecting to Redis: {self.redis_url}")
        self.redis_client = redis.from_url(self.redis_url, decode_responses=True)
        logger.info("Redis connection established")
    
    async def create_job(self, job_type: JobType, request_payload: dict, ttl_minutes: int = 60) -> Job:
        job_id = str(uuid.uuid4())
        job = Job(job_id, job_type, request_payload, ttl_minutes)
        await self.redis_client.setex(
            f"{self.key_prefix}{job_id}",
            int(ttl_minutes * 60 * 2),  # TTL = 2x job TTL
            json.dumps(job.to_dict())
        )
        logger.info(f"Created job {job_id}")
        return job
    
    async def get_job(self, job_id: str) -> Optional[Job]:
        data = await self.redis_client.get(f"{self.key_prefix}{job_id}")
        if not data:
            return None
        return Job.from_dict(json.loads(data))
    
    async def update_job_status(self, job_id: str, status: JobStatus, progress: int = None, result: dict = None, error: str = None) -> Job:
        job = await self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        
        job.status = status
        job.updated_at = datetime.utcnow()
        if progress is not None:
            job.progress = progress
        if result is not None:
            job.result = result
        if error is not None:
            job.error = error
        if status in [JobStatus.completed, JobStatus.failed, JobStatus.cancelled]:
            job.completed_at = datetime.utcnow()
        
        await self.redis_client.setex(
            f"{self.key_prefix}{job_id}",
            7200,  # 2 hours TTL
            json.dumps(job.to_dict())
        )
        logger.info(f"Updated job {job_id}: status={status.value}, progress={progress}")
        return job

# Global singleton
_job_store = None

def get_job_store() -> JobStore:
    global _job_store
    if _job_store is None:
        _job_store = JobStore()
    return _job_store

async def init_job_store(redis_url: str = None) -> None:
    global _job_store
    _job_store = JobStore(redis_url)
    await _job_store.initialize()
