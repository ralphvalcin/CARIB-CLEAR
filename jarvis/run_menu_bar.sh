#!/bin/bash
# ── JARVIS Menu Bar Launcher ──────────────────────────────────────────────────
# Start the macOS menu bar app for JARVIS status and quick controls.
#
# Usage:
#   ./run_menu_bar.sh              # Normal mode
#   ./run_menu_bar.sh --debug      # Verbose logging
#
# To auto-start on login, add a launchd plist:
#   $HOME/Library/LaunchAgents/com.jarvis.menubar.plist
# ──────────────────────────────────────────────────────────────────────────────

set -e
cd "$(dirname "$0")"

VENV=$(python3 -c "import sys; print(hasattr(sys, 'real_prefix') or sys.base_prefix != sys.prefix)" 2>/dev/null)
if [ "$VENV" = "True" ]; then
    # Already in a venv — use it
    python3 -m jarvis.menu_bar.app "$@"
else
    # Try to find and activate a venv
    for venv_dir in .venv venv .env env; do
        if [ -f "$venv_dir/bin/python3" ] || [ -f "$venv_dir/bin/python" ]; then
            exec "$venv_dir/bin/python3" -m jarvis.menu_bar.app "$@"
        fi
    done
    # Fall back to system python
    exec python3 -m jarvis.menu_bar.app "$@"
fi