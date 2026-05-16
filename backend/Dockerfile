# Medical appointment assistant — API + MCP + local ML models
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uv/bin/
ENV PATH="/uv/bin:${PATH}"

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# Bake Whisper + embedding weights into the image (copied into the runtime volume on first boot).
ENV HF_HOME=/app/baked_models \
    TRANSFORMERS_CACHE=/app/baked_models \
    SENTENCE_TRANSFORMERS_HOME=/app/baked_models

RUN mkdir -p /app/baked_models \
    && python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')" \
    && python -c "from faster_whisper import WhisperModel; WhisperModel('turbo', device='cpu', compute_type='int8')"

COPY backend/ ./backend/
COPY scripts/ ./scripts/
COPY database/ ./database/

COPY backend/entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
