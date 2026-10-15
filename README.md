# JP Legal GraphRAG (P0)

GraphRAG cho văn bản pháp luật Nhật Bản: **Dense search (Qdrant) + Graph (Neo4j)**, embedding/rerank bằng **Ruri v3** (`cl-nagoya/ruri-v3-310m`, `cl-nagoya/ruri-v3-reranker-310m`), frontend **Next.js** (static export) chạy trên **Nginx**. Thiết kế cho môi trường **on-prem**: mỗi service có Dockerfile riêng, `docker-compose.yml` gọi các service đó.

Tài liệu kiến trúc: [docs/01-tech-stack-va-kien-truc.md](docs/01-tech-stack-va-kien-truc.md).

## Kiến trúc container

```
                 :8080
  Browser ──► web (Nginx + Next.js static) ──/api──► api (FastAPI)
                                                      │  enqueue (Redis / arq)
                                                      ▼
                                                   worker (ingest)
        ┌─────────────┬──────────────┬────────┴─────┬──────────────┬──────────────┐
        ▼             ▼              ▼              ▼              ▼              ▼
  model-server      ollama         qdrant         neo4j        postgres         redis
 (Ruri v3 embed  (LLM sinh câu   (vector)        (graph)    (metadata, job,  (queue, rate
   + rerank)     trả lời, LiteLLM)                            refs)           limit)
```

| Service | Dockerfile | Cổng nội bộ | Ghi chú |
|---|---|---|---|
| web | `web/Dockerfile` | 80 (mở ra host qua `WEB_PORT`) | Node build `next build` → Nginx; proxy `/api` → `api:8000`, SSE không buffer |
| api | `backend/Dockerfile.api` | 8000 | FastAPI, docs tại `/api/docs` |
| worker | `backend/Dockerfile.worker` | – | arq worker: upload, e-Gov API, bulk XML, rebuild links |
| model-server | `services/model-server/Dockerfile` | 8080 | `/v1/embeddings`, `/v1/rerank`; CPU mặc định, GPU qua override |
| ollama | image `ollama/ollama:0.40.4` | 11434 | LLM sinh câu trả lời; job `ollama-pull` tự tải `OLLAMA_MODEL` lần đầu |
| qdrant | image `qdrant/qdrant:v1.19.2` | 6333 | |
| neo4j | image `neo4j:5.26-community` | 7687 | |
| postgres | image `postgres:17` | 5432 | |
| redis | image `redis:8.2` | 6379 | |

Chỉ `web` mở cổng ra ngoài. Muốn debug (Neo4j Browser, Qdrant dashboard, psql) dùng `docker-compose.dev.yml` – các cổng chỉ bind vào `127.0.0.1`.

## Khởi động

Yêu cầu: Docker Engine 24+ với Compose v2. RAM tối thiểu ~8 GB (model-server CPU ~3 GB, Neo4j 2 GB). GPU: NVIDIA Container Toolkit.

```bash
cp .env.example .env           # đổi POSTGRES_PASSWORD, NEO4J_PASSWORD, cấu hình LLM
docker compose up -d --build   # CPU
# hoặc GPU cho model-server:
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build

docker compose ps              # chờ tất cả healthy (model-server tải model lần đầu ~1–3 phút)
docker compose logs -f ollama-pull   # Ollama tải OLLAMA_MODEL lần đầu (llama3.2 ~2 GB), xong thì job tự thoát
```

Mở `http://<server>:8080`.

Nạp bộ luật mẫu (労働基準法, 施行規則, 労働契約法, …) từ e-Gov 法令API:

```bash
make seed        # = docker compose exec api jplegal ingest-egov --file /app/config/laws.yaml
```

Hoặc dùng màn hình **Nạp dữ liệu**: upload file (XML e-Gov / PDF / DOCX / TXT), nhập `law_id`, hay nạp từ zip XML一括ダウンロード. Theo dõi ở **Tiến trình**.

## Hiệu năng (CPU vs GPU)

Đo trên sandbox 2 vCPU, không GPU: embedding ~250 điều luật mất ~6 phút; truy vấn dense+graph ~0.3–0.5 s; **rerank 20 điều dài mất ~40 s**. Production nên chạy model-server trên GPU (`make up-gpu`). Nếu buộc phải dùng CPU: giảm `RERANK_TOP_N` (vd. 10) và `RERANK_MAX_CHARS` (vd. 800), hoặc tắt rerank trên UI.

## LLM

Câu trả lời được sinh qua LiteLLM nên đổi model chỉ bằng biến môi trường (`LLM_MODEL`, `LLM_API_BASE`, `LLM_API_KEY`). Để trống `LLM_MODEL` thì hệ thống vẫn chạy retrieval và trả về các điều luật căn cứ.

### Mặc định: Ollama trong docker compose

```
OLLAMA_MODEL=llama3.2               # model job ollama-pull sẽ tải
LLM_MODEL=ollama_chat/llama3.2      # "ollama_chat/" + cùng tên
LLM_API_BASE=http://ollama:11434    # tên service, KHÔNG dùng localhost
LLM_NUM_CTX=16384                   # Ollama mặc định chỉ 2048 token → prompt bị cắt
```

- Đổi model: sửa `OLLAMA_MODEL` và `LLM_MODEL` cho khớp, rồi `docker compose up -d` (job `ollama-pull` tự tải model mới). Hoặc tải tay: `make ollama-pull MODEL=qwen2.5:7b`, xem danh sách: `make ollama-list`.
- `llama3.2` (3B) nhẹ nhưng tiếng Nhật pháp lý yếu; nên thử `qwen2.5:7b` / `qwen2.5:14b` nếu đủ RAM/VRAM.
- GPU: `make up-gpu` cấp GPU NVIDIA cho cả model-server và ollama. **Docker Desktop trên macOS không cho container dùng GPU** → trên Mac, Ollama trong Docker chạy CPU và chậm; muốn nhanh thì dùng app Ollama native (xem dưới).
- Ollama chỉ nằm trong network nội bộ, không mở cổng ra ngoài (Ollama không có xác thực). Debug từ host: `make up-dev` → `127.0.0.1:11434`.

### Dùng LLM bên ngoài (vLLM, Ollama native, cloud)

Chạy `make up-no-ollama` để không khởi động service ollama, rồi đổi 3 biến `LLM_*`.

vLLM chạy riêng (cùng máy hoặc máy GPU khác), ví dụ:

```bash
docker run -d --name vllm --gpus all -p 8001:8000 --ipc=host \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  vllm/vllm-openai:latest --model Qwen/Qwen3-32B --reasoning-parser qwen3 --api-key my-secret
```

```
LLM_MODEL=hosted_vllm/Qwen/Qwen3-32B
LLM_API_BASE=http://host.docker.internal:8001/v1   # vLLM cùng máy; máy khác thì dùng IP
LLM_API_KEY=my-secret
```

Ollama native trên host: `LLM_API_BASE=http://host.docker.internal:11434`, và trên Linux cần cho Ollama nghe ngoài loopback (`OLLAMA_HOST=0.0.0.0:11434`).

Sau khi sửa `.env`: `docker compose up -d api worker` (lệnh `restart` không đọc lại `.env`). `/api/status` trả `"llm": {"ok": true}` chỉ nghĩa là đã cấu hình; hỏi thử 1 câu trên UI để kiểm tra kết nối thật.

## Môi trường không có internet (air-gapped)

Trên một máy có internet:

```bash
# 1. Build image, nhúng sẵn model Ruri v3 vào image model-server
PRELOAD_MODELS=true docker compose build
docker compose pull qdrant neo4j postgres redis ollama
make save-images                       # → jplegal-images.tar
make up && make ollama-export          # tải OLLAMA_MODEL rồi đóng gói → ollama_models.tgz

# 2. Dữ liệu luật: tải zip từ https://laws.e-gov.go.jp/bulkdownload/ (XML toàn bộ ~285 MB)
```

Trên server on-prem:

```bash
make load-images
echo "HF_HUB_OFFLINE=1" >> .env
make ollama-import                     # nạp ollama_models.tgz vào volume (trước khi up)
docker compose up -d                   # không cần --build
cp all.zip ./data/import/all.zip       # thư mục này được mount read-only vào api/worker tại /data/import
make bulk ZIP=/data/import/all.zip     # hoặc dùng tab "XML một lần (bulk)" trên UI
```

Nếu dùng registry / PyPI / npm mirror nội bộ, đặt `PYTHON_IMAGE`, `NODE_IMAGE`, `PIP_INDEX_URL`, `TORCH_INDEX_URL`, `NPM_REGISTRY`, … trong `.env`.

## e-Gov: giới hạn truy cập

e-Gov 法令API v2 không cần API key và không công bố rate limit chính thức. Hệ thống tự giới hạn **1 request/giây cho toàn bộ hệ thống** (khoá chung trên Redis, chỉnh bằng `EGOV_MIN_INTERVAL_SEC`), retry có backoff khi gặp 429/5xx. Nạp số lượng lớn nên dùng file zip XML一括ダウンロード thay vì gọi API từng luật.

## Bản quyền dữ liệu

Dữ liệu luật lấy từ e-Gov法令検索 (デジタル庁) theo [公共データ利用規約 (PDL1.0)](https://laws.e-gov.go.jp/terms/). Khi hiển thị cần ghi nguồn, ví dụ: 「出典：e-Gov法令検索（https://laws.e-gov.go.jp/）」. Giao diện đã ghi nguồn ở footer. Câu trả lời của hệ thống không phải tư vấn pháp lý.

## Lệnh hay dùng

| Lệnh | Việc |
|---|---|
| `make up` / `make up-gpu` / `make up-dev` | chạy stack |
| `make up-no-ollama` | chạy stack, không chạy Ollama (dùng LLM ngoài) |
| `make ollama-pull MODEL=...` / `make ollama-list` | tải / xem model Ollama |
| `make logs` | log api, worker, model-server, ollama |
| `make seed` | nạp bộ luật mẫu từ e-Gov |
| `make bulk ZIP=...` | nạp từ zip XML |
| `make eval` | đo Recall@k / MRR@10 / nDCG@10 cho 3 cấu hình (dense, dense+graph, dense+graph+rerank) |
| `docker compose exec api jplegal search "残業代の割増率"` | thử truy xuất từ CLI |
| `docker compose exec api jplegal rebuild-links` | dựng lại cạnh graph sau khi nạp thêm luật |
| `make test` | unit test backend |

## Cấu trúc thư mục

```
backend/                 Python 3.12 (uv) – package jplegal
  Dockerfile.api, Dockerfile.worker
  src/jplegal/
    api/                 FastAPI routes (/api/ingest, /api/jobs, /api/laws, /api/search, /api/ask SSE)
    worker/              arq tasks
    ingest/              parser XML e-Gov / PDF / DOCX, chunker, trích dẫn chiếu, linker
    retrieval/           dense + graph expansion → weighted RRF → rerank → LLM
    stores/              Qdrant, Neo4j
    clients/             e-Gov API (rate limit), model-server, LiteLLM
    db/                  SQLAlchemy models (PostgreSQL)
  config/laws.yaml       danh sách luật mẫu
  eval/queries.jsonl     bộ câu hỏi đánh giá
  prompts/answer_ja.txt  prompt sinh câu trả lời
  tests/
services/model-server/   FastAPI + sentence-transformers (Ruri v3)
web/                     Next.js 16 (static export) + Tailwind v4, Nginx config
docker-compose.yml       stack chính
docker-compose.gpu.yml   override GPU
docker-compose.dev.yml   override mở cổng debug
```

## Phát triển cục bộ (không Docker)

```bash
cd backend && uv sync --group dev && uv run pytest -q
# chạy hạ tầng bằng: docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d qdrant neo4j postgres redis model-server
uv run uvicorn jplegal.api.main:app --reload --port 8000
uv run arq jplegal.worker.tasks.WorkerSettings

cd web && npm ci && NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run dev
```

Khi chạy `npm run dev` với API ở origin khác, đặt `CORS_ORIGINS=http://localhost:3000` cho api.
