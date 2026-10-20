from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from jplegal.db.models import Document
from jplegal.ingest.pipeline import find_duplicate, sha256_bytes
from jplegal.worker.jobs import create_job, enqueue

router = APIRouter(prefix="/ingest", tags=["ingest"])

ALLOWED = {".xml", ".pdf", ".docx", ".txt", ".md"}
_LAW_ID_RE = re.compile(r"^[0-9A-Z_]{15,64}$")


def _safe_name(name: str) -> str:
    name = Path(name).name
    return re.sub(r"[^\w.\-ぁ-んァ-ヶ一-龥ー]", "_", name)[:200] or "upload"


@router.post("/upload")
async def upload(request: Request, file: UploadFile = File(...), title: str | None = Form(None),
                 force: bool = Form(False)) -> dict:
    c = request.app.state.c
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED:
        raise HTTPException(400, f"Định dạng không hỗ trợ: {suffix}. Cho phép: {sorted(ALLOWED)}")
    data = await file.read()
    if len(data) > c.settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File vượt quá {c.settings.max_upload_mb}MB")
    if not data:
        raise HTTPException(400, "File rỗng")
    digest = sha256_bytes(data)
    if not force and (dup := await find_duplicate(c, digest)):
        return {"duplicate": True, "document_id": dup.id, "law_id": dup.law_id, "job_id": None}

    async with c.db.session() as s:
        doc = Document(filename=_safe_name(file.filename or "upload"), source="upload", content_hash=digest)
        s.add(doc)
        await s.flush()
        dest = c.settings.upload_dir / doc.id / doc.filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        doc.storage_path = str(dest)
        await s.commit()
    job = await create_job(c, "upload", {"filename": doc.filename, "title": title}, document_id=doc.id)
    await enqueue(request.app.state.pool, "task_ingest_upload", job.id)
    return {"duplicate": False, "document_id": doc.id, "job_id": job.id}


class EgovRequest(BaseModel):
    law_ids: list[str] = Field(default_factory=list, description="law_id / law_num / law_revision_id", max_length=50)
    titles: list[str] = Field(default_factory=list, description="Exact law name, e.g. 労働基準法", max_length=50)


@router.post("/egov")
async def ingest_egov(request: Request, body: EgovRequest) -> dict:
    c = request.app.state.c
    law_ids = [x.strip() for x in body.law_ids if x.strip()]
    unresolved = []
    for t in body.titles:  # resolve name → law_id (also goes through the rate limiter)
        hits = await c.egov.search_laws(t.strip(), limit=10)
        exact = [h for h in hits if h.get("revision_info", {}).get("law_title") == t.strip()]
        if exact:
            law_ids.append(exact[0]["law_info"]["law_id"])
        else:
            unresolved.append(t)
    law_ids = list(dict.fromkeys(law_ids))
    if not law_ids:
        raise HTTPException(400, f"Không xác định được luật nào. Không tìm thấy: {unresolved}")
    job = await create_job(c, "egov_law", {"law_ids": law_ids})
    await enqueue(request.app.state.pool, "task_ingest_egov", job.id)
    return {"job_id": job.id, "law_ids": law_ids, "unresolved_titles": unresolved}


class BulkRequest(BaseModel):
    zip_path: str | None = Field(None, description="Path of a zip already placed in DATA_DIR (air-gapped environments)")
    category_cd: int | None = None
    update_date: str | None = Field(None, pattern=r"^\d{8}$")
    law_ids: list[str] = Field(default_factory=list)
    title_contains: str | None = None
    max_laws: int = Field(200, ge=1, le=10000)


@router.post("/bulk")
async def ingest_bulk(request: Request, body: BulkRequest) -> dict:
    c = request.app.state.c
    if body.zip_path:
        p = Path(body.zip_path).resolve()
        if not str(p).startswith(str(c.settings.data_dir.resolve())) or not p.exists():
            raise HTTPException(400, "zip_path phải nằm trong DATA_DIR và tồn tại")
    job = await create_job(c, "egov_bulk", body.model_dump())
    await enqueue(request.app.state.pool, "task_ingest_bulk", job.id)
    return {"job_id": job.id}


@router.post("/rebuild-links")
async def rebuild(request: Request) -> dict:
    c = request.app.state.c
    job = await create_job(c, "rebuild_links", {})
    await enqueue(request.app.state.pool, "task_rebuild_links", job.id)
    return {"job_id": job.id}
