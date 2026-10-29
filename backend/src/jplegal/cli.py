"""CLI – run inside the api container:   docker compose exec api jplegal <command>

    jplegal init                                   # create Postgres / Qdrant / Neo4j schema
    jplegal ingest-egov --law-id 322AC0000000049   # enqueue job (processed by worker)
    jplegal ingest-egov --file config/laws.yaml
    jplegal ingest-bulk --zip /data/raw/bulk/all.zip --law-id 322AC0000000049
    jplegal ingest-file /data/inbox/通達.pdf
    jplegal rebuild-links
    jplegal search "残業代の割増率は？"
    jplegal eval --queries /app/eval/queries.jsonl
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import typer
import yaml

app = typer.Typer(add_completion=False, help="JP Legal GraphRAG CLI")


def _run(coro):
    return asyncio.run(coro)


async def _container():
    from jplegal.core.container import Container

    return await Container.create()


@app.command()
def init() -> None:
    """Create PostgreSQL tables, Qdrant collection, Neo4j constraints."""

    async def main():
        c = await _container()
        await c.close()
        typer.echo("OK – スキーマを準備しました")

    _run(main())


def _load_laws_file(path: Path) -> list[str]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [x["law_id"] if isinstance(x, dict) else str(x) for x in data.get("laws", [])]


@app.command("ingest-egov")
def ingest_egov(law_id: list[str] = typer.Option(None, "--law-id"),
                file: Path | None = typer.Option(None, "--file", help="YAML: laws: [{law_id, title}]")) -> None:
    """Enqueue ingest from the e-Gov 法令API (rate-limited, 1 req/s)."""
    ids = list(law_id or [])
    if file:
        ids += _load_laws_file(file)
    if not ids:
        raise typer.BadParameter("--law-id または --file が必要です")

    async def main():
        from jplegal.worker.jobs import create_job, enqueue, get_pool

        c = await _container()
        pool = await get_pool(c.settings.redis_url)
        job = await create_job(c, "egov_law", {"law_ids": list(dict.fromkeys(ids))})
        await enqueue(pool, "task_ingest_egov", job.id)
        typer.echo(f"job_id={job.id}（{len(ids)}法令）")
        await pool.aclose()
        await c.close()

    _run(main())


@app.command("ingest-bulk")
def ingest_bulk(zip: Path | None = typer.Option(None, help="existing XML一括ダウンロード zip"),
                category_cd: int | None = typer.Option(None), law_id: list[str] = typer.Option(None, "--law-id"),
                title_contains: str | None = typer.Option(None), max_laws: int = 200) -> None:
    async def main():
        from jplegal.worker.jobs import create_job, enqueue, get_pool

        c = await _container()
        params = {"zip_path": str(zip) if zip else None, "category_cd": category_cd, "law_ids": law_id or [],
                  "title_contains": title_contains, "max_laws": max_laws}
        pool = await get_pool(c.settings.redis_url)
        job = await create_job(c, "egov_bulk", params)
        await enqueue(pool, "task_ingest_bulk", job.id)
        typer.echo(f"job_id={job.id}")
        await pool.aclose()
        await c.close()

    _run(main())


@app.command("ingest-file")
def ingest_file(path: Path, title: str | None = None) -> None:
    """Ingest 1 local file (XML / PDF / DOCX / TXT) via the job queue."""

    async def main():
        from jplegal.db.models import Document
        from jplegal.ingest.pipeline import sha256_bytes
        from jplegal.worker.jobs import create_job, enqueue, get_pool

        c = await _container()
        data = path.read_bytes()
        async with c.db.session() as s:
            doc = Document(filename=path.name, source="upload", content_hash=sha256_bytes(data))
            s.add(doc)
            await s.flush()
            dest = c.settings.upload_dir / doc.id / path.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest)
            doc.storage_path = str(dest)
            await s.commit()
        pool = await get_pool(c.settings.redis_url)
        job = await create_job(c, "upload", {"filename": path.name, "title": title}, document_id=doc.id)
        await enqueue(pool, "task_ingest_upload", job.id)
        typer.echo(f"job_id={job.id}")
        await pool.aclose()
        await c.close()

    _run(main())


@app.command("rebuild-links")
def rebuild_links_cmd() -> None:
    async def main():
        from jplegal.ingest.linker import rebuild_links

        c = await _container()
        typer.echo(json.dumps(await rebuild_links(c, None), ensure_ascii=False))
        await c.close()

    _run(main())


@app.command("reindex-sparse")
def reindex_sparse_cmd() -> None:
    """(Re)compute BM25 sparse vectors for every chunk in Qdrant – no need to re-download laws or re-embed.

    Collections created by P0 (without sparse vectors) are auto-migrated to the new schema.
    Re-run when SUDACHI_DICT / BM25_K1 / BM25_B / BM25_AVG_LEN change.
    """

    async def main():
        c = await _container()

        async def progress(pct: int, msg: str) -> None:
            typer.echo(f"[{pct:>3}%] {msg}")

        typer.echo(json.dumps(await c.qdrant.reindex_sparse(c.sparse_doc, progress=progress), ensure_ascii=False))
        await c.close()

    _run(main())


@app.command()
def search(query: str, no_graph: bool = False, no_rerank: bool = False, k: int = 6,
           stage: str = typer.Option(None, help="dense | sparse | hybrid (default follows SPARSE_ENABLED)")) -> None:
    async def main():
        from jplegal.retrieval.pipeline import RetrievalOptions, Retriever

        c = await _container()
        res = await Retriever(c).retrieve(query, RetrievalOptions(use_graph=not no_graph, use_rerank=not no_rerank,
                                                                  final_k=k, first_stage=stage))
        for i, it in enumerate(res.items, 1):
            typer.echo(f"{i:>2}. {it.citation}{it.caption}  src={'+'.join(it.sources)} "
                       f"dense#{it.dense_rank} bm25#{it.sparse_rank} rerank={it.rerank_score}")
        typer.echo(f"first_stage={res.first_stage} timings: {res.timings_ms}")
        await c.close()

    _run(main())


@app.command("eval")
def eval_cmd(queries: Path = typer.Option(Path("/app/eval/queries.jsonl")), out: Path | None = None,
             configs: str | None = typer.Option(None, help="config list, comma-separated"),
             no_rerank: bool = typer.Option(False, "--no-rerank", help="skip configs with rerank (faster on CPU)"),
             summary: bool = typer.Option(False, "--summary", help="print summary table only")) -> None:
    """Compare retrieval configs (Recall@1/5/10, MRR@10, nDCG@10, All@10)."""
    from jplegal.retrieval.evaluate import CONFIGS, run_eval

    names = [x.strip() for x in configs.split(",")] if configs else list(CONFIGS)
    if no_rerank:
        names = [n for n in names if "rerank" not in n]

    async def main():
        c = await _container()
        report = await run_eval(c, queries, names)
        await c.close()
        text = json.dumps(report, ensure_ascii=False, indent=2)
        if out:
            out.write_text(text, encoding="utf-8")
        if not summary:
            typer.echo(text)
            return
        metrics = ["recall@1", "recall@5", "recall@10", "mrr@10", "ndcg@10", "all@10"]
        typer.echo(f"{queries.name}（{report['n_queries']}問）")
        typer.echo(f"{'config':28s}" + "".join(f"{m:>10s}" for m in metrics))
        for name, m in report["configs"].items():
            typer.echo(f"{name:28s}" + "".join(f"{m[k]:>10.3f}" for k in metrics))

    _run(main())


if __name__ == "__main__":
    app()
