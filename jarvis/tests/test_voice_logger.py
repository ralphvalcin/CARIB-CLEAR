from __future__ import annotations

from jarvis.voice.log import VoiceLogger, VoiceLogEntry


def test_empty_logger(tmp_path):
    logger = VoiceLogger(db_path=str(tmp_path / "empty.db"))
    assert logger.count() == 0
    assert logger.recent() == []


def test_append_and_recent(tmp_path):
    logger = VoiceLogger(db_path=str(tmp_path / "voice_log.db"))
    entry = VoiceLogEntry(
        utterance_id="utt-1",
        timestamp=1000.0,
        duration=2.5,
        transcription="hey jarvis what time is it",
        response_text="The time is 3:00 PM",
        response_path="direct_response",
        wake_word=True,
    )
    logger.append(entry)
    assert logger.count() == 1
    recent = logger.recent()
    assert len(recent) == 1
    assert recent[0]["transcription"] == "hey jarvis what time is it"
    assert recent[0]["wake_word"] == 1


def test_recent_limit(tmp_path):
    logger = VoiceLogger(db_path=str(tmp_path / "voice_log_limit.db"))
    for i in range(10):
        logger.append(
            VoiceLogEntry(
                utterance_id=f"utt-{i}",
                timestamp=float(i),
                duration=1.0,
                transcription=f"test {i}",
                response_text="ok",
                response_path="tool_action",
                wake_word=False,
            )
        )
    assert len(logger.recent(limit=5)) == 5
    # Most recent first (highest timestamp)
    recent = logger.recent(limit=3)
    assert recent[0]["utterance_id"] == "utt-9"
    assert recent[2]["utterance_id"] == "utt-7"


def test_search(tmp_path):
    logger = VoiceLogger(db_path=str(tmp_path / "voice_log_search.db"))
    logger.append(
        VoiceLogEntry(
            utterance_id="utt-1",
            timestamp=1.0,
            duration=1.0,
            transcription="what is the weather",
            response_text="weather is sunny",
            response_path="tool_action",
            wake_word=False,
        )
    )
    logger.append(
        VoiceLogEntry(
            utterance_id="utt-2",
            timestamp=2.0,
            duration=1.0,
            transcription="what time is it",
            response_text="it is noon",
            response_path="direct_response",
            wake_word=True,
        )
    )
    results = logger.search("weather")
    assert len(results) == 1
    assert results[0]["utterance_id"] == "utt-1"

    results = logger.search("time")
    assert len(results) == 1
    assert results[0]["utterance_id"] == "utt-2"


def test_non_wake_word_default(tmp_path):
    logger = VoiceLogger(db_path=str(tmp_path / "voice_log_default.db"))
    entry = VoiceLogEntry(
        utterance_id="utt-1",
        timestamp=1.0,
        duration=1.0,
        transcription="hello",
        response_text="hi",
        response_path="fallback",
        wake_word=False,
    )
    logger.append(entry)
    assert logger.count() == 1
    assert logger.recent()[0]["wake_word"] == 0