#!/bin/bash
# ── JARVIS Telegram Bot Launcher ──────────────────────────────────────────────
# Requires JARVIS_TELEGRAM_BOT_TOKEN in ~/JARVIS/.env.
#
# Usage:
#   ./run_telegram.sh              # Start bot (real or mock depending on token)
#   ./run_telegram.sh --mock       # Force mock mode (console input)
#   ./run_telegram.sh --debug      # Verbose logging
# ──────────────────────────────────────────────────────────────────────────────

set -e
cd "$(dirname "$0")"

# Source .env if it exists
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

exec python3 -m jarvis.notifications.telegram_bot "$@"