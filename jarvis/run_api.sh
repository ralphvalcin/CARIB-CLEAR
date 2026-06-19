#!/usr/bin/env bash
# Start JARVIS API server
# Usage: ./run_api.sh [port]
set -euo pipefail

PORT="${1:-8000}"
cd "$(dirname "$0")"

mkdir -p data logs
nohup python3 -m uvicorn jarvis.api.app:app \
  --host 0.0.0.0 \
  --port "$PORT" \
  > "logs/api.log" 2>&1 &

PID=$!
echo "JARVIS API starting on port $PORT (PID: $PID)"
echo "Log: $(pwd)/logs/api.log"
echo "Check: curl http://localhost:$PORT/health"