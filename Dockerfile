# CARIB-CLEAR — Buildathon Demo Container
# python -m carib_clear.demo full  (mock mode, no external dependencies)

FROM python:3.11-slim

WORKDIR /app

# Install system deps for kokoro TTS / soundfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency manifests first (layer caching)
COPY pyproject.toml README.md ./

# Install CARIB-CLEAR + Stellar SDK
RUN pip install --no-cache-dir -e ".[stellar]"

# Copy project source
COPY carib_clear/ carib_clear/
COPY tests/ tests/
COPY scripts/ scripts/
COPY secrets/ secrets/
COPY config/ config/

# PyTest config
COPY pyproject.toml .

# Default: run tests then demo
CMD ["sh", "-c", "python3 -m pytest tests/ -q --ignore=tests/test_openrouter.py --ignore=tests/test_openrouter2.py && echo '---' && python3 -m carib_clear.demo full"]
