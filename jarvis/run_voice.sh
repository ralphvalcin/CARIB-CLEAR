#!/bin/bash
# Launch JARVIS Voice with Piper TTS, logging to a timestamped file.
# Usage: ./run_voice.sh [--tail] [--once]

set -euo pipefail

JARVIS_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="${JARVIS_DIR}/logs"
GUARD_FILE="${HOME}/.jarvis_voice_guard"

# ── Guard check ──────────────────────────────────────────────
if [ ! -f "${GUARD_FILE}" ] && [ "${1:-}" != "--force" ]; then
  echo "🔒 Microphone BLOCKED by voice guard"
  echo "   Run: python3 -m jarvis.voice.loop --activate"
  echo "   Or:  ${0} --force"
  exit 1
fi

# Strip --force from args if present
ARGS=()
for arg in "$@"; do
  [ "$arg" = "--force" ] && continue
  ARGS+=("$arg")
done
set -- "${ARGS[@]}"

mkdir -p "${LOG_DIR}"

LOG_FILE="${LOG_DIR}/voice_$(date +%Y%m%d_%H%M%S).log"

cd "${JARVIS_DIR}"

if [ "${1:-}" = "--tail" ]; then
  # Launch in background and follow the log
  echo ""
  echo "┌─────────────────────────────────────────────┐"
  echo "│  🎤 JARVIS MICROPHONE IS NOW ACTIVE         │"
  echo "│  (background mode — PID below)              │"
  echo "└─────────────────────────────────────────────┘"
  echo ""
  PYTHONPATH="${JARVIS_DIR}:${PYTHONPATH:-}" \
    python3 jarvis/voice/loop.py --log-level INFO --tts piper \
    >> "${LOG_FILE}" 2>&1 &
  VOICE_PID=$!
  echo "   🆔 PID: ${VOICE_PID}"
  echo "   📝 Log: ${LOG_FILE}"
  echo "   ❖ Stop:  kill ${VOICE_PID}"
  echo "   ❖ Kill:  python3 -m jarvis.voice.loop --kill"
  echo ""
  echo "   (tail following log below — Ctrl+C to stop following, voice keeps running)"
  tail -f "${LOG_FILE}"
elif [ "${1:-}" = "--once" ]; then
  PYTHONPATH="${JARVIS_DIR}:${PYTHONPATH:-}" \
    timeout 60 python3 jarvis/voice/loop.py --log-level INFO --tts piper --once \
    >> "${LOG_FILE}" 2>&1
  echo "Done. Log: ${LOG_FILE}"
else
  echo ""
  echo "┌─────────────────────────────────────────────┐"
  echo "│  🎤 JARVIS MICROPHONE IS NOW ACTIVE         │"
  echo "│  (background mode — PID below)              │"
  echo "└─────────────────────────────────────────────┘"
  echo ""
  PYTHONPATH="${JARVIS_DIR}:${PYTHONPATH:-}" \
    nohup python3 jarvis/voice/loop.py --log-level INFO --tts piper \
    >> "${LOG_FILE}" 2>&1 &
  VOICE_PID=$!
  echo "   🆔 PID: ${VOICE_PID}"
  echo "   📝 Log: ${LOG_FILE}"
  echo "   ❖ Stop:  kill ${VOICE_PID}"
  echo "   ❖ Kill:  python3 -m jarvis.voice.loop --kill"
  echo "   ❖ Watch: ${0} --tail"
  echo ""
fi