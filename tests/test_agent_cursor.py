"""Tests for cursor command execution wrapper."""

from __future__ import annotations

import subprocess

import pytest

from diffsan.contracts.errors import ErrorCode, ReviewerError
from diffsan.contracts.models import AgentConfig, AppConfig
from diffsan.core.agent_cursor import run_cursor_once


def test_run_cursor_once_uses_default_command_with_api_key(
    monkeypatch,
) -> None:
    """Default command uses cursor-agent json output and optional api key."""
    monkeypatch.setenv("CURSOR_API_KEY", "test-token")
    commands: list[list[str]] = []

    def _run(
        command: list[str],
        *,
        input: str,
        text: bool,
        capture_output: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        assert input == "prompt-text"
        assert text is True
        assert capture_output is True
        assert check is False
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='{"summary_markdown":"ok","findings":[],"meta":{"agent":"cursor"}}',
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", _run)

    attempt = run_cursor_once("prompt-text", AppConfig())

    assert attempt.exit_code == 0
    assert commands == [
        [
            "cursor-agent",
            "--print",
            "--output-format",
            "json",
            "--api-key",
            "test-token",
        ]
    ]


def test_run_cursor_once_uses_custom_cursor_command(
    monkeypatch,
) -> None:
    """Custom cursor_command is used as-is when configured."""
    commands: list[list[str]] = []

    def _run(
        command: list[str],
        *,
        input: str,
        text: bool,
        capture_output: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        assert input == "prompt-text"
        assert text is True
        assert capture_output is True
        assert check is False
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    monkeypatch.setattr(subprocess, "run", _run)

    config = AppConfig(
        agent=AgentConfig(
            cursor_command="cursor-agent --print --output-format json --model gpt-5",
        )
    )
    run_cursor_once("prompt-text", config)

    assert commands == [
        ["cursor-agent", "--print", "--output-format", "json", "--model", "gpt-5"]
    ]


def test_run_cursor_once_default_command_without_api_key(monkeypatch) -> None:
    """Default command omits api-key argument when env var is missing."""
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    commands: list[list[str]] = []

    def _run(
        command: list[str],
        *,
        input: str,
        text: bool,
        capture_output: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        assert input == "prompt-text"
        assert text is True
        assert capture_output is True
        assert check is False
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    monkeypatch.setattr(subprocess, "run", _run)

    run_cursor_once("prompt-text", AppConfig())

    assert commands == [["cursor-agent", "--print", "--output-format", "json"]]


def test_run_cursor_once_rejects_empty_custom_command() -> None:
    """Blank cursor_command fails with AGENT_EXEC_FAILED."""
    config = AppConfig(agent=AgentConfig(cursor_command=""))

    with pytest.raises(ReviewerError) as error:
        run_cursor_once("prompt-text", config)

    assert error.value.error_info.error_code == ErrorCode.AGENT_EXEC_FAILED


def test_run_cursor_once_wraps_subprocess_oserror(monkeypatch) -> None:
    """Subprocess launch OSError is normalized into ReviewerError."""

    def _boom(_command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        raise OSError("exec missing")

    monkeypatch.setattr(subprocess, "run", _boom)

    with pytest.raises(ReviewerError) as error:
        run_cursor_once("prompt-text", AppConfig())

    assert error.value.error_info.error_code == ErrorCode.AGENT_EXEC_FAILED
    assert error.value.error_info.cause is not None


def test_run_cursor_once_nonzero_exit_raises(monkeypatch) -> None:
    """Non-zero command exit raises AGENT_EXEC_FAILED with fallback message."""

    def _run(_command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            ["cursor-agent"],
            2,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", _run)

    with pytest.raises(ReviewerError) as error:
        run_cursor_once("prompt-text", AppConfig())

    assert error.value.error_info.error_code == ErrorCode.AGENT_EXEC_FAILED
    assert error.value.error_info.cause == "unknown agent error"
