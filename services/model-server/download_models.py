"""Pre-download models into HF_HOME (for image builds with PRELOAD_MODELS=true,
or run once on an internet-connected machine then copy /models to the air-gapped server)."""

import os

from huggingface_hub import snapshot_download

for repo in (os.getenv("EMBED_MODEL", "cl-nagoya/ruri-v3-310m"),
             os.getenv("RERANK_MODEL", "cl-nagoya/ruri-v3-reranker-310m")):
    path = snapshot_download(repo, allow_patterns=["*.json", "*.safetensors", "*.model", "*.txt", "*.py"])
    print(f"downloaded {repo} -> {path}")
