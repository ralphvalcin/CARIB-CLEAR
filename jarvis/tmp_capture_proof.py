#!/usr/bin/env python3
"""Run one JARVIS voice capture, log exit state, and exit."""

import logging
import sys
import time

# Activate the voice guard so the loop doesn't refuse mic access.
from jarvis.voice.core import (
    GUARD_FILE_PATH,
    AudioCapture,
    KILL_FILE_PATH,
    TTSEngine,
    Transcriber,
    VoiceConfig,
    VoiceLLMClient,
    activate_guard,
    deactivate_guard,
    guard_active,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("jarvis.capture_proof")


def main() -> int:
    if not guard_active():
        if not activate_guard():
            logger.error("Unable to activate voice guard.")
            return 2

    config = VoiceConfig()

    capture = AudioCapture(config)
    transcriber = Transcriber(config)
    llm = VoiceLLMClient(config)
    tts = TTSEngine(config)

    capture._tts_interrupt_cb = tts.interrupt

    exit_reason = "unknown"
    captured_seconds = 0.0
    text = ""
    response_text = ""

    try:
        logger.info("=== Capture proof start ===")
        start = time.time()

        audio = capture.wait_for_voice()
        if audio is None:
            exit_reason = "no_audio_captured"
            logger.error("No audio captured.")
            return 1

        captured_seconds = len(audio) / float(config.sample_rate)
        logger.info("Captured %.2fs of audio", captured_seconds)

        text = transcriber.transcribe(audio)
        if not text:
            exit_reason = "no_speech_detected"
            logger.error("No speech detected.")
            return 1

        logger.info("You said: %s", text)

        token_gen = llm.stream_send(text)
        response_text = "".join(token_gen).strip()
        logger.info("LLM response length=%d chars", len(response_text))

        tts.speak(response_text)
        exit_reason = "ok"

    except Exception as exc:  # pragma: no cover - best-effort
        logger.exception("Capture proof failed: %s", exc)
        exit_reason = f"exception:{exc}"
        return 1
    finally:
        try:
            capture.stop()
            transcriber.cleanup()
            tts.cleanup()
            deactivate_guard()
        except Exception as exc:
            logger.warning("Cleanup failed: %s", exc)

    logger.info(
        "CAPTURE_PROOF_EXIT reason=%s captured_seconds=%.2f transcription_len=%d response_len=%d",
        exit_reason,
        captured_seconds,
        len(text),
        len(response_text),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
