from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
import numpy as np

from jarvis.voice.core import VoiceConfig
from jarvis.voice.loop import VoiceLoop


class TestWakeWordConfig:
    def test_wake_word_disabled_by_default(self) -> None:
        config = VoiceConfig()
        assert config.wake_word_enabled is False
        assert config.wake_word == "jarvis"

    def test_wake_word_enabled_in_config(self) -> None:
        config = VoiceConfig(wake_word_enabled=True, wake_word="jarvis")
        assert config.wake_word_enabled is True
        assert config.wake_word == "jarvis"


class TestPlayConfirmationTone:
    def test_tone_does_not_crash(self) -> None:
        """Confirmation tone should handle errors gracefully (no audio hardware in CI)."""
        config = VoiceConfig()
        loop = VoiceLoop(config)
        # This should not raise — it catches exceptions internally
        loop._play_confirmation_tone()


class TestWakeWordDetect:
    def test_wake_word_not_detected_on_silence(self) -> None:
        """When no speech is captured, wake word detect returns None."""
        config = VoiceConfig(wake_word_enabled=True)
        loop = VoiceLoop(config)
        # Mock capture.record_seconds to return silence (zeros)
        loop.capture = MagicMock()
        loop.capture.record_seconds.return_value = np.zeros(16000, dtype=np.int16)
        # Mock transcriber to return empty text
        loop.transcriber = MagicMock()
        loop.transcriber.transcribe.return_value = ""

        result = loop._wake_word_detect()
        assert result is None

    def test_wake_word_detected_in_speech(self) -> None:
        """When speech contains the wake word, return the audio."""
        config = VoiceConfig(wake_word_enabled=True, wake_word="jarvis")
        loop = VoiceLoop(config)
        loop._running = True
        audio = np.ones(16000, dtype=np.int16) * 1000  # Simulated speech
        loop.capture = MagicMock()
        loop.capture.record_seconds.return_value = audio
        loop.transcriber = MagicMock()
        loop.transcriber.transcribe.return_value = "hey jarvis what time is it"

        result = loop._wake_word_detect()
        assert result is not None
        assert np.array_equal(result, audio)

    def test_wake_word_stops_when_not_running(self) -> None:
        """If the loop is stopped during wake word detection, return None."""
        config = VoiceConfig(wake_word_enabled=True)
        loop = VoiceLoop(config)
        loop._running = False
        loop.capture = MagicMock()

        result = loop._wake_word_detect()
        assert result is None