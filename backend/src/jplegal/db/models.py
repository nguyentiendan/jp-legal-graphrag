"""PostgreSQL – metadata, job, registry luật, bảng dẫn chiếu (nguồn sự thật để dựng lại cạnh graph)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> datetime:
    return datetime.now(UTC)


def _uuid() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    filename: Mapped[str] = mapped_column(String(512))
    source: Mapped[str] = mapped_column(String(32))  # upload | egov | egov_bulk
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    storage_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    law_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|processing|done|failed|skipped
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class IngestJob(Base):
    __tablename__ = "ingest_jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String(32))  # upload | egov_law | egov_bulk | rebuild_links | daily_update
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued|running|succeeded|failed
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0..100
    message: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LawRecord(Base):
    __tablename__ = "laws"
    law_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(512), index=True)
    abbrev: Mapped[str] = mapped_column(String(128), default="")
    law_num: Mapped[str] = mapped_column(String(128), default="")
    law_type: Mapped[str] = mapped_column(String(64), default="")
    category: Mapped[str] = mapped_column(String(64), default="")
    revision_id: Mapped[str] = mapped_column(String(128), default="")
    promulgation_date: Mapped[str] = mapped_column(String(32), default="")
    enforcement_date: Mapped[str] = mapped_column(String(32), default="")
    source: Mapped[str] = mapped_column(String(32), default="egov")
    document_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    num_articles: Mapped[int] = mapped_column(Integer, default=0)
    num_chunks: Mapped[int] = mapped_column(Integer, default=0)
    aliases: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class LegalRef(Base):
    __tablename__ = "legal_refs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    src_uid: Mapped[str] = mapped_column(String(160), index=True)
    src_law_id: Mapped[str] = mapped_column(String(64), index=True)
    relation: Mapped[str] = mapped_column(String(48))
    target_law_name: Mapped[str | None] = mapped_column(String(512), nullable=True)  # None = cùng luật
    target_article_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_law_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    raw_span: Mapped[str] = mapped_column(Text, default="")

    __table_args__ = (Index("ix_legal_refs_target", "target_law_id", "target_article_key"),)
