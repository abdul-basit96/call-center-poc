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

## How to run the app

Pick **one** path below. All paths need a Hugging Face token and accepted [Gemma 4 license](https://huggingface.co/google/gemma-4-E2B-it).

| | **Docker** | **Local (Mac / Linux)** | **Local (Windows)** |
|---|------------|-------------------------|---------------------|
| **Command** | `docker compose up --build` | `./run_local.sh` | `.\run_local.ps1` |
| **Launcher script** | — | `run_local.sh` | `run_local.ps1` |
| **UI URL** | http://localhost | http://127.0.0.1:5173 | http://127.0.0.1:5173 |
| **API URL** | http://localhost:8000 | http://127.0.0.1:8000 | http://127.0.0.1:8000 |
| **Postgres** | Included (`db` service) | You provide (see below) | Same |
| **Best for** | Production-like demo, no local Python | Day-to-day dev on Mac/Linux | Day-to-day dev on Windows |

### One-time setup (all paths)

```bash
cp env.docker.template .env
```

Edit `.env` and set **`HF_TOKEN`**. For **local** scripts, also set:

```bash
DATABASE_URL=postgresql://postgres:password@localhost:5432/medical_clinic
```

(Use the same credentials as your Postgres instance, or the defaults from `docker compose up db`.)

---

## Docker — single command

From the project root:

```bash
docker compose up --build
```

- Starts **Postgres**, **backend** (seed + model preload), then **frontend** (Nginx).
- Open **http://localhost** when the backend healthcheck passes (`models_preloaded: true`).
- Logs: `docker compose logs -f backend`

**Stop / reset**

```bash
docker compose down          # stop containers
docker compose down -v       # stop + wipe DB and Hugging Face cache
```

**First boot** may take **15–45+ minutes** while Gemma downloads into the `hf_cache` volume.

---

## Local development — single command

Run the app on your machine with hot-reload frontend (Vite). The backend and frontend are started for you by a launcher script.

### Prerequisites (local only)

| Requirement | Notes |
|-------------|--------|
| [uv](https://docs.astral.sh/uv/) | Python 3.12+ and dependency sync |
| [Node.js](https://nodejs.org/) 20+ | Vite dev server |
| **PostgreSQL + pgvector** | Easiest: `docker compose up db` in a **second** terminal and leave it running |
| **ffmpeg** | Voice / WebM decoding — macOS: `brew install ffmpeg`; Windows: `winget install ffmpeg` |
| **~16 GB RAM** | Recommended for Gemma on CPU; Apple Silicon can set `HF_DEVICE=mps` in `.env` |

### macOS and Linux — `run_local.sh`

In **Terminal**, from the project root:

```bash
chmod +x run_local.sh    # first time only
./run_local.sh
```

### Windows — `run_local.ps1`

In **PowerShell** (not Command Prompt), from the project root:

```powershell
.\run_local.ps1
```

If PowerShell blocks the script:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.\run_local.ps1
```

### What `run_local.sh` and `run_local.ps1` do

Both scripts run the **same steps**; only the shell differs.

| Step | What happens |
|------|----------------|
| 1 | `uv sync` — Python dependencies |
| 2 | `npm install` (in `frontend/`) |
| 3 | `uv run python -m scripts.seed_db` — schema + doctor embeddings |
| 4 | Start **backend** — `uvicorn backend.main:app` on port **8000** |
| 5 | Wait for http://127.0.0.1:8000/health with **`models_preloaded: true`** |
| 6 | Start **frontend** — `npm run dev` (Vite) on port **5173** |

**While using the app**

- Keep the terminal open.
- Wait for: `✅ Backend is ready (all models preloaded).` then open http://127.0.0.1:5173
- Press **`Ctrl+C`** once to stop frontend and backend (`run_local.ps1` also stops the backend process).

**First run**

- Downloads Gemma and other weights (several GB); often **15–45+ minutes** on CPU.
- Optional longer wait: macOS/Linux `export BACKEND_HEALTH_TIMEOUT_SEC=1800` — Windows `$env:BACKEND_HEALTH_TIMEOUT_SEC=1800`

**Backend hot-reload (developers only)**

- macOS/Linux: `UVICORN_RELOAD=1 ./run_local.sh`
- Windows: `$env:UVICORN_RELOAD=1; .\run_local.ps1`
- Reloads the full model stack on every `.py` save — avoid for normal chatting.

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
| `VITE_API_URL` | No | `/api` (Docker) · direct to `:8000` (local Vite) | Frontend API base; local dev usually needs no change |
| `BACKEND_HEALTH_TIMEOUT_SEC` | No | `900` | Max seconds `run_local.*` waits for model preload |
| `UVICORN_RELOAD` | No | off | Set to `1` only when editing backend Python (reloads all models) |

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
| **Docker:** frontend never loads | `docker compose logs -f backend` — wait for `All local models preloaded` |
| **Local:** backend timeout | Increase `BACKEND_HEALTH_TIMEOUT_SEC`; check `HF_TOKEN` and disk space for downloads |
| **Local:** Postgres errors | Start DB: `docker compose up db`; confirm `DATABASE_URL` in `.env` |
| **Local:** `run_local.ps1` blocked | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` (PowerShell) |
| **Local:** port 8000 in use | Stop old uvicorn or other service on 8000 |
| Port 5432 / 80 in use (Docker) | Stop conflicting services or change compose ports |
| `Loading local embedding model` during chat | Should not happen after startup; pull latest code and restart |
| OOM / killed backend | Use `HF_DEVICE=cpu`, close other apps, or more RAM |
| Native audio / WebM errors | Install **ffmpeg** (in Docker image; required locally) |
| Stale Docker DB | `docker compose down -v` and re-up |

---

## Project layout

```
├── backend/              # FastAPI, agent, MCP server, ML utils
├── frontend/             # React UI + Nginx config (Docker)
├── database/             # init.sql, migrations
├── scripts/              # seed_db, wait_for_db
├── docker-compose.yml    # Docker: db + backend + frontend
├── env.docker.template   # Copy to .env (HF_TOKEN, DATABASE_URL, …)
├── run_local.sh          # Single-command local run (macOS / Linux)
└── run_local.ps1         # Single-command local run (Windows PowerShell)
```
