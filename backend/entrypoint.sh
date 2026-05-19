#!/bin/bash
set -e

echo "Waiting for Postgres to be ready..."
until curl -s http://db:5432 || [ $? -eq 52 ]; do
  # Note: Postgres doesn't respond to HTTP but we can check the port
  # A better way is using a python check
  sleep 2
done

echo "Waiting for Ollama at ${OLLAMA_BASE_URL} (start Ollama on the host if needed)..."
until curl -sf "${OLLAMA_BASE_URL}/api/tags" > /dev/null; do
  sleep 2
done

echo "Waiting for bge-m3 on host Ollama (run: ollama pull bge-m3)..."
until curl -sf "${OLLAMA_BASE_URL}/api/tags" | grep -q "bge-m3"; do
  sleep 5
done

echo "Running Database Seed & Embedding Generation..."
# Using -m scripts.seed_db ensures it's run as a package
python -m scripts.seed_db

echo "Starting FastAPI Server..."
python -m backend.main
