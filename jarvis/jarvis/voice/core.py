"""Voice I/O core: audio capture, transcription, JARVIS integration, and TTS."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import logging
import os
import subprocess
import sys
import threading
import time

from jarvis.voice.voice_manager import VoiceManager

import numpy as np
import sounddevice as sd

logger = logging.getLogger("jarvis.voice")

# ── Guard File ───────────────────────────────────────────────────────────────
# When present, allows the voice loop to open the microphone.
# Without it, the loop refuses to start unless --force is passed.

GUARD_FILE_PATH = Path.home() / ".jarvis_voice_guard"
KILL_FILE_PATH = Path.home() / ".jarvis_voice_kill"


def guard_active() -> bool:
    """Return True if the guard file exists (mic permission granted)."""
    return GUARD_FILE_PATH.exists()


def activate_guard() -> bool:
    """Create the guard file. Returns True if newly created."""
    if guard_active():
        return False
    GUARD_FILE_PATH.touch(exist_ok=True)
    logger.info("🔓 Voice guard activated (%s)", GUARD_FILE_PATH)
    return True


def deactivate_guard() -> bool:
    """Remove the guard file. Returns True if it existed."""
    if not guard_active():
        return False
    GUARD_FILE_PATH.unlink(missing_ok=True)
    logger.info("🔒 Voice guard deactivated (%s)", GUARD_FILE_PATH)
    return True


def kill_requested() -> bool:
    """Return True if the kill switch file exists (request to stop immediately)."""
    return KILL_FILE_PATH.exists()


def clear_kill_signal() -> None:
    """Consume the kill signal so it doesn't persist."""
    KILL_FILE_PATH.unlink(missing_ok=True)


# ── Config ───────────────────────────────────────────────────────────────────

@dataclass
class VoiceConfig:
    """Configuration for the voice loop."""

    # Audio
    sample_rate: int = 16000
    block_duration: float = 0.5  # seconds per audio block for monitoring
    silence_rms_threshold: float = 0.001  # RMS (normalized float [-1,1]) below this = silence
    voice_rms_threshold: float = 0.004  # RMS (normalized float [-1,1]) above this = voice started
    silence_timeout: float = 0.5  # seconds of silence to end utterance
    max_record_seconds: float = 30.0
    max_listen_seconds: float = 120.0  # max seconds to wait for speech before returning
    input_device: Optional[int] = None  # None = system default

    # Transcription
    whisper_model_size: str = "tiny"  # tiny, base, small, medium, large
    whisper_device: str = "auto"  # auto, cpu, cuda
    whisper_compute_type: str = "int8"  # default, float16, int8

    # JARVIS
    in_process: bool = True  # True = import JarvisApp directly; False = HTTP
    api_url: str = "http://localhost:8000"
    api_key: str = ""

    # TTS
    tts_engine: str = "kokoro"  # "say", "piper", "kokoro", "none"
    piper_path: str = "/usr/local/bin/piper"
    piper_voice: str = "en_US-lessac-medium"
    piper_rate: float = 1.0
    kokoro_voice: str = "af_heart"
    kokoro_rate: float = 1.0

    # LLM
    llm_engine: str = "ollama"  # "ollama", "openai"
    llm_model: str = "llama3.2:3b"
    llm_fallback_engine: str = ""  # empty = no fallback
    llm_fallback_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.7
    llm_max_tokens: int = 256
    llm_timeout: float = 30.0
    ollama_base_url: str = "http://localhost:11434"
    openai_base_url: str = ""
    openai_api_key: str = ""

    # MCP — Model Context Protocol for dynamic tool discovery
    mcp_servers: List[Dict[str, Any]] = field(default_factory=list)
    """List of MCP server config dicts, e.g.:
    [{"name": "weather", "command": "uvx", "args": ["weather-mcp"]}]
    """
    mcp_enabled: bool = False

    # Sensitivity — adjusts voice/silence multiplier vs ambient
    sensitivity: str = "medium"  # "low", "medium", "high"

    # Voice activity
    wake_word_enabled: bool = False
    wake_word: str = "jarvis"

    def apply_env_defaults(self) -> None:
        import os as _os
        if _os.getenv("JARVIS_VOICE_MODEL"):
            self.whisper_model_size = _os.getenv("JARVIS_VOICE_MODEL", self.whisper_model_size)
        if _os.getenv("JARVIS_VOICE_TTS"):
            self.tts_engine = _os.getenv("JARVIS_VOICE_TTS", self.tts_engine)
        if _os.getenv("JARVIS_VOICE_SEARCH") is not None:
            self.wake_word_enabled = _os.getenv("JARVIS_VOICE_SEARCH", "").lower() not in {"0", "false", "no", "off"}
            self.wake_word = _os.getenv("JARVIS_VOICE_WORD", self.wake_word)


# ── Audio Capture ───────────────────────────────────────────────────────────

class AudioCapture:
    """Captures microphone audio with energy-based VAD."""

    def __init__(self, config: VoiceConfig) -> None:
        self.config = config
        self._stop_event = threading.Event()
        self._tts_last_speech: float = 0.0  # shared TTS playback timestamp
        self._tts_interrupt_cb: Any = None  # callable to interrupt TTS

    def __enter__(self) -> AudioCapture:
        return self

    def __exit__(self, *_: Any) -> None:
        self.stop()

    def __del__(self) -> None:
        self.stop()

    def stop(self) -> None:
        self._stop_event.set()

    def _auto_calibrate(self) -> tuple[float, float]:
        """Measure ambient noise floor, return (silence_rms, voice_rms) thresholds.

        Records 1.5 seconds of mic input, computes median RMS across blocks,
        and sets thresholds relative to the ambient floor.
        """
        fs = self.config.sample_rate
        block = int(fs * 0.25)  # 250ms blocks for calibration
        blocks_needed = 1  # minimum capture block
        rms_blocks: list[float] = []
        rms_blocks: list[float] = []

        def cal_callback(indata: np.ndarray, _frames: int, _info: Any, _status: Any) -> None:
            rms = float(np.sqrt(np.mean((indata.astype(np.float64) / 32768.0) ** 2)))
            rms_blocks.append(rms)
            if len(rms_blocks) >= blocks_needed:
                raise sd.CallbackStop

        try:
            with sd.InputStream(
                device=self.config.input_device,
                samplerate=fs,
                channels=1,
                blocksize=block,
                callback=cal_callback,
                dtype="int16",
            ):
                while len(rms_blocks) < blocks_needed:
                    sd.sleep(50)
        except sd.CallbackStop:
            pass

        if not rms_blocks:
            ambient_rms = 0.005  # fallback
        else:
            ambient_rms = float(np.median(rms_blocks))

        # Sensitivity presets — trade-off between catching quiet speech vs
        # false triggers from ambient noise
        _SENSITIVITY_MAP = {
            "high":   (1.1, 1.5),   # voice at 1.5x ambient — catches whispers
            "medium": (1.3, 2.5),   # voice at 2.5x ambient — good for normal rooms
            "low":    (1.8, 4.0),   # voice at 4.0x ambient — needs louder speech
        }
        sil_mult, voice_mult = _SENSITIVITY_MAP.get(
            self.config.sensitivity.lower(), (1.3, 2.5)
        )

        silence_rms = max(ambient_rms * sil_mult, 0.0005)
        voice_rms = max(ambient_rms * voice_mult, 0.002)

        if ambient_rms >= 0.03:
            voice_rms = min(voice_rms, 0.02)
            silence_rms = min(silence_rms, 0.008)

        if ambient_rms >= 0.06:
            room_mult = 1.2
            voice_rms = max(voice_rms, ambient_rms * room_mult)
            silence_rms = max(ambient_rms * 0.9, 0.005)

        # Cap thresholds so they never become impossible to cross.
        cap = 0.06
        if voice_rms > cap:
            voice_rms = cap
        if silence_rms > cap * 0.5:
            silence_rms = cap * 0.5
        logger.info(
            "VAD calibrated: ambient=%.5f  silence_thresh=%.5f  voice_thresh=%.5f  (sensitivity=%s)",
            ambient_rms, silence_rms, voice_rms, self.config.sensitivity,
        )
        return silence_rms, voice_rms

    def wait_for_voice(self) -> Optional[np.ndarray]:
        """Monitor mic until voice crosses threshold, then capture utterance.

        Auto-calibrates noise floor at the start of each call.
        Returns recorded audio as int16 numpy array, or None on interrupt.
        """
        silence_thresh, voice_thresh = self._auto_calibrate()
        fs = self.config.sample_rate
        block = int(fs * self.config.block_duration)  # samples per block
        max_samples = int(fs * self.config.max_record_seconds)

        audio_buffer: list[np.ndarray] = []
        silence_blocks = 0
        silence_limit = int(self.config.silence_timeout / self.config.block_duration)
        voice_active = False
        total_samples = 0

        def callback(indata: np.ndarray, frames: int, _time_info: Any, status: Any) -> None:
            nonlocal voice_active, silence_blocks, total_samples
            if status:
                logger.warning("sounddevice status: %s", status)

            rms = np.sqrt(np.mean((indata.astype(np.float64) / 32768.0) ** 2))

            # Echo suppression: if TTS was speaking < 300ms ago, ignore this block
            # BUT: if voice continues past the suppression window, it's the user
            # talking over JARVIS — interrupt TTS immediately
            if time.time() < self._tts_last_speech:
                if not voice_active:
                    return  # Still in quiet phase — ignore echo
                # If voice was already active, continue capture (user may be talking over TTS)

            # Interruption: if TTS is still playing and voice exceeds threshold,
            # kill TTS immediately so JARVIS stops talking
            if (
                rms >= voice_thresh
                and not voice_active
                and self._tts_interrupt_cb is not None
                and time.time() < self._tts_last_speech + 3.0
            ):
                logger.info("🔊 Voice detected during TTS — interrupting")
                self._tts_interrupt_cb()
                # Don't return — let this be treated as the start of a new utterance
                voice_active = True
                audio_buffer.append(indata.copy())
                total_samples += frames
                return

            if rms >= voice_thresh and not voice_active:
                voice_active = True
                logger.debug("Voice started (rms=%.4f)", rms)
                # include the block that triggered voice
                audio_buffer.append(indata.copy())
                total_samples += frames

            elif voice_active:
                if rms < silence_thresh:
                    silence_blocks += 1
                else:
                    silence_blocks = 0
                audio_buffer.append(indata.copy())
                total_samples += frames

                if silence_blocks >= silence_limit or total_samples >= max_samples:
                    raise sd.CallbackStop

        try:
            with sd.InputStream(
                device=self.config.input_device,
                samplerate=fs,
                channels=1,
                blocksize=block,
                callback=callback,
                dtype="int16",
            ):
                start = time.time()
                while not self._stop_event.is_set():
                    elapsed = time.time() - start
                    if elapsed >= self.config.max_listen_seconds:
                        logger.debug("Max listen time reached (%.0fs)", elapsed)
                        break
                    sd.sleep(100)
        except sd.CallbackStop:
            pass  # Expected — utterance ended

        if not audio_buffer:
            return None

        raw = np.concatenate(audio_buffer).ravel()
        return raw

    def record_seconds(self, duration: float) -> Optional[np.ndarray]:
        """Record a fixed-duration clip from the microphone."""
        fs = self.config.sample_rate
        samples = int(fs * duration)
        try:
            recording = sd.rec(
                samples,
                samplerate=fs,
                channels=1,
                device=self.config.input_device,
                dtype="int16",
            )
            sd.wait()
            return recording.ravel()
        except Exception as exc:
            logger.error("Recording failed: %s", exc)
            return None


# ── Transcriber ─────────────────────────────────────────────────────────────

class Transcriber:
    """Speech-to-text via registered backends (default: faster-whisper).

    Dispatches to the backend registered in SpeechRegistry for the configured
    STT engine. This makes it trivial to add new STT backends — just create a
    module, decorate with ``@SpeechRegistry.register("name")``, and it's
    auto-discovered.
    """

    def __init__(self, config: VoiceConfig) -> None:
        self.config = config
        self._backend: Any = None
        self._loaded: bool = False

    def _ensure_backend(self) -> Any:
        """Lazy-load the STT backend from the registry."""
        if self._loaded:
            return self._backend

        # Auto-discover speech backends
        from jarvis.voice.registry import SpeechRegistry

        SpeechRegistry.auto_discover("jarvis.voice.backends.faster_whisper")

        backend_cls = SpeechRegistry.get("faster-whisper")
        if backend_cls is None:
            raise RuntimeError("No STT backend registered")

        logger.info(
            "Loading Whisper model '%s' on device=%s compute=%s",
            self.config.whisper_model_size,
            self.config.whisper_device,
            self.config.whisper_compute_type,
        )
        self._backend = backend_cls(
            model_size=self.config.whisper_model_size,
            device=self.config.whisper_device,
            compute_type=self.config.whisper_compute_type,
        )
        self._loaded = True
        return self._backend

    def cleanup(self) -> None:
        """Release the Whisper model to free ~1GB RAM."""
        if self._backend is not None:
            self._backend.cleanup()
        self._backend = None
        self._loaded = False
        logger.debug("Whisper model released")

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe audio (int16) to text via registry backend."""
        backend = self._ensure_backend()
        return backend.transcribe(audio, language="en")


# ── TTS Engine ────────────────────────────────────────────────────────────────


class TTSEngine:
    """Text-to-speech output through system speakers.

    Dispatches to backends registered in TTSRegistry. Adding a new TTS engine
    is a single file with ``@TTSRegistry.register("name")`` — no changes
    needed in this class.

    Built-in engines: kokoro (default, recommended), piper (legacy), say.
    """

    def __init__(self, config: VoiceConfig) -> None:
        self.config = config
        self._backend: Any = None  # Lazy-loaded TTSBackend instance
        self._loaded: bool = False
        self._interrupted: bool = False
        self.last_speech_at: float = 0.0
        self.last_speech_till: float = 0.0

    def cleanup(self) -> None:
        """Release loaded models."""
        if self._backend is not None:
            self._backend.cleanup()
        self._backend = None
        self._loaded = False

    def interrupt(self) -> None:
        """Interrupt TTS playback immediately (user is speaking over it)."""
        self._interrupted = True
        import sounddevice as _sd
        try:
            _sd.stop()
        except Exception:
            pass

    # ── High-level API ──────────────────────────────────────────────────────

    def speak(self, text: str) -> None:
        """Speak text through default audio output."""
        if not text.strip():
            return

        engine = self.config.tts_engine
        if engine == "none":
            logger.info("TTS suppressed: %s", text)
            return

        logger.debug("TTS (%s): %s", engine, text[:60])
        backend = self._ensure_backend()
        if backend is None:
            logger.warning("No TTS backend available for engine '%s'", engine)
            return

        try:
            audio_bytes = backend.synthesize(text)
            if not audio_bytes:
                return
            self._play_audio(audio_bytes)
        except Exception as exc:
            logger.error("TTS (%s) failed: %s", engine, exc)

    def speak_streaming(self, text_generator) -> None:
        """Streaming TTS: speak sentences as they arrive from the LLM.

        Works with any registered backend. Each sentence is synthesized
        and played via sounddevice as it arrives.
        """
        import re as _re

        if not text_generator:
            return

        engine = self.config.tts_engine
        if engine == "none":
            # Consume and discard generator
            for _ in text_generator:
                pass
            return

        self._interrupted = False
        backend = self._ensure_backend()
        if backend is None:
            for _ in text_generator:
                pass
            return

        buffer = ""

        for token in text_generator:
            if self._interrupted:
                logger.debug("TTS streaming interrupted")
                break
            buffer += token

            # Flush on sentence boundaries
            match = _re.search(r"(.*?[.!?])\s*$", buffer)
            if match:
                sentence = match.group(1).strip()
                if sentence:
                    self._speak_sentence_streaming(backend, sentence)
                buffer = ""

        # Flush remaining text
        buffer = buffer.strip()
        if buffer and not self._interrupted:
            self._speak_sentence_streaming(backend, buffer)

        self.last_speech_till = time.time()

    # ── Backend management ──────────────────────────────────────────────────

    def _ensure_backend(self) -> Any:
        """Lazy-load the TTS backend from the registry."""
        if self._loaded:
            return self._backend

        engine = self.config.tts_engine

        # Auto-discover all TTS backends
        from jarvis.voice.registry import TTSRegistry

        TTSRegistry.auto_discover("jarvis.voice.backends.kokoro")
        TTSRegistry.auto_discover("jarvis.voice.backends.piper")
        TTSRegistry.auto_discover("jarvis.voice.backends.say")

        if not TTSRegistry.contains(engine):
            logger.error("No TTS backend registered for '%s'. Available: %s", engine, TTSRegistry.available())
            self._loaded = True  # Don't retry on every speak()
            return None

        backend_cls = TTSRegistry.get(engine)
        kwargs = self._backend_kwargs(engine)
        logger.info("Loading TTS backend '%s' with %s", engine, kwargs)
        self._backend = backend_cls(**kwargs)
        self._loaded = True
        return self._backend

    def _backend_kwargs(self, engine: str) -> dict:
        """Return backend-specific init kwargs from config."""
        if engine == "kokoro":
            return {"voice": self.config.kokoro_voice, "speed": self.config.kokoro_rate}
        if engine == "piper":
            return {"voice": self.config.piper_voice}
        return {}

    # ── Audio playback ──────────────────────────────────────────────────────

    def _play_audio(self, audio_bytes: bytes) -> None:
        """Play WAV/AIFF audio bytes through system speakers."""
        import io as _io
        import sounddevice as _sd
        import soundfile as _sf

        try:
            data, sr = _sf.read(_io.BytesIO(audio_bytes))
            self.last_speech_at = time.time()
            est_duration = len(data) / sr
            self.last_speech_till = time.time() + est_duration
            _sd.play(data, samplerate=sr)
        except Exception as exc:
            logger.error("Audio playback failed: %s", exc)

    def _speak_sentence_streaming(self, backend: Any, sentence: str) -> None:
        """Synthesize a single sentence and play it synchronously."""
        import io as _io
        import sounddevice as _sd
        import soundfile as _sf

        try:
            audio_bytes = backend.synthesize(sentence)
            if not audio_bytes:
                return
            data, sr = _sf.read(_io.BytesIO(audio_bytes))
            self.last_speech_at = time.time()
            _sd.play(data, samplerate=sr)
            _sd.wait()  # Block until sentence finishes
        except Exception as exc:
            logger.error("Streaming TTS playback failed: %s", exc)


# ── Response Formatter ──────────────────────────────────────────────────────

def format_response_for_tts(response: Dict[str, Any]) -> str:
    """Convert a JARVIS handle_text response into a TTS-friendly string."""
    if not isinstance(response, dict):
        return "JARVIS could not process that request."

    if response.get("error"):
        return f"Error: {response['error']}"

    if response.get("requires_approval"):
        action = response.get("action", "something")
        reason = response.get("reason", "")
        return f"I need your approval to {action}. {reason}. Check the dashboard to approve or deny."

    if response.get("denied"):
        reason = response.get("reason", "that action is not allowed")
        return f"That action is denied. {reason}"

    if response.get("path") == "drift_check":
        report = response.get("drift_report", {})
        missing = report.get("missing", [])
        if missing:
            return f"Drift check complete. Missing capabilities: {', '.join(missing)}. Everything else is in sync."
        return "Drift check complete. No capabilities have drifted. All systems are in sync."

    if response.get("path") == "direct_response":
        return response.get("response", "I'm ready. What would you like me to do?")

    if response.get("tool_result"):
        result = response.get("tool_result", {})
        if isinstance(result, dict) and result.get("ok"):
            return "Done. The action completed successfully."
        if isinstance(result, dict) and result.get("error"):
            return f"The action had an issue: {result['error']}"
        return "Done."

    if response.get("path") == "fallback":
        return "I couldn't process that request. Could you rephrase it?"

    return "Request received. Check the dashboard for details."


# ── JARVIS Client ───────────────────────────────────────────────────────────

class JarvisClient:
    """Interface to send text to JARVIS and get a response."""

    def __init__(self, config: VoiceConfig) -> None:
        self.config = config
        self._jarvis_app: Any = None
        self._session_id: str = f"voice-{int(time.time())}"

        if config.in_process:
            self._init_in_process()

    def _init_in_process(self) -> None:
        """Import and instantiate JarvisApp directly."""
        # Ensure the project root is on sys.path
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        from jarvis.main import JarvisApp

        self._jarvis_app = JarvisApp()
        logger.info("JARVIS voice client initialized (in-process)")

    def send(self, text: str) -> Dict[str, Any]:
        """Send transcribed text to JARVIS and return the response."""
        if self._jarvis_app:
            return self._jarvis_app.handle_text(session_id=self._session_id, text=text)

        # HTTP mode fallback
        import http.client
        import urllib.parse

        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["x-api-key"] = self.config.api_key

        try:
            import urllib.request

            body = json.dumps({"session_id": self._session_id, "text": text}).encode()
            req = urllib.request.Request(
                f"{self.config.api_url}/control/ingest",
                data=body,
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode())
        except Exception as exc:
            logger.error("HTTP request to JARVIS failed: %s", exc)
            return {"error": str(exc), "path": "error"}


# ── Voice LLM Client ────────────────────────────────────────────────────────────


class VoiceLLMClient:
    """Conversational LLM client for the voice loop.

    Uses LLMEngine (with backend resolution and fallback) to talk to the
    configured LLM with proper voice-optimized prompts and conversation
    history. Bypasses the JarvisApp routing layer for direct conversational
    interaction. Optional Tavily web search for current events queries.

    The engine is configurable — switch between Ollama, OpenAI, or any
    registered backend from VoiceConfig.
    """

    def __init__(
        self,
        enable_search: bool = True,
        config: Optional["VoiceConfig"] = None,
    ) -> None:
        from jarvis.voice.engine import LLMConfig, LLMEngine, VOICE_SYSTEM_PROMPT
        from jarvis.voice.registry import Conversation

        if config:
            llm_config = LLMConfig(
                engine=config.llm_engine,
                model=config.llm_model,
                fallback_engine=config.llm_fallback_engine,
                fallback_model=config.llm_fallback_model,
                temperature=config.llm_temperature,
                max_tokens=config.llm_max_tokens,
                timeout=config.llm_timeout,
                ollama_base_url=config.ollama_base_url,
                openai_base_url=config.openai_base_url,
                openai_api_key=config.openai_api_key,
            )
        else:
            llm_config = LLMConfig()

        self.engine = LLMEngine(llm_config)
        self._search_enabled = enable_search

        # Build system prompt with optional MCP tool context
        system_prompt = VOICE_SYSTEM_PROMPT

        # Discover MCP tools if configured
        self._mcp: Any = None
        if config and config.mcp_enabled and config.mcp_servers:
            system_prompt = self._init_mcp(config, system_prompt)

        self.conversation = Conversation(system_prompt=system_prompt)
        logger.info(
            "VoiceLLMClient initialized (engine=%s, model=%s, search=%s, fallback=%s, mcp=%s)",
            llm_config.engine, llm_config.model, enable_search,
            llm_config.fallback_engine or "none",
            config.mcp_enabled if config else False,
        )

    def _init_mcp(self, config: "VoiceConfig", base_prompt: str) -> str:
        """Initialize MCP tool discovery and augment the system prompt."""
        from jarvis.voice.mcp_client import MCPManager, MCPServerConfig

        try:
            server_configs = [
                MCPServerConfig(
                    name=s["name"],
                    command=s["command"],
                    args=s.get("args", []),
                    env=s.get("env", {}),
                    enabled=s.get("enabled", True),
                )
                for s in config.mcp_servers
            ]

            self._mcp = MCPManager(server_configs)
            tool_count = self._mcp.discover()

            if tool_count > 0:
                tool_block = self._mcp.tools_for_llm()
                augmented = f"{base_prompt}\n\n{tool_block}"
                logger.info("MCP: %d tools discovered across %d servers", tool_count, len(server_configs))
                return augmented

        except Exception as exc:
            logger.warning("MCP initialization failed: %s", exc)

        return base_prompt

    def send(self, text: str) -> str:
        """Send user text to LLM and return the full response."""
        self._inject_search(text)
        self.conversation.add_user(text)
        response = self.engine.chat(self.conversation)
        return response

    def stream_send(self, text: str):
        """Send user text to LLM and yield response tokens as they arrive."""
        self._inject_search(text)
        self.conversation.add_user(text)
        yield from self.engine.stream_chat(self.conversation)

    def _inject_search(self, text: str) -> None:
        """Run Tavily search if needed and inject results as conversation context.

        Inserts live search context as a transient system message immediately
        before the current user query. This preserves message order across
        multiple turns and makes the web results the clearest context for
        the LLM.
        """
        if not self._search_enabled:
            return
        try:
            from jarvis.voice.searcher import needs_search, search

            if not needs_search(text):
                return

            logger.info("🌐 Searching web for: %s", text[:60])
            context = search(text)
            if not context:
                return

            self.conversation.messages.append({"role": "system", "content": context})
            logger.info("🌐 Web results injected (message #%d)", len(self.conversation.messages))
        except Exception as exc:
            logger.warning("Web search injection failed: %s", exc)

    def reset(self) -> None:
        """Clear conversation history (keep system prompt)."""
        self.conversation.reset()
        logger.info("VoiceLLMClient conversation reset")