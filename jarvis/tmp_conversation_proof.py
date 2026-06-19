#!/usr/bin/env python3
"""Run JARVIS back-and-forth conversation with multiple voice turns."""

import logging
import sys
import time

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
logger = logging.getLogger("jarvis.conversation_proof")


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
    turns = 0
    try:
        logger.info("=== Conversation proof start ===")
        tts.speak("JARVIS is listening. Say something.")

        while turns < 3:
            logger.info("--- Turn %d ---", turns + 1)
            audio = capture.wait_for_voice()
            if audio is None:
                exit_reason = "no_audio_captured"
                logger.error("No audio captured on turn %d.", turns + 1)
                break

            captured_seconds = len(audio) / float(config.sample_rate)
            text = transcriber.transcribe(audio)
            if not text:
                logger.info("No speech detected on turn %d.", turns + 1)
                continue

            logger.info("You said: %s", text)
            token_gen = llm.stream_send(text)
            response_text = "".join(token_gen).strip()
            logger.info("JARVIS says (%d chars): %s", len(response_text), response_text[:160])
            tts.speak(response_text)
            exit_reason = "ok"
            turns += 1

            logger.info("--- End of turn %d ---", turns)

    except Exception as exc:
        logger.exception("Conversation proof failed: %s", exc)
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

    logger.info("CONVERSATION_PROOF_EXIT reason=%s turns=%d", exit_reason, turns)
    return 0


if __name__ == "__main__":
    sys.exit(main())
