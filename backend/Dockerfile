# Static ffmpeg avoids apt pulling libllvm/libz3 (often OOM / exit 137 on Docker Desktop).
FROM mwader/static-ffmpeg:7.1.1 AS ffmpeg

FROM python:3.12-slim

COPY --from=ffmpeg /ffmpeg /usr/local/bin/ffmpeg
COPY --from=ffmpeg /ffprobe /usr/local/bin/ffprobe

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && ffmpeg -version

# Install uv from the official binary
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uv/bin/
ENV PATH="/uv/bin:${PATH}"

WORKDIR /app

# Copy project configuration files
# Note: These are in the root context
COPY pyproject.toml uv.lock ./

# Install dependencies using uv
# --frozen ensures we use the exact versions from uv.lock
RUN uv sync --frozen --no-dev

# Set the path to use the newly created virtual environment
ENV PATH="/app/.venv/bin:$PATH"

# Pre-download the Whisper model during build
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('turbo', device='cpu', compute_type='int8')"

# Copy the backend and scripts folders
COPY backend/ ./backend/
COPY scripts/ ./scripts/
COPY database/ ./database/

# Copy startup script
COPY backend/entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

# Expose port 8000
EXPOSE 8000

# Use the entrypoint script
ENTRYPOINT ["./entrypoint.sh"]
