# JARVIS Architecture

## Overview

JARVIS is a modular voice-controlled AI assistant. Six main domains:

```
Voice ────→ Runtime ────→ Hermes CLI
  │             │
  │             ├── Policy Engine
  │             ├── Approval Queue
  │             ├── Event Logger
  │             └── Local Runner
  │
  └── API ──→ Dashboard
```

## Data Flow

### Voice Path (primary)

```
Mic → VAD (energy detection)
   → Audio capture (while speaking + silence gap)
   → Whisper STT (faster-whisper, base model)
   → JarvisApp.handle_text()
      ├── IntentRouter.route()
      ├── PolicyEngine.evaluate()
      ├── LocalCapabilityRunner.run()  (if handled locally)
      ├── RetryingHermesClient.run()   (if Hermes needed)
      └── Event logging (JSONL + SQLite)
   → format_response_for_tts()
   → Piper TTS → Speakers
```

### Wake Word Path

```
Mic → VAD (energy detection)
   → 2s audio capture
   → Whisper STT
   → Wake word match? ("jarvis")
      ├── Yes → Confirmation tone → Full utterance capture
      └── No  → Continue listening
```

### API Path

```
HTTP → FastAPI → JarvisApp → Response
  GET  /health
  GET  /dashboard            (live-updating htmx dashboard)
  GET  /dashboard/_health    (health + drift cards)
  GET  /dashboard/_metrics   (approval metrics)
  GET  /dashboard/_pending   (pending approvals)
  GET  /dashboard/_events    (recent events)
  GET  /knowledge/self       (self-knowledge JSON)
  GET  /knowledge/self/markdown (self-knowledge markdown)
  GET  /voice-log            (voice interaction log)
  POST /control/evaluate     (policy check)
  POST /control/ingest       (process text)
  POST /control/approvals/{id}/approve
  POST /control/approvals/{id}/deny
  POST /events               (log custom event)
```

## Module Map

### `jarvis/runtime/` — Core Decision Layer

| File | Responsibility |
|------|---------------|
| `router.py` | Keyword-based intent routing (drift_check, tool_action, direct_response) |
| `policy.py` | Allow/deny/require_approval decisions per action |
| `approval_queue.py` | SQLite-backed pending action queue with atomic claim for idempotent execution |
| `local_runner.py` | Local tool execution (read_file, list_dir, run_python, check_disk, time, system_info) |
| `errors.py` | Error code enum for structured error responses |

### `jarvis/hermes_bridge/` — Hermes CLI Integration

| File | Responsibility |
|------|---------------|
| `client.py` | Subprocess adapter for `hermes` CLI (run_tool, chat, list_skills) |
| `retry_client.py` | Exponential backoff wrapper — retries on 429s, timeouts, connection errors |

### `jarvis/knowledge/` — Self-Knowledge

| File | Responsibility |
|------|---------------|
| `drift_checker.py` | Compares expected vs observed capabilities, reports drift |
| `self_doc.py` | Generates structured markdown self-knowledge document |

### `jarvis/events/` — Observability

| File | Responsibility |
|------|---------------|
| `models.py` | Typed Event dataclass with UUID, timestamp, level |
| `store.py` | Dual sink: JSONL (easy tail) + SQLite (searchable) |

### `jarvis/voice/` — Voice I/O

| File | Responsibility |
|------|---------------|
| `core.py` | AudioCapture (VAD + calibration), Transcriber (Whisper), TTSEngine (Piper), response formatter |
| `loop.py` | Voice loop, wake word detection, confirmation tone, voice logging integration |
| `log.py` | SQLite-backed voice interaction logger |

### `jarvis/api/` — Web Interface

| File | Responsibility |
|------|---------------|
| `app.py` | FastAPI app with all endpoints, htmx dashboard, sweeper thread for stale approvals |

## Key Design Decisions

1. **Hermes CLI as orchestration core** — JARVIS delegates to Hermes for skills and remote tools, but handles local operations independently
2. **SQLite for state** — Approvals, events, voice logs all use SQLite for durability and restart safety
3. **Idempotent approvals** — Atomic claim transition prevents double execution under race conditions
4. **Dynamic VAD calibration** — Measures ambient noise before each listen cycle; no fixed thresholds
5. **Echo feedback prevention** — Mute cooldown after TTS lets speaker audio fade before next listen
6. **Self-knowledge caching** — System preamble rebuilt every 5 minutes, not per-utterance
7. **Fallback chain** — Local runner → Retrying Hermes → Graceful error — maximizes reliability