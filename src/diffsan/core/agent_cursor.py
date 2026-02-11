"""Cursor CLI invocation for one-shot agent execution."""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
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
    duration_ms: int


def run_cursor_once(prompt: str, config: AppConfig) -> AgentAttempt:
    """Execute one agent attempt and return raw outputs."""
    command = shlex.split(config.agent.cursor_command)
    if not command:
        raise ReviewerError(
            "Agent command is empty",
            error_code=ErrorCode.AGENT_EXEC_FAILED,
        )

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
        duration_ms=duration_ms,
    )
