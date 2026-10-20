"""Centralized config – read from environment variables / .env file (see .env.example at root)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---- App ----
    app_name: str = "jp-legal-graphrag"
    log_level: str = "INFO"
    data_dir: Path = Path("/data")
    prompts_dir: Path = Path("/app/prompts")
    max_upload_mb: int = 50
    cors_origins: str = ""  # "," separated; leave empty when FE and API share an origin via Nginx

    # ---- PostgreSQL (metadata, jobs, references) ----
    postgres_dsn: str = "postgresql+asyncpg://jplegal:jplegal@postgres:5432/jplegal"

    # ---- Redis (job queue + rate limiter) ----
    redis_url: str = "redis://redis:6379/0"

    # ---- Qdrant ----
    qdrant_url: str = "http://qdrant:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "articles"

    # ---- Neo4j ----
    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "change-me-please"
    neo4j_database: str = "neo4j"

    # ---- Model server (ruri-v3 embedding + reranker) ----
    model_server_url: str = "http://model-server:8080"
    model_server_timeout: float = 300.0
    embed_dim: int = 768
    embed_batch_size: int = 16
    query_prefix: str = "検索クエリ: "
    doc_prefix: str = "検索文書: "

    # ---- LLM (LiteLLM) ----
    # Example on-prem vLLM:  LLM_MODEL=openai/Qwen/Qwen3-32B  LLM_API_BASE=http://vllm:8000/v1
    # Example cloud:         LLM_MODEL=openrouter/deepseek/deepseek-chat  LLM_API_KEY=...
    llm_model: str = ""
    llm_api_base: str | None = None
    llm_api_key: str | None = None
    llm_temperature: float = 0.0
    llm_max_tokens: int = 1500
    llm_timeout: float = 300.0
    # Ollama defaults to a 2048-token context → prompts (6 articles) get cut. 0 = don't send.
    llm_num_ctx: int = 16384

    # ---- e-Gov 法令API ----
    egov_api_base: str = "https://laws.e-gov.go.jp/api/2"
    egov_bulk_url: str = "https://laws.e-gov.go.jp/bulkdownload"
    egov_min_interval_sec: float = 1.0  # self-imposed rate limit: at most 1 request / second (system-wide)
    egov_max_retries: int = 5
    egov_timeout: float = 120.0
    egov_user_agent: str = "jp-legal-graphrag/0.1 (on-prem; contact: admin@example.local)"
    enable_daily_update: bool = False  # cron to update ingested laws (bulk file_section=3)

    # ---- Ingest ----
    include_suppl_provisions: bool = False  # 附則 – skipped in MVP
    max_chunk_chars: int = 2400

    # ---- Retrieval ----
    dense_top_k: int = 20
    seed_k: int = 5  # top dense articles used as seeds for graph expansion
    graph_max: int = 10  # max graph candidates (fed into the rerank pool)
    graph_slots: int = 2  # without rerank: slots reserved for graph-retrieved articles
    fusion_mode: str = "slots"  # "slots" (default) | "rrf"
    delegated_per_law: int = 3
    rrf_k: int = 60
    w_dense: float = 1.0
    w_graph: float = 0.5
    rerank_enabled: bool = True
    rerank_top_n: int = 20
    final_k: int = 6
    rerank_max_chars: int = 3000

    # ---- Sparse / BM25 (Sudachi) ----
    sparse_enabled: bool = True  # BM25 branch; needs a collection with sparse vectors (jplegal reindex-sparse)
    sudachi_dict: str = "core"  # core | full (requires installing sudachidict-full)
    bm25_k1: float = 1.2
    bm25_b: float = 0.75
    bm25_avg_len: float = 100.0  # avg tokens / chunk (measured ≈ 100 on the 労働 corpus); change → reindex-sparse
    hybrid_fusion: str = "dbsf"  # dbsf | rrf  (dense + sparse fusion inside Qdrant; DBSF scores better on the eval set)
    hybrid_w_dense: float = 1.0  # RRF weight (only used when fusion = rrf)
    hybrid_w_sparse: float = 1.0
    hybrid_rrf_k: int = 60

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"


@lru_cache
def get_settings() -> Settings:
    return Settings()
