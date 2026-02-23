"""Dramatiq broker configuration"""

import os
import sys
import asyncio
import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware import AsyncIO


def get_broker():
    """Get Redis broker with URL from environment"""
    REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    broker = RedisBroker(url=REDIS_URL)
    broker.add_middleware(AsyncIO())
    return broker


# Set broker immediately
broker = get_broker()
dramatiq.set_broker(broker)

# Use Redis for job store (not DATABASE_URL which is MySQL)
REDIS_URL = os.environ.get(
    "REDIS_URL", "redis://redis-master.wordpress-staging.svc.cluster.local:6379/0"
)

# Only initialize JobStore in worker process (not in FastAPI/uvicorn)
if "dramatiq" in sys.argv[0]:
    from .job_store import init_job_store

    asyncio.run(init_job_store(REDIS_URL))
