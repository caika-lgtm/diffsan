"""Structured event logger for artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from diffsan.contracts.events import Event, EventLevel


class EventLogger:
    """Append structured events to a JSONL file."""

    def __init__(self, events_file: str | Path) -> None:
        self.events_file = Path(events_file)
        self.events_file.parent.mkdir(parents=True, exist_ok=True)

    def emit(
        self,
        event: str,
        *,
        level: EventLevel = EventLevel.INFO,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Emit one event line."""
        payload = Event(level=level, event=event, data=data or {})
        with self.events_file.open("a", encoding="utf-8") as stream:
            stream.write(payload.model_dump_json() + "\n")
