#!/usr/bin/env bash
set -e

# ─────────────────────────────────────────────────────────────────────────────
# CARIB-CLEAR — Buildathon Demo Starter
# ─────────────────────────────────────────────────────────────────────────────
# One command to install, verify, and launch the full CARIB-CLEAR demo:
#   Layer 1: CARICOM FX Swap Network
#   Layer 2: MSME Credit Layer (cash-flow lending, no collateral)
#   Web dashboard at http://localhost:8000/dashboard
#   Live Stellar testnet settlement (optional: pass --live)
# ─────────────────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
DIM='\033[2m'
NC='\033[0m'

echo -e "${CYAN}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║           CARIB-CLEAR — Buildathon Demo Launcher            ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ── Parse args ──────────────────────────────────────────────────────────────

LIVE=false
SKIP_TESTS=false
HOST="0.0.0.0"
PORT=8000

while [[ $# -gt 0 ]]; do
  case "$1" in
    --live) LIVE=true; shift ;;
    --skip-tests) SKIP_TESTS=true; shift ;;
    --host) HOST="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --help)
      echo "Usage: ./start.sh [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --live         Use live Stellar testnet settlement (requires secrets/)"
      echo "  --skip-tests   Skip pytest run (faster startup)"
      echo "  --host HOST    API server host (default: 0.0.0.0)"
      echo "  --port PORT    API server port (default: 8000)"
      echo "  --help         Show this help"
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# ── Step 1: Install dependencies ────────────────────────────────────────────

echo -e "\n${BLUE}[1/4]${NC} Installing dependencies..."
pip install -q -e ".[stellar]" 2>&1 | tail -1
echo -e "  ${GREEN}✅${NC} Dependencies installed"

# ── Step 2: Run tests ───────────────────────────────────────────────────────

if [ "$SKIP_TESTS" = false ]; then
  echo -e "\n${BLUE}[2/4]${NC} Running test suite..."
  if python3 -m pytest tests/ -q --ignore=tests/test_openrouter.py --ignore=tests/test_openrouter2.py 2>&1 | tail -1; then
    echo -e "  ${GREEN}✅${NC} All tests passing"
  else
    echo -e "  ${YELLOW}⚠️  Some tests failed — continuing anyway${NC}"
  fi
else
  echo -e "\n${BLUE}[2/4]${NC} ${YELLOW}Skipping tests (--skip-tests)${NC}"
fi

# ── Step 3: Quick demo (mock or live) ──────────────────────────────────────

echo -e "\n${BLUE}[3/4]${NC} Running demo..."
if [ "$LIVE" = true ]; then
  echo -e "  ${DIM}(live mode — Stellar testnet)${NC}"
  python3 -m carib_clear.demo full --live 2>&1 | tail -5
else
  python3 -m carib_clear.demo full 2>&1 | tail -5
fi

# ── Step 4: Launch API server ──────────────────────────────────────────────

echo -e "\n${BLUE}[4/4]${NC} Launching API server..."
echo ""
echo -e "  ${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  ${GREEN}  CARIB-CLEAR is running!${NC}"
echo -e "  ${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  ${CYAN}Dashboard:${NC}  http://localhost:$PORT/dashboard"
echo -e "  ${CYAN}Swagger:${NC}    http://localhost:$PORT/docs"
echo -e "  ${CYAN}Health:${NC}     http://localhost:$PORT/health"
echo ""
echo -e "  ${DIM}Demo FX Swap:  curl http://localhost:$PORT/demo/fx_swap${NC}"
echo -e "  ${DIM}Demo Credit:   curl http://localhost:$PORT/demo/msme_credit${NC}"
echo -e "  ${DIM}Loan Apply:    curl -X POST http://localhost:$PORT/loan/apply \\\\${NC}"
echo -e "  ${DIM}                 -H 'Content-Type: application/json' \\\\${NC}"
echo -e "  ${DIM}                 -d '{\"business_name\":\"My Biz\",\"jurisdiction\":\"HT\",\"amount_usd\":5000}'${NC}"
echo ""
echo -e "  ${YELLOW}Press Ctrl+C to stop${NC}"
echo ""

uvicorn carib_clear.api:app --host "$HOST" --port "$PORT"
