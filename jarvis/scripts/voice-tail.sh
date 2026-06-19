#!/bin/bash
# Tail the last JARVIS voice log
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$(cd "$SCRIPT_DIR/.." && pwd)/logs"

LATEST=$(ls -t "$LOG_DIR"/voice-*.log 2>/dev/null | head -1)

if [ -z "$LATEST" ]; then
    echo "⚠️  No voice logs found in $LOG_DIR"
    echo "   Start JARVIS first: scripts/voice.sh"
    exit 1
fi

echo "📝 Tailing: $LATEST"
echo "   (Ctrl+C to stop)"
tail -f "$LATEST"
