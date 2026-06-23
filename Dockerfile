FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for audio processing (Kokoro/faster-whisper)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Copy pyproject.toml first for layer caching
COPY pyproject.toml README.md ./

# Install core dependencies
RUN pip install --no-cache-dir -e . && \
    pip install --no-cache-dir fastapi uvicorn

# Copy application code
COPY carib_clear/ carib_clear/
COPY config/ config/
COPY tests/ tests/

# Create non-root user
RUN useradd -m -u 1000 carib && chown -R carib:carib /app
USER carib

# Expose API port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health').read()" || exit 1

# Run FastAPI server by default
CMD ["python3", "-m", "carib_clear.api"]