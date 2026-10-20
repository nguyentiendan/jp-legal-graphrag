"""arq worker – runs ingest in the background.

Start:  arq jplegal.worker.tasks.WorkerSettings
"""

from __future__ import annotations

import logging
import traceback
from datetime import date, timedelta
from pathlib import Path

from arq import cron
from sqlalchemy import select

from jplegal.core.config import get_settings
from jplegal.core.container import Container
from jplegal.db.models import Document, IngestJob, LawRecord
from jplegal.ingest.linker import rebuild_links
from jplegal.ingest.parsers.egov_xml import parse_egov_xml
from jplegal.ingest.pipeline import ingest_parsed_law, parse_file
from jplegal.ingest.sources.egov_bulk import iter_xml, list_entries
from jplegal.worker.jobs import QUEUE_NAME, now, redis_settings, set_job

log = logging.getLogger(__name__)


async def startup(ctx: dict) -> None:
    ctx["c"] = await Container.create()


async def shutdown(ctx: dict) -> None:
    await ctx["c"].close()


async def _run(ctx: dict, job_id: str, fn) -> dict:
    c: Container = ctx["c"]
    await set_job(c, job_id, status="running", started_at=now(), progress=0, message="Bắt đầu")

    async def progress(pct: int, msg: str) -> None:
        await set_job(c, job_id, progress=max(0, min(100, pct)), message=msg)

    try:
        async with c.db.session() as s:
            job = await s.get(IngestJob, job_id)
        result = await fn(c, job, progress)
        await set_job(c, job_id, status="succeeded", progress=100, finished_at=now(), result=result,
                      message="Hoàn tất")
        return result
    except Exception as e:
        log.exception("job %s failed", job_id)
        await set_job(c, job_id, status="failed", finished_at=now(), error=f"{e}\n{traceback.format_exc()[-2000:]}",
                      message=str(e)[:500])
        raise


# ---------------------------------------------------------------- tasks
async def task_ingest_upload(ctx: dict, job_id: str) -> dict:
    async def fn(c: Container, job: IngestJob, progress):
        async with c.db.session() as s:
            doc = await s.get(Document, job.document_id)
            doc.status = "processing"
            await s.commit()
        try:
            await progress(2, f"Parse {doc.filename}")
            parsed = parse_file(Path(doc.storage_path), document_id=doc.id,
                                include_suppl=c.settings.include_suppl_provisions,
                                max_chars=c.settings.max_chunk_chars)
            if job.params.get("title"):
                parsed.meta.title = job.params["title"]
            result = await ingest_parsed_law(c, parsed, progress)
            async with c.db.session() as s:
                doc = await s.get(Document, job.document_id)
                doc.status, doc.law_id, doc.stats = "done", parsed.meta.law_id, result
                await s.commit()
            return result
        except Exception as e:
            async with c.db.session() as s:
                doc = await s.get(Document, job.document_id)
                doc.status, doc.error = "failed", str(e)[:2000]
                await s.commit()
            raise

    return await _run(ctx, job_id, fn)


async def task_ingest_egov(ctx: dict, job_id: str) -> dict:
    """params: {law_ids: [...]} – 1 API request per law (rate-limited)."""

    async def fn(c: Container, job: IngestJob, progress):
        law_ids: list[str] = job.params.get("law_ids", [])
        done, failed = [], []
        for i, lid in enumerate(law_ids):
            base = int(100 * i / max(1, len(law_ids)))
            span = max(1, int(100 / max(1, len(law_ids))))

            async def sub(p: int, m: str, _b=base, _s=span, _lid=lid):
                await progress(_b + int(_s * p / 100), f"[{_lid}] {m}")

            try:
                await sub(1, "Tải từ e-Gov 法令API")
                law = await c.egov.get_law(lid, cache_dir=c.settings.raw_dir)
                parsed = parse_egov_xml(law.xml, law.meta, include_suppl=c.settings.include_suppl_provisions)
                done.append(await ingest_parsed_law(c, parsed, sub))
            except Exception as e:
                log.exception("ingest %s failed", lid)
                failed.append({"law_id": lid, "error": str(e)[:300]})
        if failed and not done:
            raise RuntimeError(f"Tất cả đều lỗi: {failed}")
        return {"done": done, "failed": failed}

    return await _run(ctx, job_id, fn)


async def task_ingest_bulk(ctx: dict, job_id: str) -> dict:
    """params: {zip_path? | category_cd? | update_date?, law_ids?: [...], title_contains?: str, max_laws?: int}"""

    async def fn(c: Container, job: IngestJob, progress):
        p = job.params
        zip_path = Path(p["zip_path"]) if p.get("zip_path") else None
        if zip_path is None:
            name = f"bulk_{p.get('category_cd', 'all')}_{p.get('update_date', date.today().isoformat())}.zip"
            zip_path = c.settings.raw_dir / "bulk" / name
            if not zip_path.exists():
                await progress(1, "Tải XML一括ダウンロード")
                await c.egov.download_bulk(zip_path, category_cd=p.get("category_cd"),
                                           update_date=p.get("update_date"))
        law_ids = set(p.get("law_ids") or []) or None
        entries = list_entries(zip_path, law_ids)
        if p.get("title_contains"):
            entries = [e for e in entries if p["title_contains"] in e.title]
        if p.get("only_registered"):
            async with c.db.session() as s:
                reg = set((await s.execute(select(LawRecord.law_id))).scalars())
            entries = [e for e in entries if e.law_id in reg]
        entries = entries[: int(p.get("max_laws") or 200)]
        done, failed = [], []
        for i, (e, xml) in enumerate(iter_xml(zip_path, entries)):
            await progress(5 + int(85 * i / max(1, len(entries))), f"[{i + 1}/{len(entries)}] {e.title or e.law_id}")
            try:
                parsed = parse_egov_xml(xml, law_id=e.law_id, revision_id=e.revision_id,
                                        include_suppl=c.settings.include_suppl_provisions)
                done.append(await ingest_parsed_law(c, parsed, link=False))
            except Exception as ex:
                log.exception("bulk ingest %s failed", e.law_id)
                failed.append({"law_id": e.law_id, "error": str(ex)[:300]})
        await progress(92, "Liên kết graph")
        links = await rebuild_links(c, None)
        return {"done": len(done), "failed": failed, "links": links}

    return await _run(ctx, job_id, fn)


async def task_rebuild_links(ctx: dict, job_id: str) -> dict:
    async def fn(c: Container, job: IngestJob, progress):
        await progress(10, "Resolve dẫn chiếu")
        return await rebuild_links(c, None)

    return await _run(ctx, job_id, fn)


async def cron_daily_update(ctx: dict) -> None:
    """Daily: download bulk 'laws updated yesterday', only re-ingest laws already in the system."""
    c: Container = ctx["c"]
    if not c.settings.enable_daily_update:
        return
    from jplegal.worker.jobs import create_job

    yday = (date.today() - timedelta(days=1)).strftime("%Y%m%d")
    job = await create_job(c, "daily_update", {"update_date": yday, "only_registered": True, "max_laws": 1000})
    await task_ingest_bulk(ctx, job.id)


s = get_settings()


class WorkerSettings:
    functions = [task_ingest_upload, task_ingest_egov, task_ingest_bulk, task_rebuild_links]
    cron_jobs = [cron(cron_daily_update, hour={18}, minute={30})]  # 18:30 UTC = 03:30 JST
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = redis_settings(s.redis_url)
    queue_name = QUEUE_NAME
    max_jobs = 2
    job_timeout = 6 * 3600
    keep_result = 24 * 3600
