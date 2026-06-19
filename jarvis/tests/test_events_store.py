from __future__ import annotations

from jarvis.events.store import JsonlEventStore
from jarvis.events.models import Event


def test_recent_empty_file(tmp_path):
    store = JsonlEventStore(path=str(tmp_path / "empty.jsonl"))
    assert store.recent() == []


def test_recent_returns_appended_events(tmp_path):
    store = JsonlEventStore(path=str(tmp_path / "events.jsonl"))
    for i in range(3):
        evt = Event(type="test", session_id=f"s{i}", payload={"num": i})
        store.append(evt)

    recent = store.recent(limit=10)
    assert len(recent) == 3
    assert recent[0]["type"] == "test"
    assert recent[0]["payload"]["num"] == 0


def test_recent_limit(tmp_path):
    store = JsonlEventStore(path=str(tmp_path / "events_limit.jsonl"))
    for i in range(20):
        evt = Event(type="test", session_id=f"s{i}", payload={"num": i})
        store.append(evt)

    recent = store.recent(limit=5)
    assert len(recent) == 5
    nums = [e["payload"]["num"] for e in recent]
    assert nums == [15, 16, 17, 18, 19]


def test_recent_ignores_bad_lines(tmp_path):
    p = tmp_path / "corrupt.jsonl"
    p.write_text('{"type":"good"}\ncorrupt_line\n{"type":"also_good"}\n')
    store = JsonlEventStore(path=str(p))
    recent = store.recent(limit=10)
    assert len(recent) == 2