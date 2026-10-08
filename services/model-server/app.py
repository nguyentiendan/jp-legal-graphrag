"""Model server: ruri-v3-310m (embedding) + ruri-v3-reranker-310m (cross-encoder rerank).

POST /v1/embeddings   {"input": [str] | str, "model": "..."}         → OpenAI-compatible
POST /v1/rerank       {"query": str, "documents": [str], "top_n": int} → {"results": [{index, relevance_score}]}
GET  /health

Lưu ý: prefix của Ruri v3 ("検索クエリ: " / "検索文書: ") do client (backend) thêm vào.
On-prem / air-gapped: đặt HF_HUB_OFFLINE=1 và mount sẵn thư mục model vào HF_HOME (/models).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

log = logging.getLogger("model-server")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

EMBED_MODEL = os.getenv("EMBED_MODEL", "cl-nagoya/ruri-v3-310m")
RERANK_MODEL = os.getenv("RERANK_MODEL", "cl-nagoya/ruri-v3-reranker-310m")
DEVICE = os.getenv("MODEL_DEVICE") or ("cuda" if torch.cuda.is_available() else "cpu")
EMBED_BATCH = int(os.getenv("EMBED_BATCH_SIZE", "16"))
RERANK_BATCH = int(os.getenv("RERANK_BATCH_SIZE", "16"))
MAX_SEQ_LEN = int(os.getenv("MAX_SEQ_LENGTH", "2048"))  # Ruri v3 hỗ trợ 8192; giảm để tiết kiệm RAM/VRAM
USE_FP16 = os.getenv("USE_FP16", "auto")
TORCH_THREADS = int(os.getenv("TORCH_THREADS", "0"))

state: dict = {}
_lock = asyncio.Semaphore(int(os.getenv("MAX_CONCURRENCY", "1")))  # tuần tự hoá inference trên 1 GPU/CPU


@asynccontextmanager
async def lifespan(app: FastAPI):
    from sentence_transformers import CrossEncoder, SentenceTransformer

    if TORCH_THREADS > 0:
        torch.set_num_threads(TORCH_THREADS)
    t0 = time.time()
    emb = SentenceTransformer(EMBED_MODEL, device=DEVICE)
    emb.max_seq_length = MAX_SEQ_LEN
    rr = CrossEncoder(RERANK_MODEL, device=DEVICE, max_length=MAX_SEQ_LEN)
    fp16 = (USE_FP16 == "auto" and DEVICE.startswith("cuda")) or USE_FP16 == "1"
    if fp16:
        emb.half()
        rr.model.half()
    state.update(embed=emb, rerank=rr, dim=(getattr(emb, "get_embedding_dimension", None) or emb.get_sentence_embedding_dimension)(), fp16=fp16)
    log.info("loaded %s (dim=%s) + %s on %s fp16=%s in %.1fs", EMBED_MODEL, state["dim"], RERANK_MODEL, DEVICE,
             fp16, time.time() - t0)
    yield
    state.clear()


app = FastAPI(title="ruri-v3 model server", lifespan=lifespan)


class EmbeddingRequest(BaseModel):
    input: list[str] | str
    model: str | None = None


class RerankRequest(BaseModel):
    query: str
    documents: list[str] = Field(..., max_length=256)
    top_n: int | None = None
    model: str | None = None


@app.get("/health")
async def health() -> dict:
    if "embed" not in state:
        raise HTTPException(503, "loading")
    return {"status": "ok", "device": DEVICE, "embed_model": EMBED_MODEL, "rerank_model": RERANK_MODEL,
            "dim": state["dim"], "fp16": state["fp16"], "max_seq_length": MAX_SEQ_LEN}


@app.post("/v1/embeddings")
async def embeddings(req: EmbeddingRequest) -> dict:
    texts = [req.input] if isinstance(req.input, str) else req.input
    if not texts:
        return {"object": "list", "data": [], "model": EMBED_MODEL}
    async with _lock:
        vecs = await asyncio.to_thread(
            state["embed"].encode, texts, batch_size=EMBED_BATCH, normalize_embeddings=True,
            convert_to_numpy=True, show_progress_bar=False,
        )
    return {
        "object": "list",
        "model": EMBED_MODEL,
        "data": [{"object": "embedding", "index": i, "embedding": v.astype("float32").tolist()}
                 for i, v in enumerate(vecs)],
        "usage": {"prompt_tokens": 0, "total_tokens": 0},
    }


@app.post("/v1/rerank")
async def rerank(req: RerankRequest) -> dict:
    if not req.documents:
        return {"model": RERANK_MODEL, "results": []}
    pairs = [(req.query, d) for d in req.documents]
    async with _lock:
        scores = await asyncio.to_thread(state["rerank"].predict, pairs, batch_size=RERANK_BATCH,
                                         show_progress_bar=False, convert_to_numpy=True)
    order = sorted(range(len(scores)), key=lambda i: float(scores[i]), reverse=True)
    top = order[: req.top_n or len(order)]
    return {"model": RERANK_MODEL,
            "results": [{"index": i, "relevance_score": float(scores[i])} for i in top]}
