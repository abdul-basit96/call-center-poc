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

### 🐳 Option 1: Docker (Single-Command)
Perfect for a zero-configuration experience.
```bash
docker-compose up --build
```
*   **Fully Automated**: Pulls models, builds the `uv`-optimized backend, seeds the DB with embeddings, and starts the Nginx proxy.
*   **URL**: [http://localhost](http://localhost)

### 🍎 Option 2: Mac/Linux Local
Direct execution on your host machine.
```bash
./run_local.sh
```

### 🪟 Option 3: Windows Local (PowerShell)
Native experience for Windows developers.
```powershell
.\run_local.ps1
```

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
*   **Ollama Connectivity**: If Ollama is not found in Docker, ensure your `docker-compose.yml` has `OLLAMA_BASE_URL=http://ollama:11434`.
*   **First-Time Startup**: The first run will take a few minutes as it downloads the ~1.5GB Whisper model and LLM weights.
