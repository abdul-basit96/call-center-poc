# Medical Appointment Assistant (Agentic AI)

[![Built with LangGraph](https://img.shields.io/badge/Built%20with-LangGraph-blue)](https://langchain-ai.github.io/langgraph/)
[![Powered by Hugging Face](https://img.shields.io/badge/Powered%20by-Hugging%20Face-yellow)](https://huggingface.co/)

A bilingual (Arabic / English) clinic receptionist that **reasons**, **calls tools**, and **writes to PostgreSQL** only after validation and user confirmation. Voice and text are supported.

---

## Features

- **Agentic workflow** — LangGraph ReAct loop: Gemma 4 decides when to search doctors, check availability, validate, and book.
- **Semantic doctor search** — `BAAI/bge-m3` embeddings + pgvector (1024-dim) for natural-language specialty queries.
- **Bilingual (AR / EN)** — locale detection, translated tool output, Arabic/English UI strings.
- **Voice** — optional native multimodal audio via Gemma (`USE_NATIVE_AUDIO_LLM=true`), or Whisper STT + Edge TTS.
- **Human-in-the-loop** — write tools (`book_appointment`, `reschedule_appointment`) interrupt the graph until the UI confirms.

---

## Quick start

### Prerequisites

| Requirement | Docker | Local dev |
|-------------|--------|-----------|
| **Docker Desktop** 4.x+ | Yes | — |
| **Python 3.12+** + [uv](https://docs.astral.sh/uv/) | — | Yes |
| **Node 20+** | — | Yes (Vite dev server) |
| **PostgreSQL 15+** with [pgvector](https://github.com/pgvector/pgvector) | Included (`db` service) | Run on `localhost:5432` |
| **ffmpeg** | In backend image | `brew install ffmpeg` (for browser WebM audio) |
| **HF account** | Accept [Gemma 4 E2B IT](https://huggingface.co/google/gemma-4-E2B-it), create a [token](https://huggingface.co/settings/tokens) | Same |
| **RAM** | ~16 GB recommended (Gemma on CPU) | Same; MPS/CUDA optional |

### Docker (recommended)

```bash
cp env.docker.template .env
# Edit .env and set HF_TOKEN=hf_...

docker compose up --build
```

| URL | Purpose |
|-----|---------|
| http://localhost | React UI (Nginx → `/api/*` → backend) |
| http://localhost:8000/health | API health + model status |
| `localhost:5432` | Postgres (optional host access) |

**Stop / reset**

```bash
docker compose down          # stop containers
docker compose down -v       # stop + delete DB and HF cache volumes
docker compose logs -f backend
```

**First boot** can take **15–45+ minutes** while Gemma downloads into the `hf_cache` volume. The frontend container starts only after the backend healthcheck reports `"models_preloaded": true`.

### Local development

1. Start Postgres with pgvector and create DB `medical_clinic` (or use the compose `db` service only: `docker compose up db`).
2. Configure `.env`:

```bash
cp env.docker.template .env
# HF_TOKEN=...
# DATABASE_URL=postgresql://postgres:password@localhost:5432/medical_clinic
```

3. Run:

```bash
chmod +x run_local.sh
./run_local.sh
```

- Backend: http://127.0.0.1:8000  
- Frontend (Vite): http://127.0.0.1:5173 (proxies API or set `VITE_API_URL`)

Windows: `.\run_local.ps1`

The script runs `uv sync`, `npm install`, `seed_db`, starts uvicorn, **waits until all models are preloaded**, then starts Vite. Do not use `UVICORN_RELOAD=1` during normal use — it reloads the process and reloads multi‑GB models on every save.

---

## Architecture

```mermaid
flowchart TB
  subgraph client [Browser]
    UI[React + Vite / Nginx]
  end

  subgraph docker [Docker Compose]
    FE[frontend :80]
    BE[backend :8000]
  end

  subgraph be_proc [Backend process]
    API[FastAPI + LangGraph]
    MCPsub[MCP stdio subprocess]
  end

  DB[(Postgres + pgvector)]

  UI -->|"/api/*"| FE
  FE --> BE
  BE --> API
  API <-->|tools| MCPsub
  API --> DB
  MCPsub --> DB
```

### Request flow (chat)

1. **UI** → `POST /api/chat` (or `/api/chat/audio` for voice).
2. **LangGraph** — `prepare_context` → `agent` (Gemma 4 + tool schemas).
3. If the model emits tool calls → **read_tools** or **write_tools** (MCP) → back to `agent`.
4. **Write tools** pause at `interrupt_before` until the user confirms in the UI.
5. Response text is stripped of Gemma control tokens before returning to the client.

### LangGraph nodes

| Node | Role |
|------|------|
| `prepare_context` | Injects server date + booking workflow hints |
| `agent` | Hugging Face Gemma 4 inference (text or native audio) |
| `read_tools` | MCP: search, list, availability, verify, validate |
| `after_read` | Refreshes context after read tools |
| `write_tools` | MCP: book / reschedule (interrupt before run) |

---

## Models and startup preload

All models are loaded **before** the API serves traffic. There is no optional lazy load on first chat.

| Model | Default ID | Process | When loaded |
|-------|------------|---------|-------------|
| **Gemma 4** | `google/gemma-4-E2B-it` | API (uvicorn) | FastAPI lifespan → `preload_all_models()` |
| **Whisper** | `turbo` | API | Same |
| **BGE-M3** | `BAAI/bge-m3` | API + **MCP subprocess** | API at lifespan; MCP at worker start + warm-up `search_doctors` |
| **Edge TTS** | neural voices | API | On demand (network, not a local weight file) |

**Two Python processes matter:**

- **API process** — Gemma, Whisper, embeddings for seeding.
- **MCP process** (`python -m backend.mcp_server.server`) — embeddings for `search_doctors`; must preload on its own (stdio child process).

`/health` returns `503` until `models.embeddings`, `models.whisper`, and `models.gemma` are all `true`.

### Docker image vs runtime cache

- **Image build** bakes Whisper + BGE-M3 under `/app/baked_models`.
- **Entrypoint** copies that into the `hf_cache` volume on first run (so the volume mount does not hide baked weights).
- **Gemma** downloads into `hf_cache` on first boot (gated; needs `HF_TOKEN`).

---

## Docker services

| Service | Image / build | Ports | Depends on |
|---------|---------------|-------|------------|
| `db` | `ankane/pgvector:v0.7.0` | 5432 | — |
| `backend` | `backend/Dockerfile` | 8000 | healthy `db` |
| `frontend` | `frontend/Dockerfile` (Nginx) | 80 | healthy `backend` |

**Backend entrypoint**

1. Seed Hugging Face volume from image (first boot).
2. Wait for Postgres (`scripts/wait_for_db.py`).
3. Run `scripts/seed_db` (schema + doctor embeddings).
4. Start uvicorn → lifespan preloads models → MCP warm-up.

**Frontend** — production build served by Nginx; `/api/` proxied to `backend:8000` with long timeouts for LLM turns.

---

## Technical stack

| Layer | Technology |
|-------|------------|
| Agent orchestration | LangGraph, LangChain, `langchain-mcp-adapters` |
| LLM | Hugging Face `google/gemma-4-E2B-it` (`transformers`, native audio + tools) |
| Embeddings | `sentence-transformers` / `BAAI/bge-m3` |
| STT | `faster-whisper` |
| TTS | `edge-tts` |
| API | FastAPI, uvicorn |
| Tools | MCP (FastMCP) over stdio |
| Database | PostgreSQL, pgvector, psycopg2 |
| UI | React, TypeScript, Vite |
| Python packaging | uv (`pyproject.toml`, `uv.lock`) |

---

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `HF_TOKEN` | **Yes** | — | Hugging Face token for Gemma 4 |
| `DATABASE_URL` | Yes (local) | set by Compose in Docker | Postgres connection string |
| `HF_NATIVE_MODEL_ID` | No | `google/gemma-4-E2B-it` | Multimodal LLM |
| `EMBED_MODEL` | No | `BAAI/bge-m3` | Must match `vector(1024)` in `database/init.sql` |
| `WHISPER_MODEL` | No | `turbo` | Faster-Whisper size |
| `USE_NATIVE_AUDIO_LLM` | No | `true` in Docker | `true` = Gemma audio; `false` = Whisper transcribe + text chat |
| `HF_DEVICE` | No | `cpu` in Docker | `cpu`, `cuda`, or `mps` |
| `WHISPER_DEVICE` | No | `cpu` | Whisper device |
| `VITE_API_URL` | No | `/api` | Frontend API base (Docker uses Nginx proxy) |

If you change `EMBED_MODEL` away from BGE-M3, run `database/migrate_embedding_1024.sql` on existing DBs and re-seed with `FORCE_EMBED_DOCTORS=true`.

---

## Database

- **Init:** `database/init.sql` (tables, sample doctors, `vector(1024)`).
- **Seed:** `uv run python -m scripts.seed_db` (Docker entrypoint runs this automatically).
- **Migrate:** `database/migrate_embedding_1024.sql` for older 384-dim embeddings.

---

## Troubleshooting

| Issue | What to do |
|-------|------------|
| `Set HF_TOKEN in .env` | Copy `env.docker.template` → `.env`, set token, accept Gemma license |
| Frontend never loads | `docker compose logs -f backend` — wait for `All local models preloaded` |
| Port 5432 / 80 in use | Stop conflicting services or change compose ports |
| `Loading local embedding model` during chat | Should not happen after warm-up; rebuild images, ensure latest `agent.py` / MCP preload |
| OOM / killed backend | Use `HF_DEVICE=cpu`, close other apps, or a machine with more RAM |
| Native audio / WebM errors | Install ffmpeg (included in Docker image) |
| Stale Docker DB | `docker compose down -v` and re-up (re-seeds, re-downloads Gemma) |

---

## Project layout

```
├── backend/           # FastAPI, agent, MCP server, ML utils
├── frontend/          # React UI + Nginx config for Docker
├── database/          # init.sql, migrations
├── scripts/           # seed_db, wait_for_db
├── docker-compose.yml
├── env.docker.template
├── run_local.sh       # Local dev (macOS/Linux)
└── run_local.ps1      # Local dev (Windows)
```
