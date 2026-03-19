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

_TRUST_FLAGS = {"--trust", "--yolo", "-f"}
_MODEL_FLAGS = ("--model",)
_SENSITIVE_VALUE_FLAGS = {"--api-key", "--token", "--access-token", "--password"}


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
    command = _build_cursor_command(config.agent.cursor_command, config.agent.model)
    if not command:
        raise ReviewerError(
            "Agent command is empty",
            error_code=ErrorCode.AGENT_EXEC_FAILED,
        )
    sanitized_command = _sanitize_command_for_error_context(command)

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
            context={"command": sanitized_command},
        ) from exc

    duration_ms = int((perf_counter() - start) * 1000)
    ended_at = datetime.now(tz=UTC)
    if result.returncode != 0:
        raise ReviewerError(
            "Agent command exited non-zero",
            error_code=ErrorCode.AGENT_EXEC_FAILED,
            cause=result.stderr.strip() or "unknown agent error",
            context={"command": sanitized_command, "returncode": result.returncode},
        )

    return AgentAttempt(
        raw_stdout=result.stdout,
        raw_stderr=result.stderr,
        exit_code=result.returncode,
        started_at=started_at,
        ended_at=ended_at,
        duration_ms=duration_ms,
    )


def _build_cursor_command(cursor_cmd: str | None, model: str | None) -> list[str]:
    if cursor_cmd is not None:
        custom_command = shlex.split(cursor_cmd)
        if not custom_command:
            return []
        command = custom_command
        if model is not None:
            command = _set_flag_value(command, _MODEL_FLAGS, model)
        return _ensure_trust_flag(command)

    command = ["cursor-agent", "--print", "--output-format", "json"]
    if model is not None:
        command.extend(["--model", model])
    api_key = os.getenv("CURSOR_API_KEY")
    if api_key:
        command.extend(["--api-key", api_key])
    return _ensure_trust_flag(command)


def _set_flag_value(
    command: list[str], flags: tuple[str, ...], value: str
) -> list[str]:
    aliases = set(flags)
    prefixes = tuple(f"{flag}=" for flag in flags)
    rewritten: list[str] = []
    skip_next = False
    for idx, token in enumerate(command):
        if skip_next:
            skip_next = False
            continue
        if token in aliases:
            if idx + 1 < len(command) and not command[idx + 1].startswith("-"):
                skip_next = True
            continue
        if any(token.startswith(prefix) for prefix in prefixes):
            continue
        rewritten.append(token)
    rewritten.extend([flags[0], value])
    return rewritten


def _ensure_trust_flag(command: list[str]) -> list[str]:
    if any(flag in command for flag in _TRUST_FLAGS):
        return command
    return [*command, "--trust"]


def _sanitize_command_for_error_context(command: list[str]) -> list[str]:
    sanitized = list(command)
    for idx, token in enumerate(sanitized[:-1]):
        if token in _SENSITIVE_VALUE_FLAGS:
            sanitized[idx + 1] = "[REDACTED]"
    return sanitized
