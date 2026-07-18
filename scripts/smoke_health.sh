#!/usr/bin/env bash
set -euo pipefail

# Quick health smoke for CARIB-CLEAR.
BASE_URL="${CARIB_CLEAR_BASE_URL:-http://127.0.0.1:8000}"
API_KEY="${CARIB_CLEAR_API_KEY:-}"

if [ -z "$API_KEY" ]; then
  echo "CARIB_CLEAR_API_KEY is required"
  exit 1
fi

fail=0
for path in /health /readyz /livez /metrics; do
  code=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "X-API-Key: ${API_KEY}" \
    "${BASE_URL}${path}") || code="000"
  if [ "$code" != "200" ]; then
    echo "FAIL ${path} -> ${code}"
    fail=1
  else
    echo "OK   ${path}"
  fi
done

exit "$fail"
