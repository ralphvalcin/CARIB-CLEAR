#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -f scripts/run_migrations.sh ]; then
  bash scripts/run_migrations.sh
else
  echo "run_migrations.sh not found; skipping"
fi
