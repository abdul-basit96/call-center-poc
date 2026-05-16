#!/bin/bash
set -e

# Kill background processes on exit
trap "kill 0" EXIT

echo "📦 Syncing Python dependencies (uv)..."
uv sync

echo "📦 Syncing Frontend dependencies (npm)..."
cd frontend && npm install && cd ..

echo "🐘 Checking Database (Postgres)..."
# Just a quick check if pg_isready is available
if command -v pg_isready >/dev/null 2>&1; then
    pg_isready -h localhost -p 5432 || echo "⚠️ Warning: Postgres might not be running on localhost:5432"
fi

echo "🌱 Initializing Database & Seed Data..."
uv run python -m scripts.seed_db

wait_for_backend() {
  local url="http://127.0.0.1:8000/health"
  local max_wait="${BACKEND_HEALTH_TIMEOUT_SEC:-900}"
  echo "⏳ Waiting for backend at $url (up to ${max_wait}s; models preload at startup)..."
  local elapsed=0
  while [ "$elapsed" -lt "$max_wait" ]; do
    if curl -sf "$url" 2>/dev/null | grep -q '"models_preloaded":true'; then
      echo "✅ Backend is ready (all models preloaded)."
      return 0
    fi
    sleep 2
    elapsed=$((elapsed + 2))
    if [ $((elapsed % 30)) -eq 0 ]; then
      echo "   still waiting (${elapsed}s)..."
    fi
  done
  echo "❌ Backend did not respond on port 8000 within ${max_wait}s."
  return 1
}

echo "🚀 Starting backend (frontend starts after /health is up)..."
# --reload restarts the process on every .py save and reloads Gemma into RAM each time.
# Use UVICORN_RELOAD=1 only while editing backend code.
UVICORN_ARGS="--port 8000"
if [ "${UVICORN_RELOAD:-}" = "1" ]; then
  UVICORN_ARGS="$UVICORN_ARGS --reload"
  echo "   (uvicorn --reload enabled; saving backend files will reload the LLM)"
else
  echo "   Models preload at startup; keep this terminal open between chats."
fi
uv run uvicorn backend.main:app $UVICORN_ARGS &
BACKEND_PID=$!

wait_for_backend

echo "🚀 Starting frontend..."
cd frontend && npm run dev
