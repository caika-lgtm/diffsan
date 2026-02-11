"""Structured event logger for artifacts."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, TextIO

from diffsan.contracts.events import Event, EventLevel


class EventLogger:
    """Append structured events to a JSONL file."""

    def __init__(
        self,
        events_file: str | Path,
        *,
        echo: bool = False,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
    ) -> None:
        self.events_file = Path(events_file)
        self.events_file.parent.mkdir(parents=True, exist_ok=True)
        self.echo = echo
        self.stdout = stdout if stdout is not None else sys.stdout
        self.stderr = stderr if stderr is not None else sys.stderr

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
        if self.echo:
            self._emit_console_line(payload)

    def _emit_console_line(self, payload: Event) -> None:
        line = f"[diffsan] {payload.event}"
        summary = _summarize_data(payload.data)
        if summary:
            line = f"{line} | {summary}"
        stream = self.stderr if payload.level == EventLevel.ERROR else self.stdout
        print(line, file=stream)


def _summarize_data(data: dict[str, Any]) -> str:
    if not data:
        return ""
    preferred_keys = [
        "message",
        "error_code",
        "ok",
        "skipped",
        "duration_ms",
        "chars",
        "files",
        "final_chars",
        "truncated",
        "redaction_found",
        "attempt",
        "exit_code",
        "findings",
        "path",
    ]
    selected: list[tuple[str, Any]] = []
    for key in preferred_keys:
        if key in data and _is_simple(data[key]):
            selected.append((key, data[key]))
    if not selected:
        for key, value in data.items():
            if _is_simple(value):
                selected.append((key, value))
            if len(selected) == 4:
                break
    return ", ".join(f"{key}={_short(value)}" for key, value in selected)


def _is_simple(value: Any) -> bool:
    return isinstance(value, str | int | float | bool) or value is None


def _short(value: Any) -> str:
    if value is None:
        return "none"
    text = str(value)
    if len(text) > 120:
        return f"{text[:117]}..."
    return text
