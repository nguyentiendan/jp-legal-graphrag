"""Gom các client dùng chung (API process và worker process mỗi bên giữ 1 instance)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from redis.asyncio import Redis

from jplegal.clients.egov import EgovClient
from jplegal.clients.llm import LLMClient
from jplegal.clients.model_server import ModelServerClient
from jplegal.core.config import Settings, get_settings
from jplegal.db.session import Database
from jplegal.stores.neo4j_store import Neo4jStore
from jplegal.stores.qdrant_store import QdrantStore


@dataclass
class Container:
    settings: Settings
    db: Database
    redis: Redis
    qdrant: QdrantStore
    neo4j: Neo4jStore
    models: ModelServerClient
    llm: LLMClient
    egov: EgovClient

    @classmethod
    async def create(cls, settings: Settings | None = None, *, init_schema: bool = True) -> Container:
        s = settings or get_settings()
        logging.basicConfig(level=s.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        redis = Redis.from_url(s.redis_url)
        c = cls(
            settings=s,
            db=Database(s.postgres_dsn),
            redis=redis,
            qdrant=QdrantStore(s.qdrant_url, s.qdrant_collection, s.embed_dim, s.qdrant_api_key),
            neo4j=Neo4jStore(s.neo4j_uri, s.neo4j_user, s.neo4j_password, s.neo4j_database),
            models=ModelServerClient(s),
            llm=LLMClient(s),
            egov=EgovClient(s, redis),
        )
        if init_schema:
            await c.db.create_all()
            await c.qdrant.ensure_collection()
            await c.neo4j.ensure_schema()
        s.raw_dir.mkdir(parents=True, exist_ok=True)
        s.upload_dir.mkdir(parents=True, exist_ok=True)
        return c

    async def close(self) -> None:
        await self.egov.close()
        await self.models.close()
        await self.qdrant.close()
        await self.neo4j.close()
        await self.db.dispose()
        await self.redis.aclose()
