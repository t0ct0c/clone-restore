"""
Async job store for tracking Dramatiq background tasks.
Uses SQLAlchemy with aiomysql driver for async MySQL access.
"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base, Mapped, mapped_column
from sqlalchemy import select, func, String, JSON
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, List, Dict, Any
from loguru import logger
import uuid
import json

Base = declarative_base()


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


class Job(Base):
    """SQLAlchemy model for jobs table."""

    __tablename__ = "jobs"

    job_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    type: Mapped[JobType] = mapped_column(nullable=False)
    status: Mapped[JobStatus] = mapped_column(nullable=False, default=JobStatus.pending)
    progress: Mapped[int] = mapped_column(default=0)
    request_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    ttl_expires_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    def to_dict(self) -> Dict[str, Any]:
        """Convert job to dictionary for API responses."""
        return {
            "job_id": self.job_id,
            "type": self.type.value,
            "status": self.status.value,
            "progress": self.progress,
            "request_payload": self.request_payload,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat()
            if self.completed_at
            else None,
            "ttl_expires_at": self.ttl_expires_at.isoformat()
            if self.ttl_expires_at
            else None,
        }


class JobStore:
    """
    Async job store for managing background job state.

    Usage:
        job_store = JobStore()
        await job_store.initialize()

        job = await job_store.create_job(
            job_type=JobType.clone,
            request_payload={"source_url": "...", "customer_id": "..."}
        )
    """

    def __init__(self, database_url: str = None):
        self.database_url = database_url
        self.engine = None
        self.session_factory = None
        logger.info("JobStore initialized")

    async def initialize(self) -> None:
        """Initialize database engine and session factory."""
        if not self.database_url:
            raise ValueError("DATABASE_URL not provided")

        logger.info(f"Connecting to database: {self.database_url[:50]}...")

        self.engine = create_async_engine(
            self.database_url,
            echo=False,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
        )

        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        logger.info("Database connection established")

    async def close(self) -> None:
        """Close database connections."""
        if self.engine:
            await self.engine.dispose()
            logger.info("Database connections closed")

    async def create_job(
        self,
        job_type: JobType,
        request_payload: Dict[str, Any],
        ttl_minutes: int = 60,
    ) -> Job:
        """
        Create a new job record.

        Args:
            job_type: Type of job (clone, restore, delete)
            request_payload: Original request data
            ttl_minutes: Time-to-live in minutes (default 60)

        Returns:
            Created Job object
        """
        job_id = str(uuid.uuid4())
        ttl_expires_at = datetime.utcnow() + timedelta(minutes=ttl_minutes)

        async with self.session_factory() as session:
            job = Job(
                job_id=job_id,
                type=job_type,
                status=JobStatus.pending,
                progress=0,
                request_payload=request_payload,
                ttl_expires_at=ttl_expires_at,
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)

            logger.info(
                f"Created job {job_id} (type={job_type.value}, ttl={ttl_minutes}m)"
            )
            return job

    async def get_job(self, job_id: str) -> Optional[Job]:
        """
        Get job by ID.

        Args:
            job_id: Job UUID

        Returns:
            Job object or None if not found
        """
        async with self.session_factory() as session:
            result = await session.execute(select(Job).where(Job.job_id == job_id))
            return result.scalar_one_or_none()

    async def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        progress: int = None,
        result: Dict[str, Any] = None,
        error: str = None,
    ) -> Job:
        """
        Update job status and related fields.

        Args:
            job_id: Job UUID
            status: New status
            progress: Progress percentage (0-100)
            result: Result data (for completed jobs)
            error: Error message (for failed jobs)

        Returns:
            Updated Job object
        """
        async with self.session_factory() as session:
            stmt = select(Job).where(Job.job_id == job_id)
            query_result = await session.execute(stmt)
            job = query_result.scalar_one_or_none()

            if not job:
                raise ValueError(f"Job {job_id} not found")

            job.status = status

            if progress is not None:
                job.progress = progress

            if result is not None:
                job.result = result

            if error is not None:
                job.error = error

            if status in (JobStatus.completed, JobStatus.failed, JobStatus.cancelled):
                job.completed_at = datetime.utcnow()

            await session.commit()
            await session.refresh(job)

            logger.info(
                f"Updated job {job_id}: status={status.value}, progress={progress}"
            )
            return job

    async def list_jobs(
        self,
        status: JobStatus = None,
        job_type: JobType = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Job]:
        """
        List jobs with optional filtering.

        Args:
            status: Filter by status
            job_type: Filter by type
            limit: Maximum results
            offset: Pagination offset

        Returns:
            List of Job objects
        """
        async with self.session_factory() as session:
            query = select(Job)

            if status:
                query = query.where(Job.status == status)

            if job_type:
                query = query.where(Job.type == job_type)

            query = query.order_by(Job.created_at.desc())
            query = query.offset(offset).limit(limit)

            result = await session.execute(query)
            return list(result.scalars().all())

    async def cleanup_expired_jobs(self) -> int:
        """
        Delete jobs that have passed their TTL expiration.

        Returns:
            Number of jobs deleted
        """
        from sqlalchemy import delete

        async with self.session_factory() as session:
            query = delete(Job).where(Job.ttl_expires_at < datetime.utcnow())
            result = await session.execute(query)
            await session.commit()

            deleted = result.rowcount
            if deleted > 0:
                logger.info(f"Cleaned up {deleted} expired jobs")

            return deleted

    async def get_pending_jobs(self) -> List[Job]:
        """Get all pending jobs for processing."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(Job)
                .where(Job.status == JobStatus.pending)
                .order_by(Job.created_at.asc())
            )
            return list(result.scalars().all())


# Global job store instance
_job_store: Optional[JobStore] = None


def get_job_store() -> JobStore:
    """Get the global job store instance."""
    if _job_store is None:
        raise RuntimeError("JobStore not initialized. Call init_job_store() first.")
    return _job_store


async def init_job_store(database_url: str = None) -> JobStore:
    """
    Initialize the global job store.

    Args:
        database_url: Database connection URL (defaults to DATABASE_URL env var)

    Returns:
        Initialized JobStore instance
    """
    global _job_store

    if _job_store is None:
        _job_store = JobStore(database_url)
        await _job_store.initialize()

    return _job_store
