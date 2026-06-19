# Contributing to JARVIS

## Development Setup

```bash
cd JARVIS
pip install -e ".[dev]"
```

## Code Standards

- Python 3.12+ with `from __future__ import annotations`
- Type hints on all public functions
- Docstrings on classes and public methods
- No `print()` — use `logging.getLogger()`

## Adding a New Capability

1. If it's a **local tool** (no network needed):
   - Add the tool function in `jarvis/runtime/local_runner.py`
   - Register it in `LocalCapabilityRunner.__init__()`
   - Write tests in `tests/test_local_runner.py`

2. If it's a **Hermes skill**:
   - Install it via `hermes skills install <name>`
   - Run `drift check` to see it appear in capabilities

3. If it's a **new route**:
   - Add keyword matching in `jarvis/runtime/router.py`
   - Add policy rules in `jarvis/runtime/policy.py` (if needed)

## Adding a New API Endpoint

1. Add the route function to `jarvis/api/app.py`
2. If it returns HTML for the dashboard, add an htmx partial endpoint
3. Add E2E test in `tests/test_api_e2e.py`

## Test Conventions

```bash
# Run all tests
pytest tests/ -v

# Run a specific test file
pytest tests/test_local_runner.py -v

# Run a specific test
pytest tests/test_wake_word.py::TestWakeWordConfig -v
```

- Tests use `tmp_path` for SQLite databases (never touch real data/)
- Mock external dependencies (Hermes CLI, audio hardware, Piper)
- Every new feature needs >1 test
- All 105+ tests must pass before commits

## Drift Awareness

JARVIS has a self-knowledge system that detects when capabilities drift:

```python
# Check drift from code
from jarvis.knowledge.drift_checker import DriftChecker, HermesCapabilitySource
checker = DriftChecker(HermesCapabilitySource())
report = checker.run()
print(f"Missing: {report.missing}")     # things expected but not found
print(f"Unexpected: {report.unexpected}") # things found but not expected
```

When adding code that changes JARVIS' capabilities:
1. Update the declared capability set in `jarvis/knowledge/drift_checker.py` (the `_JARVIS_EXTRA_CAPABILITIES` set)
2. Run drift check to confirm no unexpected gaps
3. The self-knowledge document and system preamble auto-reflect changes

## Project Structure Rules

- `jarvis/runtime/` — no I/O, no external calls except through registered tools
- `jarvis/hermes_bridge/` — Hermes CLI communication only
- `jarvis/knowledge/` — introspection and self-awareness
- `jarvis/events/` — observability (sinks, schemas)
- `jarvis/voice/` — audio capture, STT, TTS
- `jarvis/api/` — web interface, dashboard
- `tests/` — flat, one file per module, functional over unit