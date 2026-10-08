from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select

from jplegal.db.models import Document, IngestJob

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _job(j: IngestJob, doc: Document | None = None) -> dict:
    return {
        "id": j.id, "kind": j.kind, "status": j.status, "progress": j.progress, "message": j.message,
        "error": j.error, "params": j.params, "result": j.result, "document_id": j.document_id,
        "filename": doc.filename if doc else None,
        "created_at": j.created_at, "started_at": j.started_at, "finished_at": j.finished_at,
    }


@router.get("")
async def list_jobs(request: Request, limit: int = Query(50, le=200), status: str | None = None) -> list[dict]:
    c = request.app.state.c
    async with c.db.session() as s:
        q = select(IngestJob, Document).outerjoin(Document, Document.id == IngestJob.document_id)
        if status:
            q = q.where(IngestJob.status == status)
        rows = (await s.execute(q.order_by(IngestJob.created_at.desc()).limit(limit))).all()
    return [_job(j, d) for j, d in rows]


@router.get("/{job_id}")
async def get_job(request: Request, job_id: str) -> dict:
    c = request.app.state.c
    async with c.db.session() as s:
        j = await s.get(IngestJob, job_id)
        if not j:
            raise HTTPException(404, "job not found")
        d = await s.get(Document, j.document_id) if j.document_id else None
    return _job(j, d)
