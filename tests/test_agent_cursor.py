"""Tests for cursor command execution wrapper."""

from __future__ import annotations

import subprocess

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
