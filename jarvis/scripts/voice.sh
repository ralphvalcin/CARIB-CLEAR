#!/bin/bash
# JARVIS Voice Loop — launch with live log output
# Usage: ./scripts/voice.sh [--once] [--tts piper|say|none] [--log-level DEBUG|INFO]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$PROJECT_DIR/logs"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
LOG_FILE="$LOG_DIR/voice-$TIMESTAMP.log"
PID_FILE="$LOG_DIR/voice.pid"

mkdir -p "$LOG_DIR"

# Parse extra args (pass everything after script name to loop.py)
EXTRA_ARGS=("$@")

cd "$PROJECT_DIR"

echo "═══════════════════════════════════════════"
echo "  JARVIS Voice Assistant — Logged Launch"
echo "═══════════════════════════════════════════"
echo "  Log file: $LOG_FILE"
echo "  TTS:      ${EXTRA_ARGS[*]:-} (default: piper)"
echo ""
echo "  To view live output:  tail -f $LOG_FILE"
echo "  To stop JARVIS:       bash scripts/voice-stop.sh"
echo ""

if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "⚠️  JARVIS voice is already running (PID $OLD_PID)"
        echo "   Kill it first: bash scripts/voice-stop.sh"
        exit 1
    fi
    rm -f "$PID_FILE"
fi

nohup env PYTHONPATH="$PROJECT_DIR" python3 -u "$PROJECT_DIR/jarvis/voice/loop.py" \
    "${EXTRA_ARGS[@]}" \
    > "$LOG_FILE" 2>&1 &

VOICE_PID=$!
echo "$VOICE_PID" > "$PID_FILE"

echo "✅ JARVIS voice started (PID $VOICE_PID)"

# Wait for log file to appear and accumulate some content
sleep 3

if [ ! -f "$LOG_FILE" ]; then
    echo "⚠️  Log file not created yet — starting tail anyway..."
fi

echo "📝 Tailing log..."
echo "   (press Ctrl+C to stop tailing — JARVIS keeps running)"
echo ""
tail -f "$LOG_FILE"
