#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────
# CARIB-CLEAR — H200 GPU Launcher (Buildathon One-Command)
# ──────────────────────────────────────────────────────────
# Starts: Ollama → pulls models → runs tests → launches API
#
# Usage:
#   ./scripts/start-h200.sh
#
# Or via Dockerfile.gpu CMD (auto):
#   docker compose -f docker-compose.gpu.yml up
# ──────────────────────────────────────────────────────────

set -euo pipefail

echo "╔═══════════════════════════════════════════════════╗"
echo "║     CARIB-CLEAR — H200 Buildathon Deployment     ║"
echo "╚═══════════════════════════════════════════════════╝"

# ── 1. Verify GPU ───────────────────────────────────────
echo ""
echo "▸ Step 1: Checking GPU..."
if command -v nvidia-smi &>/dev/null; then
    nvidia-smi --query-gpu=name,memory.total,compute_cap --format=csv,noheader
    echo "  ✅ GPU detected"
else
    echo "  ⚠️  nvidia-smi not found — running in CPU fallback mode"
    export USE_GPU=0
fi

# ── 2. Start Ollama ─────────────────────────────────────
echo ""
echo "▸ Step 2: Starting Ollama..."
ollama serve &
OLLAMA_PID=$!
sleep 3

# Wait for Ollama to be ready
for i in $(seq 1 30); do
    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo "  ✅ Ollama ready"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "  ⚠️  Ollama not ready after 30s — continuing anyway"
    fi
    sleep 1
done

# ── 3. Pull models ──────────────────────────────────────
echo ""
echo "▸ Step 3: Pulling models..."

pull_model() {
    local model=$1
    echo "  Pulling $model..."
    if ollama pull "$model" 2>/dev/null; then
        echo "  ✅ $model loaded"
    else
        echo "  ⚠️  Could not pull $model — will use mock/fallback"
    fi
}

pull_model "kreyol:3b"
pull_model "llama3.1:8b"
pull_model "nomic-embed-text"

echo ""
echo "  Models available:"
ollama list

# ── 4. Run tests ────────────────────────────────────────
echo ""
echo "▸ Step 4: Running test suite..."
python3 -m pytest tests/ -q --ignore=tests/test_openrouter.py --ignore=tests/test_openrouter2.py \
    || echo "  ⚠️  Some tests failed — continuing to API launch"

# ── 5. Run demo once (warms up models) ──────────────────
echo ""
echo "▸ Step 5: Warming up demo pipeline..."
python3 -m carib_clear.demo full 2>/dev/null || echo "  ⚠️  Demo warmup had issues"

# ── 6. Launch API ───────────────────────────────────────
echo ""
echo "▸ Step 6: Launching CARIB-CLEAR API..."
echo "  Dashboard: http://localhost:8000/dashboard"
echo "  Swagger:   http://localhost:8000/docs"
echo "  Ollama:    http://localhost:11434"
echo ""

exec uvicorn carib_clear.api:app --host 0.0.0.0 --port 8000 --workers 4
