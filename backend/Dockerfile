# Use a slim Python image
FROM python:3.12-slim

# Install system dependencies
# ffmpeg is REQUIRED for Whisper audio processing
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install
# Note: requirements.txt is in the root
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the Whisper model during build
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('turbo', device='cpu', compute_type='int8')"

# Copy the backend and scripts folders
COPY backend/ ./backend/
COPY scripts/ ./scripts/
COPY database/ ./database/

# Copy a startup script (I'll create this next)
COPY backend/entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

# Expose port 8000
EXPOSE 8000

# Use the entrypoint script to run seeding before the server
ENTRYPOINT ["./entrypoint.sh"]
