# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# Model server: Ruri v3 embedding + reranker (cl-nagoya/ruri-v3-310m, ruri-v3-reranker-310m)
#   CPU (mặc định):  docker build services/model-server
#   GPU (CUDA 12.8): docker build --build-arg TORCH_INDEX_URL=https://download.pytorch.org/whl/cu128 services/model-server
#   Air-gapped:      --build-arg PRELOAD_MODELS=true để nhúng model vào image,
#                    hoặc chép thư mục HF cache vào volume "models" (xem README).
# ---------------------------------------------------------------------------
ARG PYTHON_IMAGE=python:3.12-slim-bookworm
FROM ${PYTHON_IMAGE}

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
ARG TORCH_VERSION=
ARG PRELOAD_MODELS=false
ARG EMBED_MODEL=cl-nagoya/ruri-v3-310m
ARG RERANK_MODEL=cl-nagoya/ruri-v3-reranker-310m

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    HF_HOME=/models \
    EMBED_MODEL=${EMBED_MODEL} \
    RERANK_MODEL=${RERANK_MODEL} \
    TZ=Asia/Tokyo

RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --home /app app \
    && mkdir -p /models /app && chown -R app:app /models /app
WORKDIR /app

# torch cài riêng từ index CPU/CUDA để không kéo nhầm bản CUDA khổng lồ khi chạy CPU
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --index-url ${TORCH_INDEX_URL} "torch${TORCH_VERSION:+==${TORCH_VERSION}}"
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

COPY --chown=app:app app.py download_models.py ./
USER app
RUN if [ "${PRELOAD_MODELS}" = "true" ]; then python download_models.py; fi

EXPOSE 8080
VOLUME ["/models"]
HEALTHCHECK --interval=20s --timeout=5s --start-period=180s --retries=40 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4).status==200 else 1)"
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
