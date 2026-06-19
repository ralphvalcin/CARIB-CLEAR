#!/bin/bash
# Stop JARVIS Voice Loop
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PID_FILE="$PROJECT_DIR/logs/voice.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "⚠️  No JARVIS voice PID file found at $PID_FILE"
    echo "   Try: pgrep -f 'voice.loop' | xargs kill"
    exit 1
fi

OLD_PID=$(cat "$PID_FILE")
if kill -0 "$OLD_PID" 2>/dev/null; then
    echo "🛑 Stopping JARVIS voice (PID $OLD_PID)..."
    kill "$OLD_PID" 2>/dev/null
    sleep 1
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "   Force stopping..."
        kill -9 "$OLD_PID" 2>/dev/null || true
    fi
    echo "✅ Stopped"
else
    echo "ℹ️  JARVIS voice (PID $OLD_PID) is not running"
fi
rm -f "$PID_FILE"
