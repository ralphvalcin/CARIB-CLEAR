# JARVIS — Voice-Activated Personal Assistant

> **J**ust **A** **R**eally **V**ersatile **I**ntelligent **S**ystem

JARVIS is a voice-controlled AI assistant for macOS that lives on your machine. Speak to it, ask it questions, run commands — it handles the rest.

## Features

- 🎤 **Voice interface** — VAD-based listening, Whisper STT, Piper TTS
- 🔧 **Local tool execution** — Read files, check disk, run Python without network
- 🌐 **Hermes CLI bridge** — 235+ capabilities via skills and built-in tools
- ⚖️ **Policy gating** — Allow/deny/require-approval for every action
- 📋 **Approval queue** — SQLite-backed, restart-safe, idempotent
- 📊 **Live dashboard** — Health, drift, approvals, events (htmx-powered)
- 🧠 **Self-knowledge** — Knows its own capabilities, detects drift
- 🗣️ **Wake word** — Optional "Hey JARVIS" activation
- 📝 **Voice logging** — Every interaction logged and searchable

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt  # or: pip install -e .

# Download Piper voice model
mkdir -p piper_voices && cd piper_voices
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json
cd ..

# Start the API server
./run_api.sh

# Start talking
python3 -m jarvis.voice.loop
```

## Usage

```bash
# One-shot voice command
python3 -m jarvis.voice.loop --once

# Continuous conversation
python3 -m jarvis.voice.loop

# Wake word activation ("Hey JARVIS")
python3 -m jarvis.voice.loop --wake

# Low sensitivity (louder room)
python3 -m jarvis.voice.loop --sensitivity low

# Use HTTP mode (connect to running API)
python3 -m jarvis.voice.loop --http

# Open dashboard
open http://localhost:8000/dashboard

# See self-knowledge
curl http://localhost:8000/knowledge/self | jq .
```

## Project Structure

```
JARVIS/
├── jarvis/
│   ├── main.py              # Runtime orchestration
│   ├── api/
│   │   ├── app.py           # FastAPI endpoints
│   │   └── __init__.py
│   ├── runtime/
│   │   ├── router.py        # Intent routing
│   │   ├── policy.py        # Security policy
│   │   ├── approval_queue.py # SQLite approvals
│   │   ├── local_runner.py  # Local tool execution
│   │   ├── errors.py        # Error codes
│   │   └── __init__.py
│   ├── hermes_bridge/
│   │   ├── client.py        # Hermes CLI transport
│   │   ├── retry_client.py  # Exponential backoff
│   │   └── __init__.py
│   ├── knowledge/
│   │   ├── drift_checker.py # Capability drift detection
│   │   ├── self_doc.py      # Self-knowledge builder
│   │   └── __init__.py
│   ├── events/
│   │   ├── models.py        # Event schemas
│   │   ├── store.py         # JSONL + SQLite sinks
│   │   └── __init__.py
│   └── voice/
│       ├── core.py           # VAD, STT, TTS, response formatter
│       ├── loop.py           # Main voice loop
│       ├── log.py            # Voice interaction logger
│       └── __init__.py
├── tests/
│   ├── test_api_e2e.py       # 6 tests
│   ├── test_approval_flow.py # 11 tests
│   ├── test_events_store.py  # 4 tests
│   ├── test_hermes_client.py # 2 tests
│   ├── test_local_runner.py  # 24 tests
│   ├── test_main_flow.py     # 6 tests
│   ├── test_policy_and_drift.py # 2 tests
│   ├── test_retry_client.py  # 19 tests
│   ├── test_self_doc.py      # 13 tests
│   ├── test_voice.py         # 12 tests
│   ├── test_voice_logger.py  # 5 tests
│   └── test_wake_word.py     # 6 tests
├── data/                     # Created at runtime
│   ├── approvals.db          # Approval queue
│   ├── events.db             # Event log
│   ├── events.jsonl          # Events (JSONL)
│   └── voice_log.db          # Voice interaction log
├── piper_voices/             # Voice model files
├── run_api.sh                # API launcher
├── pyproject.toml
└── README.md
```

## Test Suite

```bash
# Run all tests
pytest tests/ -v

# Run 105 tests (all passing)
# Coverage: approval, policy, drift, local_runner, retry,
#           self-knowledge, voice, wake word, logging
```

## License

MIT