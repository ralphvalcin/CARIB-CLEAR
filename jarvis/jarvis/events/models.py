from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Literal
import time
import uuid

EventLevel = Literal["info", "warn", "error"]


@dataclass
class Event:
    type: str
    session_id: str
    payload: Dict[str, Any]
    level: EventLevel = "info"
    ts: float = field(default_factory=time.time)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
