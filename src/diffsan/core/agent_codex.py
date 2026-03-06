"""Codex CLI invocation for structured-output agent execution."""

from __future__ import annotations

import json
import shlex
import subprocess
from datetime import UTC, datetime
from time import perf_counter
from typing import TYPE_CHECKING

from diffsan.contracts.errors import ErrorCode, ReviewerError
from diffsan.contracts.models import AgentReviewOutput, AppConfig
from diffsan.core.agent_cursor import AgentAttempt

if TYPE_CHECKING:
    from pathlib import Path

_DEFAULT_SANDBOX = "read-only"
_OUTPUT_SCHEMA_FLAG = "--output-schema"
_OUTPUT_LAST_MESSAGE_FLAG = "--output-last-message"
_SANDBOX_FLAG = "--sandbox"
_SENSITIVE_VALUE_FLAGS = {"--api-key", "--token", "--access-token", "--password"}


def run_codex_once(
    prompt: str,
    config: AppConfig,
    *,
    workdir: Path,
    schema_filename: str = "codex-output-schema.json",
    output_filename: str = "codex-output.json",
) -> AgentAttempt:
    """Execute one codex attempt and return structured output payload text."""
    schema_path = workdir / schema_filename
    output_path = workdir / output_filename
    _write_output_schema(schema_path)

    command = _build_codex_command(
        config.agent.codex_command,
        schema_path=schema_path,
        output_path=output_path,
    )
    sanitized_command = _sanitize_command_for_error_context(command)
    output_path.unlink(missing_ok=True)

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

    raw_stdout = _read_output_file(output_path)
    return AgentAttempt(
        raw_stdout=raw_stdout,
        raw_stderr=result.stderr,
        exit_code=result.returncode,
        started_at=started_at,
        ended_at=ended_at,
        duration_ms=duration_ms,
    )


def _write_output_schema(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = AgentReviewOutput.model_json_schema()
    path.write_text(
        json.dumps(schema, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_output_file(path: Path) -> str:
    try:
        payload = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ReviewerError(
            "Failed to read codex structured output file",
            error_code=ErrorCode.AGENT_EXEC_FAILED,
            cause=exc,
            context={"output_file": str(path)},
        ) from exc
    if not payload.strip():
        raise ReviewerError(
            "Codex structured output file is empty",
            error_code=ErrorCode.AGENT_EXEC_FAILED,
            context={"output_file": str(path)},
        )
    return payload


def _build_codex_command(
    codex_command: str | None,
    *,
    schema_path: Path,
    output_path: Path,
) -> list[str]:
    command = (
        shlex.split(codex_command) if codex_command is not None else ["codex", "exec"]
    )
    if not command:
        raise ReviewerError(
            "Agent command is empty",
            error_code=ErrorCode.AGENT_EXEC_FAILED,
        )
    command = _set_flag_value(command, _OUTPUT_SCHEMA_FLAG, str(schema_path))
    command = _set_flag_value(command, _OUTPUT_LAST_MESSAGE_FLAG, str(output_path))
    command = _ensure_flag_value(command, _SANDBOX_FLAG, _DEFAULT_SANDBOX)
    return command


def _set_flag_value(command: list[str], flag: str, value: str) -> list[str]:
    rewritten: list[str] = []
    skip_next = False
    prefix = f"{flag}="
    for idx, token in enumerate(command):
        if skip_next:
            skip_next = False
            continue
        if token == flag:
            if idx + 1 < len(command) and not command[idx + 1].startswith("-"):
                skip_next = True
            continue
        if token.startswith(prefix):
            continue
        rewritten.append(token)
    rewritten.extend([flag, value])
    return rewritten


def _ensure_flag_value(command: list[str], flag: str, value: str) -> list[str]:
    prefix = f"{flag}="
    for idx, token in enumerate(command):
        if token.startswith(prefix):
            return command
        if token != flag:
            continue
        if idx + 1 < len(command) and not command[idx + 1].startswith("-"):
            return command
        rewritten = list(command)
        rewritten.insert(idx + 1, value)
        return rewritten
    return [*command, flag, value]


def _sanitize_command_for_error_context(command: list[str]) -> list[str]:
    sanitized = list(command)
    for idx, token in enumerate(sanitized[:-1]):
        if token in _SENSITIVE_VALUE_FLAGS:
            sanitized[idx + 1] = "[REDACTED]"
    return sanitized
