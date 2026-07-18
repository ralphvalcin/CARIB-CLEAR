#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON=python3
if [ -f "$HOME/.carib-clear/venv/bin/python" ]; then
  PYTHON="$HOME/.carib-clear/venv/bin/python"
fi
"$PYTHON" -m carib_clear.migrations.apply
