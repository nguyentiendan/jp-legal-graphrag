"""Tải trước model vào HF_HOME (dùng khi build image với PRELOAD_MODELS=true,
hoặc chạy 1 lần trên máy có internet rồi copy thư mục /models sang server air-gapped)."""

import os

from huggingface_hub import snapshot_download

for repo in (os.getenv("EMBED_MODEL", "cl-nagoya/ruri-v3-310m"),
             os.getenv("RERANK_MODEL", "cl-nagoya/ruri-v3-reranker-310m")):
    path = snapshot_download(repo, allow_patterns=["*.json", "*.safetensors", "*.model", "*.txt", "*.py"])
    print(f"downloaded {repo} -> {path}")
