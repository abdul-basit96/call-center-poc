# 🏥 Medical Appointment Assistant (Agentic AI)

[![Built with LangGraph](https://img.shields.io/badge/Built%20with-LangGraph-blue)](https://langchain-ai.github.io/langgraph/)
[![Powered by Ollama](https://img.shields.io/badge/Powered%20by-Ollama-orange)](https://ollama.com/)

A premium, state-of-the-art agentic workflow designed for clinical appointment management. This system doesn't just "chat"—it **thinks**, **verifies**, and **acts** by orchestrating between a local LLM and a PostgreSQL database.

---

## ✨ Key Features

*   **🤖 Truly Agentic**: Uses a ReAct-style loop where the agent autonomously chooses tools based on user intent.
*   **🌍 Bilingual Mastery (AR/EN)**: 
    *   Seamlessly switch between Arabic and English via voice or text.
    *   **Whisper Turbo** integration for 100% accurate clinical transcription.
    *   Bilingual intent detection for booking, rescheduling, and doctor searches.
*   **🎤 Immersive Voice Mode**: High-performance "hands-free" interaction with real-time audio visualization and neural TTS.
*   **🔍 Semantic Doctor Search**: Uses **pgvector** to find the right doctor based on specialty descriptions, not just keywords.
*   **🛡️ Human-in-the-Loop**: Strict validation and UI-based confirmation before any database writes occur.

---

## 🏗️ How It Works

1.  **Input**: User speaks or types (e.g., "أريد موعد مع دكتور قلب").
2.  **Detection**: The backend detects the language and "Workflow Stage."
3.  **The Loop**: 
    *   Agent calls `search_doctors` to find Cardiologists.
    *   Agent calls `check_doctor_availability` for the best match.
4.  **Confirmation**: The UI displays a "Confirmation Panel" for the user to approve.
5.  **Action**: Upon approval, the `book_appointment` tool persists the record to PostgreSQL.

---

## 🚀 Deployment Options

### 🐳 Option 1: Docker (DB + app in Docker, Ollama on host)
Ollama runs **on your machine** (better GPU/Metal on Mac, simpler on Windows with NVIDIA). Docker runs Postgres, backend, and frontend.

1. Install and start [Ollama](https://ollama.com/), then pull models:
   ```bash
   ollama pull gemma4:e2b
   ollama pull bge-m3
   ```
2. Start the stack:
   ```bash
   docker compose up --build
   ```
*   Backend reaches host Ollama at `http://host.docker.internal:11434`.
*   **URL**: [http://localhost](http://localhost)

### 🍎 Option 2: Mac/Linux Local
Direct execution on your host machine.
```bash
./run_local.sh
```

### 🪟 Option 3: Windows (single command, native — no Docker)
Same idea as `./run_local.sh` on Mac: Ollama, Postgres, backend, and frontend all run on the machine.

**Prerequisites:**

| Tool | Auto via script? | Notes |
|------|------------------|--------|
| **uv**, **Node/npm**, **Ollama**, **ffmpeg** | `.\run_local.ps1 -InstallMissing` installs all four via **winget** | May need a **new terminal** after winget installs |
| **PostgreSQL + pgvector** | **No** — manual setup | Must match `DATABASE_URL` in your `.env` |
| **Ollama app running** | — | Open Ollama from Start menu before / after install |

**Run** (open **PowerShell** in the project folder):
```powershell
.\run_local.ps1
```
First time without tools installed:
```powershell
.\run_local.ps1 -InstallMissing
```
Then open a **new** PowerShell window and run `.\run_local.ps1` again if winget just installed tools.

The script checks tools, runs `uv sync` / `npm install`, pulls missing Ollama models, seeds the DB, starts API **:8000** and UI **http://localhost:5173**. Press **Ctrl+C** to stop.

### 💻 Local development — frontend & backend separately

Use two terminals when you want separate logs for the API and the UI.  
**Do not skip the setup steps** — `npm run dev` alone is not enough if dependencies or the database were never installed.

All commands below are run from the **project root** unless noted. On Windows, use **PowerShell**.

---

#### A. Requirements (install once per machine)

| Requirement | Purpose |
|-------------|---------|
| [Ollama](https://ollama.com/) | LLM (`gemma4:e2b`) + embeddings (`bge-m3`) |
| PostgreSQL + [pgvector](https://github.com/pgvector/pgvector) | App database (must match `.env`) |
| [uv](https://docs.astral.sh/uv/) | Python dependencies |
| [Node.js 20+](https://nodejs.org/) (includes **npm**) | Frontend build & dev server |
| **ffmpeg** on PATH | Voice / speech-to-text (e.g. `winget install --id Gyan.FFmpeg` on Windows) |
| **`.env`** in project root | Connection strings and model names (see `.env.example`) |

---

#### B. One-time project setup (do in order)

**1. Clone the repo and open a terminal in the project folder.**

**2. Configure environment**

Ensure `.env` exists and `DATABASE_URL` points at your local Postgres, for example:

`postgresql://postgres:password@localhost:5432/medical_clinic`

**3. Install Python dependencies (backend)**

```bash
uv sync
```

**4. Install frontend dependencies**

```bash
cd frontend
npm install
cd ..
```

You must run `npm install` before the first `npm run dev`. Re-run it after `package.json` changes.

**5. Start Ollama and pull models**

Open the Ollama app, then:

```bash
ollama pull gemma4:e2b
ollama pull bge-m3
```

**6. Seed the database (schema + doctor embeddings)**

Postgres must be running on port `5432` first.

```bash
uv run python -m scripts.seed_db
```

Re-run seeding if you reset the database or change embedding logic.

---

#### C. Start the app (every time you develop)

**Terminal 1 — Backend (port 8000)**

```bash
# project root
uv run python -m backend.main
```

Wait until it is listening, then verify: [http://localhost:8000/health](http://localhost:8000/health) should return `"status":"ok"`.

**Terminal 2 — Frontend (port 5173)**

```bash
cd frontend
npm run dev
```

Open the UI: [http://localhost:5173](http://localhost:5173)  
(Vite proxies `/api/*` → `http://localhost:8000`; see `frontend/vite.config.ts`.)

**Stop:** `Ctrl+C` in each terminal (backend first or both).

---

#### D. Quick reference

| Service | URL | Start command |
|---------|-----|----------------|
| **Frontend (UI)** | http://localhost:5173 | `cd frontend` → `npm run dev` |
| **Backend (API)** | http://localhost:8000 | `uv run python -m backend.main` |
| **Health check** | http://localhost:8000/health | (backend must be running) |

| Common mistake | Fix |
|----------------|-----|
| UI loads but chat fails | Start **backend** first; check Ollama is running |
| `npm run dev` errors | Run `npm install` inside `frontend/` |
| Import / module errors | Run `uv sync` at project root |
| DB errors | Check Postgres + run `uv run python -m scripts.seed_db` |
| Voice not working | Install **ffmpeg** on the system |

**Shortcut:** `./run_local.sh` (Mac/Linux) or `.\run_local.ps1` (Windows) runs steps **B.3–B.6** (if needed) and **C** in one script.

---

## 🏗️ Technical Implementation & Architecture

### 1. Agentic Intelligence (LangGraph)
The heart of the system is a **LangGraph** state machine. Unlike a standard chatbot, this agent operates in a **ReAct (Reason + Act)** loop:
*   **State Management**: Tracks the conversation history, detected locale, and pending tool calls.
*   **Nodes & Edges**: The graph consists of a `call_model` node and a `tool_node`. If the model decides a tool is needed (e.g., to check a schedule), it transitions to the tool node and then loops back to the model with the "facts."

### 2. Semantic Persistence (PostgreSQL + pgvector)
We use **Vector Embeddings** to bridge the gap between human queries and database records:
*   **Doctor Search**: Every doctor's specialty is converted into a 1024-dimensional vector using the `bge-m3` model.
*   **Similarity Matching**: When a user asks for a "heart specialist," the agent vectorizes the query and performs a cosine similarity search in SQL to find the best match (e.g., "Cardiologist").

### 3. Bilingual Audio Pipeline
*   **STT (Speech-to-Text)**: Uses **Faster-Whisper (Turbo)**. We implemented a "Soft Language Hint" system that provides context to the model for better accuracy while allowing it to auto-detect if the user switches languages mid-sentence.
*   **VAD (Voice Activity Detection)**: Custom-tuned silence thresholds ensure that slower-paced Arabic speech isn't clipped.
*   **TTS (Text-to-Speech)**: Uses **Microsoft Edge TTS** neural voices for high-quality, human-like speech in both Arabic (`ar-SA-ZariyahNeural`) and English (`en-US-JennyNeural`).

### 4. Containerization & Orchestration
*   **Multi-Stage Docker**: The frontend is built and served via Nginx, while the backend is optimized using **Astral `uv`**, reducing image size and build times.
*   **Internal Routing**: An Nginx reverse proxy routes all `/api` traffic to the backend, creating a unified single-port experience on port 80.

---

## 🛠️ Technical Stack

*   **Orchestration**: LangGraph (State management) + FastAPI.
*   **Intelligence**: Ollama (`gemma4:e2b`) + Faster-Whisper (`turbo`).
*   **Database**: PostgreSQL + `pgvector`.
*   **Tooling**: **`uv`** (Python package manager) + **`npm`**.
*   **UI/UX**: React + Vite + Vanilla CSS (Glassmorphism design).

---

## ⚙️ Environment Overrides (`.env`)

| Variable | Description |
|----------|-------------|
| `OLLAMA_MODEL` | LLM to use (default: `gemma4:e2b`). |
| `WHISPER_MODEL` | STT model (default: `turbo`). |
| `DATABASE_URL` | Postgres connection string. |
| `USE_NATIVE_AUDIO_LLM` | Toggle native multimodal audio support. |

---

## 🔧 Troubleshooting

*   **Docker DB Connection**: Ensure no other service is using port `5432` on your host.
*   **Ollama Connectivity (Docker)**: Start the Ollama app on the host and pull `gemma4:e2b` + `bge-m3`. Backend uses `OLLAMA_BASE_URL=http://host.docker.internal:11434`. On Linux, `extra_hosts: host-gateway` in compose is required (already set).
*   **First-Time Startup**: Backend image pre-downloads Whisper; host Ollama must already have the LLM/embed models pulled.
*   **Docker build `exit code 137` / `Killed` during `apt-get` or Whisper step**: Docker ran out of RAM. In Docker Desktop → **Settings → Resources**, set memory to **8 GB+** (16 GB recommended), then `docker compose build --no-cache backend`. The backend Dockerfile uses a static `ffmpeg` binary to avoid heavy apt packages (LLVM) that often trigger this on Windows.
