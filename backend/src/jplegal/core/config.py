"""Cấu hình tập trung – đọc từ biến môi trường / file .env (xem .env.example ở root)."""

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
    cors_origins: str = ""  # "," separated; để trống khi FE và API cùng origin qua Nginx

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
    # Ví dụ on-prem vLLM:  LLM_MODEL=openai/Qwen/Qwen3-32B  LLM_API_BASE=http://vllm:8000/v1
    # Ví dụ cloud:         LLM_MODEL=openrouter/deepseek/deepseek-chat  LLM_API_KEY=...
    llm_model: str = ""
    llm_api_base: str | None = None
    llm_api_key: str | None = None
    llm_temperature: float = 0.0
    llm_max_tokens: int = 1500
    llm_timeout: float = 300.0
    # Ollama mặc định chỉ dùng context 2048 token → prompt (6 điều luật) bị cắt. 0 = không gửi.
    llm_num_ctx: int = 16384

    # ---- e-Gov 法令API ----
    egov_api_base: str = "https://laws.e-gov.go.jp/api/2"
    egov_bulk_url: str = "https://laws.e-gov.go.jp/bulkdownload"
    egov_min_interval_sec: float = 1.0  # tự áp rate limit: tối đa 1 request / giây (toàn hệ thống)
    egov_max_retries: int = 5
    egov_timeout: float = 120.0
    egov_user_agent: str = "jp-legal-graphrag/0.1 (on-prem; contact: admin@example.local)"
    enable_daily_update: bool = False  # cron cập nhật luật đã ingest (bulk file_section=3)

    # ---- Ingest ----
    include_suppl_provisions: bool = False  # 附則 – MVP bỏ qua
    max_chunk_chars: int = 2400

    # ---- Retrieval ----
    dense_top_k: int = 20
    seed_k: int = 5  # số điều dense đứng đầu dùng làm seed để mở rộng graph
    graph_max: int = 10  # số ứng viên graph tối đa (đưa vào pool rerank)
    graph_slots: int = 2  # khi không rerank: số vị trí dành cho điều lấy từ graph
    fusion_mode: str = "slots"  # "slots" (mặc định) | "rrf"
    delegated_per_law: int = 3
    rrf_k: int = 60
    w_dense: float = 1.0
    w_graph: float = 0.5
    rerank_enabled: bool = True
    rerank_top_n: int = 20
    final_k: int = 6
    rerank_max_chars: int = 3000

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"


@lru_cache
def get_settings() -> Settings:
    return Settings()
