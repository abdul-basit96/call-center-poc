# Agentic Appointment Booking System POC

Receptionist-style chat that **chooses tools** and reads **live data from PostgreSQL** (doctors, schedules, bookings). The LLM drives the dialogue; the database and MCP tools are the source of truth — not hardcoded replies in the API.

## Architecture
- **Frontend:** React + Vite + Tailwind CSS (`frontend/`).
- **Backend:** FastAPI + LangGraph (ReAct-style loop: model → tools → model).
- **Tools:** MCP server (`backend/mcp_server/server.py`) exposing DB operations: roster, semantic search, availability, book, reschedule.
- **LLM:** Ollama (default **`gemma4:e2b`**; override with `OLLAMA_MODEL`).

## MCP tools (dynamic / DB-backed)
| Tool | Role |
|------|------|
| `list_doctors` | Full roster from SQL (`specialty_filter` optional). Use for “all doctors”, “who do you have”, directory browsing. |
| `search_doctors` | pgvector semantic search (top matches + schedule summary per row). |
| `check_doctor_availability` | One doctor: openings, booked sample, slot rules. |
| `book_appointment` | Inserts patient + appointment after **UI confirm** and validation. |
| `reschedule_appointment` | Updates appointment time after confirm. |

The FastAPI layer **does not** inject canned scheduling text into user messages; the agent must call tools to obtain facts.

## Prerequisites
1. **Ollama** — [ollama.com](https://ollama.com/)
   ```bash
   ollama pull gemma4:e2b
   ```
   Other tags work; set `OLLAMA_MODEL` in `.env` (e.g. `llama3.1:8b`, `qwen2.5:7b`).
2. **PostgreSQL** with **pgvector**.
3. **uv** — [astral-sh/uv](https://github.com/astral-sh/uv)

## Environment (`.env`)
- `DATABASE_URL` — PostgreSQL connection string.
- `OLLAMA_BASE_URL` — default `http://localhost:11434`.
- `OLLAMA_MODEL` — chat model tag (default in code: `gemma4:e2b`).
- `OLLAMA_TEMPERATURE` — default `0.25`.
- `EMBED_MODEL` — embedding model for semantic search (e.g. `bge-m3`).
- `USE_NATIVE_AUDIO_LLM` — if `true`, voice uses **`POST /chat/audio`** (no Whisper). Mic audio bytes are base64-encoded into the **`images`** message field (**Gemma 4 + Ollama** routes native audio through that slot). See [ollama#15427](https://github.com/ollama/ollama/issues/15427). The browser sends **WebM/Opus**; Ollama may require **WAV-style** payloads to treat the blob as speech (this app does **not** transcode — use Whisper + `/chat` if recognition fails).
- `OLLAMA_NATIVE_AUDIO_USER_CONTENT` — text paired with the clip (what you want the model to do with the recording).
- `OLLAMA_NATIVE_AUDIO_STYLE` — **`images`** (default, Gemma 4), or **`string`** / **`array`** / **`both`** for other experiments.
- `OLLAMA_NATIVE_AUDIO_FIELD` — scalar key for `string` / `both` (default **`audio`**).
- `OLLAMA_NATIVE_AUDIO_ARRAY_FIELD` — list key for `array` / `both` (default **`audios`**).
- `OLLAMA_NATIVE_AUDIO_TIMEOUT_SEC` — HTTP timeout for native-audio Ollama calls (default **`600`**).

## Setup
```bash
uv sync
uv run scripts/seed_db.py
```

## Run
**Two terminals** (the API starts the MCP subprocess itself):

```bash
uv run python -m backend.main
```

```bash
cd frontend && npm install && npm run dev
```

Open http://localhost:5173 — the dev server proxies `/api` to the backend on port 8000.

Optional: `frontend/.env` with `VITE_API_URL=http://localhost:8000` if not using the proxy.

## Features
- **Live roster** (`list_doctors`) and **semantic search** (`search_doctors`) with clinic hours and 7-day slot capacity on each row.
- **Availability** per doctor via `check_doctor_availability`.
- **Human-in-the-loop booking:** recap → Confirm in UI → `book_appointment` writes to DB.
- **Validation** rejects placeholder patient/contact before confirm.
- **Voice mode (AR/EN):** toggle **🎤 Voice** / **⌨️ Text** anytime. Hands-free mic (auto listen on speech, auto speak replies) with animated assistant overlay; chat scrolls behind a soft blur. Whisper STT + Edge TTS.

### Speech environment (optional)
- `WHISPER_MODEL` — default `base` (use `small` for better accuracy, slower load).
- `WHISPER_DEVICE` / `WHISPER_COMPUTE_TYPE` — CPU defaults (`int8`).
- `TTS_VOICE_EN` — default `en-US-JennyNeural`.
- `TTS_VOICE_AR` — default `ar-SA-ZariyahNeural`.

Speech API: `POST /speech/transcribe` (multipart audio), `POST /speech/synthesize` (JSON `{text, locale}` → MP3).

> **Deployment (later):** plan for Dockerfile + `docker-compose.yml` so the full stack runs with one command; not included in this POC iteration.
