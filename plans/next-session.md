# CARIB-CLEAR — Next Session Plan

## Priority 1: Wire Live Stellar Settlement into Demo

**Goal:** Running `python -m carib_clear.demo full --live` executes actual Stellar testnet path payments
instead of mock settlements.

**What's needed:**
- Update demo CLI to accept `--live` flag that sets `mock_mode=False`
- Update `StellarAdapter` to load participant secrets properly in live mode
- Add `--live` flag to `run_fx_swap_demo()` in `demo.py`
- Ensure enough balances remain in AMM pools for the $50K swap
- Print real Stellar transaction hashes in demo output

**Files to touch:** `demo.py`, `stellar_adapter.py`
**Expected effort:** 1 session
**Verification:** `python -m carib_clear.demo fx_swap --live` shows real on-chain tx hashes

---

## Priority 2: Dockerfile

**Goal:** Any judge can `docker compose up` and see the full demo in under 10 seconds.

**What's needed:**
- `Dockerfile` — Python 3.11 slim, install deps, copy project
- `docker-compose.yml` — single service, no external DB needed
- `.dockerignore` — exclude secrets, venv, node_modules, .git
- `scripts/entrypoint.sh` — run `pytest` then `demo full` for judge verification

**Expected effort:** 1 session
**Verification:** `docker compose up` shows the full BUILDATHON TRACK 3 banner

---

## Priority 3: Kreyol Mic Demo

**Goal:** Speak "Mwen bezwen $5,000 pou biznis mwen" into the mic, hear Kreyòl
response through speakers via JARVIS CARIB-CLEAR plugin.

**What's needed:**
- Ensure `jarvis/voice/carib_clear_plugin.py` is properly importable from JARVIS
- Run the JARVIS voice loop (`python -m jarvis.voice.loop`) with CARIB-CLEAR config
- Test with: "Mwen bezwen $5,000" → CARIB-CLEAR pipeline → Kreyòl TTS response
- Test with: "I need $10,000 for inventory" → CARIB-CLEAR pipeline → English TTS response
- Test with: "What's the weather?" → Normal JARVIS LLM (no intercept)

**Files to touch:** None (already integrated) — just verification and tuning
**Expected effort:** 1 session (verification + potential tuning)
**Verification:** Speak "Mwen bezwen $5,000" → hear Kreyòl response through speakers
