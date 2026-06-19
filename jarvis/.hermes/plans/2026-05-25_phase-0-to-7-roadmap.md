# JARVIS Architecture — Full Roadmap Plan

> **Status:** Planning phase — no code changes in this document.
> **Context:** JARVIS voice loop works (Piper TTS, auto-calibrating VAD, echo cooldown). API server was running but killed during cleanup. 35 tests passing, zero drift across 132 capabilities.

**Goal:** Ship a robust, self-aware JARVIS that works reliably, knows its limits, and scales gracefully.

**Architecture:** Hermes orchestration core (Architecture A) — JARVIS shells out to Hermes CLI for tool execution, handles everything else in-process.

**Tech Stack:** Python 3.12, FastAPI (API), Piper TTS, Whisper (STT), SQLite (approvals + events), sounddevice (mic), Hermes CLI (tool bridge).

---

## Phase 0: 🔧 Restart the API (immediate)

The uvicorn API server was killed during process cleanup. Health check fails because nothing is listening on port 8000.

**Files:**
- Modify: `jarvis/api/app.py` — no changes needed
- Script: `scripts/api.sh` (start/stop scripts)

**Task 1: Restart the API server**

```
cd ~/JARVIS && uvicorn jarvis.api.app:app --host 127.0.0.1 --port 8000 &
```

Run and verify `/health` returns `{"status": "ok"}`.

**Task 2: Create API lifecycle scripts**

Create `scripts/api.sh` and `scripts/api-stop.sh` with same pattern as voice scripts (logged launch, PID tracking, `tail -f`).

**Verification:** `curl http://127.0.0.1:8000/health` returns 200.

---

## Phase 1: ⏱️ API Rate Limit Resilience

**Problem:** `CLIHermesClient.run_tool()` shells out to `hermes chat` which hits the AI provider rate limit. Every voice interaction goes through this path when it needs a tool execution.

**Approach:** Add retry-with-backoff, degrade gracefully, and short-circuit tool actions that can be handled locally.

**Files:**
- Create: `jarvis/hermes_bridge/retry.py`
- Modify: `jarvis/hermes_bridge/client.py`
- Modify: `jarvis/main.py` (handle Hermes failure gracefully)
- Test: `tests/test_hermes_retry.py`

**Task 1: Create retry-with-backoff utility**

```python
# jarvis/hermes_bridge/retry.py
from typing import TypeVar, Callable
import time
import logging

T = TypeVar("T")

def with_retry(
    fn: Callable[[], T],
    max_attempts: int = 3,
    base_delay: float = 1.0,
    backoff: float = 2.0,
    retryable_exceptions: tuple = (),
) -> T:
    """Call fn with exponential backoff retry."""
```

**Task 2: Wire retry into `CLIHermesClient.run_tool()`**

Add `retry` parameter (default 2 attempts). On any non-200 response or timeout, retry with backoff. Log each attempt.

**Task 3: Add local-only tool execution short-circuit**

Tools like `terminal`, `read_file`, `write_file` don't need the Hermes CLI — JARVIS can run them directly. Refactor to try local execution first, fall back to Hermes CLI.

**Task 4: Graceful degradation in `JarvisApp.handle_text()`**

When Hermes CLI fails after retries, return a structured error instead of crashing:
```json
{"path": "tool_action", "tool_result": {"ok": false, "error": "JARVIS API unavailable — try again later"}}
```

**Task 5: Test the fallback chain**

```
pytest tests/test_hermes_retry.py -v
```

**Verification:** Kill Hermes CLI, run voice loop, say "search for something" — JARVIS says "JARVIS API unavailable" instead of crashing.

---

## Phase 2: 📖 Self-Knowledge Document

**Problem:** JARVIS has no way to introspect its own capabilities. The `HermesCapabilitySource` queries Hermes CLI but the result isn't saved or displayed anywhere.

**Approach:** Generate a living self-knowledge document in markdown that JARVIS updates on drift checks. This becomes the reference for what JARVIS can and can't do.

**Files:**
- Create: `jarvis/knowledge/self_knowledge.py`
- Modify: `jarvis/knowledge/drift_checker.py` (add doc generation)
- Modify: `jarvis/main.py` (expose self-knowledge endpoint)
- Test: `tests/test_self_knowledge.py`

**Task 1: Self-knowledge document generator**

```python
class SelfKnowledge:
    """Generates JARVIS's self-knowledge document."""
    
    def generate(self) -> str:
        """Return a markdown document of capabilities, limits, and drift state."""
        
    def save(self, path: str = "./data/self_knowledge.md") -> str:
        """Write to disk and return path."""
```

Document sections:
- `## Capabilities` — all installed skills + built-in tools
- `## Missing` — expected but absent (from drift report)
- `## Voice` — STT model, TTS engine, VAD state
- `## Approvals` — pending count, stale claim info
- `## Last Updated` — timestamp

**Task 2: Auto-update on drift check**

In `handle_text()` path `drift_check`, after running checker, also generate + save self-knowledge doc.

**Task 3: Expose via API**

```
GET /knowledge/self  → returns the self-knowledge doc as text/markdown
GET /knowledge/drift → returns the current drift report as JSON
```

**Task 4: Test**

```
pytest tests/test_self_knowledge.py -v
```

**Verification:** Say "run a drift check" via voice, then browse to http://localhost:8000/knowledge/self and see a complete capability document.

---

## Phase 3: 🧠 System-Prompt Injection

**Problem:** `handle_text()` returns the same hardcoded response *"Aye — I can help with that. What exact action should I run?"* regardless of context. JARVIS doesn't know what it can do.

**Approach:** Inject drift report + self-knowledge into the `direct_response` path so JARVIS gives context-aware replies.

**Files:**
- Modify: `jarvis/main.py` (enrich direct_response with self-knowledge)
- Modify: `jarvis/voice/core.py` (format_response_for_tts for enriched response)
- Test: `tests/test_main_flow.py` (update assertion)

**Task 1: Enrich direct_response with capability hints**

When the path is `direct_response`, attach a `capabilities_hint` field showing available actions (top 5 tools + skills). The TTS formatter can truncate to avoid speech overload.

**Task 2: Drift-aware fallback messages**

If `drift_checker.run()` shows missing capabilities, inject a warning: `"Warning: web_search capability is missing."`

**Task 3: Test that enriched responses parse correctly**

```
pytest tests/test_main_flow.py -v
```

**Verification:** Say "hello" via voice — JARVIS should respond with something like *"Aye! I have 99 skills and 21 tools ready. Try: run a drift check, search the web, open a file."*

---

## Phase 4: 🖥️ Dashboard Enhancement

**Problem:** The dashboard exists (embedded HTML in api/app.py) but is bare-bones — shows only approvals and basic metrics.

**Approach:** Add drift status, event log viewer, voice session history, and a capability tree to the dashboard.

**Files:**
- Modify: `jarvis/api/app.py` (add dashboard sections)
- Create: `jarvis/api/dashboard.py` (reusable dashboard components)
- No tests needed (UI-only)

**Task 1: Add drift status panel**

New dashboard section showing:
- Drift count (green if 0, red if >0)
- Missing capabilities list
- Last checked time
- Auto-refresh every 30s

**Task 2: Add event log viewer**

New panel showing recent events (last 50) with:
- Timestamp, type, level
- Color-coded by level (info=blue, warn=yellow, error=red)
- Auto-refresh

**Task 3: Add voice session timeline**

Show last 10 voice interactions:
- "You said: ..." — "JARVIS: ..."
- Timestamp
- VAD settings used

**Task 4: Add capability tree**

Interactive tree view of:
- Categories (mlops, creative, devops, etc.)
- Skills under each category
- Click to inspect skill

**Verification:** Browse to http://localhost:8000/dashboard — see all 4 panels updating live.

---

## Phase 5: 🗣️ Wake Word Detection

**Problem:** VAD triggers on any noise — conversation near the MacBook, TV, other people talking. This causes false activations.

**Approach:** Add "Hey JARVIS" wake word detection using a lightweight keyword spotting model. Only process audio after wake word is detected.

**Files:**
- Create: `jarvis/voice/wake_word.py`
- Modify: `jarvis/voice/core.py` (wake word config)
- Modify: `jarvis/voice/loop.py` (wake word loop integration)
- Create: `scripts/download_wake_model.sh`
- Test: `tests/test_wake_word.py`

**Task 1: Select and download a wake word model**

Options (from simplest to most sophisticated):
1. Porcupine (Picovoice) — `pip install pvporcupine`, free tier
2. OpenWakeWord — `pip install openwakeword`, fully open-source
3. Custom — train a simple energy+pattern matcher for "jarvis"

Recommend: **OpenWakeWord** — open-source, no API key, lightweight.

**Task 2: Implement WakeWordDetector**

```python
class WakeWordDetector:
    def __init__(self, wake_word: str = "jarvis"):
        self.detector = ...
    
    def listen(self, stream, callback) -> None:
        """Stream from mic, call callback on wake word detection."""
    
    def stop(self) -> None:
        ...
```

**Task 3: Wire into VoiceLoop**

In `_process_utterance`, when `wake_word_enabled=True`:
1. First call `wake_detector.listen()` — wait for wake word
2. Then proceed with normal VAD capture
3. Add wake word status to log output

**Task 4: Add `--wake-word` CLI flag**

```
python3 jarvis/voice/loop.py --wake-word
```

**Task 5: Test wake word detection with recorded samples**

```
pytest tests/test_wake_word.py -v
```

**Verification:** Voice loop ignores all ambient noise until you say "Hey JARVIS", then Piper responds.

---

## Phase 6: 📝 Voice Logging & Review

**Problem:** Voice interactions happen but aren't saved anywhere searchable. Debugging the echo loop required reading raw process output.

**Approach:** Log every voice interaction (audio path, transcription, response, VAD state) to a SQLite database with a searchable web UI.

**Files:**
- Create: `jarvis/voice/logger.py`
- Modify: `jarvis/voice/loop.py` (integrate logger)
- Modify: `jarvis/api/app.py` (voice log endpoints)
- Create: `scripts/voice-log.sh` (search/review utility)
- Test: `tests/test_voice_logger.py`

**Task 1: VoiceLogStore**

```python
@dataclass
class VoiceInteraction:
    id: str
    timestamp: float
    duration_s: float
    transcription: str
    response_text: str
    vad_ambient: float
    vad_voice_thresh: float
    sensitivity: str
    tts_engine: str
    wake_word_used: bool

class VoiceLogStore:
    def append(self, interaction: VoiceInteraction) -> None: ...
    def search(self, query: str) -> List[VoiceInteraction]: ...
    def recent(self, limit: int = 20) -> List[VoiceInteraction]: ...
```

**Task 2: Integrate into VoiceLoop**

In `_process_utterance()`, after getting transcription and response, create a `VoiceInteraction` record and append to store.

**Task 3: API endpoints**

```
GET /voice/logs?limit=20&query=searchterm  → JSON log entries
GET /voice/logs/html                        → HTML table view
```

**Task 4: CLI search tool**

```bash
python3 scripts/voice-log.sh --search "drift"  # Shows all interactions mentioning drift
python3 scripts/voice-log.sh --recent 5         # Last 5 interactions
python3 scripts/voice-log.sh --stats            # Usage statistics
```

**Task 5: Test**

```
pytest tests/test_voice_logger.py -v
```

**Verification:** After a few voice interactions, http://localhost:8000/voice/logs shows a searchable table of everything JARVIS has heard and said.

---

## Phase 7: 📚 Documentation

**Problem:** No README, no setup guide, no architecture overview. Project is opaque to new developers.

**Approach:** Write comprehensive documentation covering setup, architecture, usage, and development.

**Files:**
- Create: `README.md`
- Create: `docs/SETUP.md`
- Create: `docs/ARCHITECTURE.md`
- Create: `docs/VOICE.md`
- Create: `CONTRIBUTING.md`
- Modify: `pyproject.toml` (add README metadata)

**Task 1: README.md**

Sections:
- What is JARVIS?
- Quick start (clone, install deps, run)
- Architecture overview (one paragraph)
- Usage examples
- Project structure
- Status badges (tests, drift)
- License

**Task 2: SETUP.md**

Step-by-step:
1. Prerequisites (Python 3.12+, Piper voice model download)
2. Clone and install
3. Environment variables
4. Starting the API
5. Starting the voice loop
6. Testing it works

**Task 3: ARCHITECTURE.md**

Detailed overview with:
- Module tree and purpose of each
- Data flow diagram (text-based)
- Runtime flow: Voice → Transcribe → Route → Policy → Execute → TTS
- Hermes integration points
- Event system
- Approval workflow

**Task 4: VOICE.md**

Voice-specific docs:
- VAD calibration and sensitivity
- TTS engine comparison (Piper vs say vs none)
- Echo cooldown tuning
- Mic troubleshooting (MacBook Air specific)
- Wake word setup

**Task 5: CONTRIBUTING.md**

How to contribute:
- Code style
- Test requirements
- PR workflow
- Skill authoring

**Task 6: Update pyproject.toml**

Add `[project.readme]` pointing to README.md.

**Verification:** README renders properly on GitHub. All links work.
