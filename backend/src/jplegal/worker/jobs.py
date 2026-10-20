"""Manage ingest jobs (PostgreSQL) + enqueue into arq (Redis)."""

from __future__ import annotations

from datetime import UTC, datetime

from arq import ArqRedis, create_pool
from arq.connections import RedisSettings
from sqlalchemy import update

from jplegal.db.models import IngestJob

QUEUE_NAME = "jplegal:ingest"


def redis_settings(url: str) -> RedisSettings:
    return RedisSettings.from_dsn(url)


async def get_pool(url: str) -> ArqRedis:
    return await create_pool(redis_settings(url), default_queue_name=QUEUE_NAME)


async def create_job(c, kind: str, params: dict, document_id: str | None = None) -> IngestJob:
    async with c.db.session() as s:
        job = IngestJob(kind=kind, params=params, document_id=document_id, status="queued", message="Đang chờ")
        s.add(job)
        await s.commit()
        await s.refresh(job)
        return job


async def enqueue(pool: ArqRedis, task: str, job_id: str) -> None:
    await pool.enqueue_job(task, job_id, _job_id=f"{task}:{job_id}", _queue_name=QUEUE_NAME)


async def set_job(c, job_id: str, **values) -> None:
    async with c.db.session() as s:
        await s.execute(update(IngestJob).where(IngestJob.id == job_id).values(**values))
        await s.commit()


def now() -> datetime:
    return datetime.now(UTC)
