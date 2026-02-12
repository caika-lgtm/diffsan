"""Cursor CLI invocation for one-shot agent execution."""

from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import TYPE_CHECKING

from diffsan.contracts.errors import ErrorCode, ReviewerError

if TYPE_CHECKING:
    from diffsan.contracts.models import AppConfig


@dataclass(frozen=True, slots=True)
class AgentAttempt:
    """Single agent attempt details."""

    raw_stdout: str
    raw_stderr: str
    exit_code: int
    started_at: datetime
    ended_at: datetime
    duration_ms: int


def run_cursor_once(prompt: str, config: AppConfig) -> AgentAttempt:
    """Execute one agent attempt and return raw outputs."""
    command = _build_cursor_command(config.agent.cursor_command)
    if not command:
        raise ReviewerError(
            "Agent command is empty",
            error_code=ErrorCode.AGENT_EXEC_FAILED,
        )

    started_at = datetime.now(tz=UTC)
    start = perf_counter()
    try:
        result = subprocess.run(
            command,
            input=prompt,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise ReviewerError(
            "Failed to execute agent command",
            error_code=ErrorCode.AGENT_EXEC_FAILED,
            cause=exc,
            context={"command": command},
        ) from exc

    duration_ms = int((perf_counter() - start) * 1000)
    ended_at = datetime.now(tz=UTC)
    if result.returncode != 0:
        raise ReviewerError(
            "Agent command exited non-zero",
            error_code=ErrorCode.AGENT_EXEC_FAILED,
            cause=result.stderr.strip() or "unknown agent error",
            context={"command": command, "returncode": result.returncode},
        )

    return AgentAttempt(
        raw_stdout=result.stdout,
        raw_stderr=result.stderr,
        exit_code=result.returncode,
        started_at=started_at,
        ended_at=ended_at,
        duration_ms=duration_ms,
    )


def _build_cursor_command(cursor_cmd: str | None) -> list[str]:
    if cursor_cmd:
        return shlex.split(cursor_cmd)

    command = ["cursor-agent", "--print", "--output-format", "json"]
    api_key = os.getenv("CURSOR_API_KEY")
    if api_key:
        command.extend(["--api-key", api_key])
    return command
