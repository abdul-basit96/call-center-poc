#!/bin/bash
set -euo pipefail

export HF_HOME=/cache/huggingface
export TRANSFORMERS_CACHE=/cache/huggingface
export SENTENCE_TRANSFORMERS_HOME=/cache/huggingface

mkdir -p /cache/huggingface
if [ ! -f /cache/huggingface/.volume_initialized ]; then
  if [ -d /app/baked_models ] && [ -n "$(ls -A /app/baked_models 2>/dev/null)" ]; then
    echo "==> Initializing Hugging Face cache volume from image…"
    cp -a /app/baked_models/. /cache/huggingface/
  fi
  touch /cache/huggingface/.volume_initialized
fi

echo "==> Waiting for Postgres…"
python -m scripts.wait_for_db

echo "==> Seeding database (schema + doctor embeddings)…"
python -m scripts.seed_db

echo "==> Starting API (all models preload before accepting traffic)…"
exec uvicorn backend.main:app --host 0.0.0.0 --port 8000
