#!/bin/bash
set -e

# Kill background processes on exit
trap "kill 0" EXIT

echo "📦 Syncing Python dependencies (uv)..."
uv sync

echo "📦 Syncing Frontend dependencies (npm)..."
cd frontend && npm install && cd ..

echo "🧠 Checking Ollama & Models..."
if ! curl -s http://localhost:11434/api/tags > /dev/null; then
    echo "❌ Error: Ollama is not running. Please start the Ollama app first."
    exit 1
fi

echo "  - Pulling gemma4:e2b..."
ollama pull gemma4:e2b
echo "  - Pulling bge-m3..."
ollama pull bge-m3

echo "🗄️ Checking Database & Seeding..."
# Check if Postgres is reachable
if ! nc -z localhost 5432; then
    echo "❌ Error: Postgres is not running on localhost:5432."
    exit 1
fi

echo "  - Running seed_db.py (Schema + Embeddings)..."
uv run python -m scripts.seed_db

echo "🚀 Starting Backend..."
uv run python -m backend.main &

echo "🌐 Starting Frontend..."
cd frontend && npm run dev
