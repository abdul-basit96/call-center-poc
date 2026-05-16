# 🏥 Medical Appointment Assistant (Agentic POC)

A premium, receptionist-style agent that manages doctor bookings and availability using **LangGraph**, **MCP**, and **Ollama**. Supports seamless switching between **Arabic** and **English** via text and voice.

---

## 🚀 One-Command Deployment

### Option 1: Docker (Recommended)
The fastest way to run the entire stack (Frontend, Backend, Postgres, and Ollama) with everything automated.

```bash
docker-compose up --build
```
*   **What happens**: Docker pulls the required LLM models (`gemma4:e2b` and `bge-m3`), initializes the database, generates doctor embeddings, and starts the app at [http://localhost](http://localhost).

### Option 2: Local Run (Direct on Mac)
Use this if you want to run the code directly on your machine using your local Postgres and Ollama app.

```bash
./run_local.sh
```
*   **What happens**: This script automatically runs `uv sync`, `npm install`, pulls models via CLI, seeds your local database, and launches both the frontend and backend.

---

## 🌍 Bilingual Features (Arabic & English)
- **Fluid Switching**: Speak or type in Arabic or English at any time. The agent detects the switch instantly and adapts its response language.
- **High-Accuracy STT**: Powered by **Whisper Turbo** with custom tuning for clinical Arabic and English dialects.
- **Bilingual Intent Detection**: Specialized regex and prompting ensure that booking, rescheduling, and doctor lookups work perfectly in both languages.

---

## 🛠️ Technical Architecture
- **Frontend**: React + Vite + Vanilla CSS (Premium Dark Mode & Glassmorphism).
- **Backend**: FastAPI + LangGraph (ReAct-style tool-calling loop).
- **Package Management**: **`uv`** for lightning-fast Python dependency handling and **`npm`** for frontend.
- **Intelligence**: 
    - **LLM**: Ollama (`gemma4:e2b`).
    - **STT**: Faster-Whisper (`turbo` model).
    - **TTS**: Edge-TTS (Neural voices for AR/EN).
- **Database**: PostgreSQL with **pgvector** for semantic doctor search.

---

## 📖 MCP Tools (Dynamic / DB-Backed)
| Tool | Role |
|------|------|
| `list_doctors` | Fetches the full doctor roster from SQL. |
| `search_doctors` | Performs semantic vector search to find doctors by specialty or name. |
| `check_doctor_availability` | Returns 7-day slot capacity and schedule rules for a specific doctor. |
| `book_appointment` | Validates and inserts a new appointment after user confirmation. |
| `reschedule_appointment` | Updates an existing appointment time after user confirmation. |
| `verify_patient` | Looks up a patient and their active appointments by phone number. |

---

## ⚙️ Environment Configuration (`.env`)
The system loads settings from your local `.env`. Key variables:
- `GEMINI_API_KEY`: Required if using Gemini-based tools.
- `OLLAMA_MODEL`: Default is `gemma4:e2b`.
- `WHISPER_MODEL`: Default is `turbo` (pre-loaded in Docker).
- `USE_NATIVE_AUDIO_LLM`: Set to `true` to experiment with Ollama's native multimodal audio (Gemma 4).

---

## 🧪 Development & Testing
If you want to run specific tests for the intent detection or booking logic:
```bash
uv run python -m tests.test_booking_guard  # (Examples)
```
*(Note: Test files matching `test_*.py` are excluded from the Docker build for security).*
