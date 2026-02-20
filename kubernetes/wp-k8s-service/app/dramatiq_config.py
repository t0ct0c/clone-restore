"""Dramatiq broker configuration"""
import os
import sys
import asyncio
import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware import AsyncIO

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Construct DATABASE_URL from separate env vars
SHARED_RDS_HOST = os.getenv("SHARED_RDS_HOST", "localhost")
SHARED_RDS_PASSWORD = os.getenv("SHARED_RDS_PASSWORD", "")
DATABASE_URL = f"mysql+aiomysql://admin:{SHARED_RDS_PASSWORD}@{SHARED_RDS_HOST}/wordpress"

broker = RedisBroker(url=REDIS_URL)

# Add AsyncIO middleware for async actors
broker.add_middleware(AsyncIO())

dramatiq.set_broker(broker)

# Only initialize JobStore in worker process (not in FastAPI/uvicorn)
if "dramatiq" in sys.argv[0] and SHARED_RDS_HOST and SHARED_RDS_PASSWORD:
    from .job_store import init_job_store
    asyncio.run(init_job_store(DATABASE_URL))
