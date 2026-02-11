"""Helpers for writing and reading run artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class ArtifactStore:
    """Persist artifacts inside a run-scoped work directory."""

    def __init__(self, workdir: str | Path) -> None:
        self.workdir = Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)

    def path(self, relative_path: str | Path) -> Path:
        """Return absolute path for a workdir-relative artifact."""
        return self.workdir / relative_path

    def write_text(self, relative_path: str | Path, content: str) -> Path:
        """Write plain text artifact."""
        destination = self.path(relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        return destination

    def read_text(self, relative_path: str | Path) -> str:
        """Read plain text artifact."""
        return self.path(relative_path).read_text(encoding="utf-8")

    def write_json(self, relative_path: str | Path, payload: Any) -> Path:
        """Write JSON artifact, accepting pydantic models and plain objects."""
        destination = self.path(relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        serializable = _to_json_value(payload)
        destination.write_text(
            json.dumps(serializable, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return destination

    def read_json(self, relative_path: str | Path) -> Any:
        """Read and decode JSON artifact."""
        return json.loads(self.read_text(relative_path))


def _to_json_value(payload: Any) -> Any:
    if isinstance(payload, BaseModel):
        return payload.model_dump(mode="json")
    return payload
