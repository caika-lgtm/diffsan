"""Tests for codex command execution wrapper."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from diffsan.contracts.errors import ErrorCode, ReviewerError
from diffsan.contracts.models import AgentConfig, AppConfig
from diffsan.core.agent_codex import run_codex_once


def _write_output_from_command(command: list[str], payload: str) -> None:
    output_idx = command.index("--output-last-message") + 1
    output_path = Path(command[output_idx])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(payload, encoding="utf-8")


def test_run_codex_once_uses_default_command_and_reads_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Default codex command writes schema and reads structured output file."""
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
        _write_output_from_command(command, '{"summary_markdown":"ok","findings":[]}')
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _run)

    attempt = run_codex_once(
        "prompt-text",
        AppConfig(agent=AgentConfig(agent="codex")),
        workdir=tmp_path,
    )

    assert attempt.exit_code == 0
    assert attempt.raw_stdout == '{"summary_markdown":"ok","findings":[]}'
    assert attempt.raw_stderr == ""
    assert attempt.duration_ms >= 0
    assert (tmp_path / "codex-output-schema.json").exists()
    assert (tmp_path / "codex-output.json").exists()
    schema_text = (tmp_path / "codex-output-schema.json").read_text(encoding="utf-8")
    schema_payload = json.loads(schema_text)
    assert '"title": "AgentReviewOutput"' in schema_text
    assert schema_payload["additionalProperties"] is False
    assert set(schema_payload["required"]) == set(schema_payload["properties"].keys())
    finding_schema = schema_payload["$defs"]["Finding"]
    assert finding_schema["additionalProperties"] is False
    assert set(finding_schema["required"]) == set(finding_schema["properties"].keys())
    assert "finding_id" in finding_schema["required"]
    assert commands == [
        [
            "codex",
            "exec",
            "--output-schema",
            str(tmp_path / "codex-output-schema.json"),
            "--output-last-message",
            str(tmp_path / "codex-output.json"),
            "--sandbox",
            "read-only",
        ]
    ]


def test_run_codex_once_uses_custom_command_and_injects_output_flags(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Custom codex_command keeps custom flags and injects output wiring."""
    commands: list[list[str]] = []

    def _run(
        command: list[str],
        *,
        input: str,
        text: bool,
        capture_output: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        _ = input, text, capture_output, check
        commands.append(command)
        _write_output_from_command(command, '{"summary_markdown":"ok","findings":[]}')
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _run)

    config = AppConfig(
        agent=AgentConfig(
            agent="codex",
            codex_command="codex exec --model gpt-5",
        )
    )
    run_codex_once("prompt-text", config, workdir=tmp_path)

    command = commands[0]
    assert command[:2] == ["codex", "exec"]
    assert "--model" in command
    assert "gpt-5" in command
    assert "--output-schema" in command
    assert "--output-last-message" in command
    assert "--sandbox" in command
    assert "read-only" in command


def test_run_codex_once_rejects_empty_custom_command(tmp_path: Path) -> None:
    """Blank codex_command fails with AGENT_EXEC_FAILED."""
    config = AppConfig(agent=AgentConfig(agent="codex", codex_command=""))

    with pytest.raises(ReviewerError) as error:
        run_codex_once("prompt-text", config, workdir=tmp_path)

    assert error.value.error_info.error_code == ErrorCode.AGENT_EXEC_FAILED


def test_run_codex_once_nonzero_exit_raises_and_redacts_sensitive_flags(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Non-zero command exit is normalized and sensitive args are redacted."""
    config = AppConfig(
        agent=AgentConfig(
            agent="codex",
            codex_command="codex exec --api-key secret-token",
        ),
    )

    def _run(_command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            ["codex", "exec"],
            1,
            stdout="",
            stderr="failed",
        )

    monkeypatch.setattr(subprocess, "run", _run)

    with pytest.raises(ReviewerError) as error:
        run_codex_once("prompt-text", config, workdir=tmp_path)

    assert error.value.error_info.error_code == ErrorCode.AGENT_EXEC_FAILED
    assert "secret-token" not in str(error.value.error_info.context["command"])
    assert "[REDACTED]" in str(error.value.error_info.context["command"])


def test_run_codex_once_missing_output_file_raises(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Missing codex output file is treated as AGENT_EXEC_FAILED."""

    def _run(_command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["codex", "exec"], 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _run)

    with pytest.raises(ReviewerError) as error:
        run_codex_once(
            "prompt-text",
            AppConfig(agent=AgentConfig(agent="codex")),
            workdir=tmp_path,
        )

    assert error.value.error_info.error_code == ErrorCode.AGENT_EXEC_FAILED


def test_run_codex_once_empty_output_file_raises(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Empty codex output file is treated as AGENT_EXEC_FAILED."""

    def _run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        _write_output_from_command(command, "   ")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _run)

    with pytest.raises(ReviewerError) as error:
        run_codex_once(
            "prompt-text",
            AppConfig(agent=AgentConfig(agent="codex")),
            workdir=tmp_path,
        )

    assert error.value.error_info.error_code == ErrorCode.AGENT_EXEC_FAILED


def test_run_codex_once_wraps_subprocess_oserror(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Subprocess launch OSError is normalized into ReviewerError."""
    config = AppConfig(
        agent=AgentConfig(
            agent="codex",
            codex_command="codex exec --api-key secret-token",
        ),
    )

    def _boom(_command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        raise OSError("exec missing")

    monkeypatch.setattr(subprocess, "run", _boom)

    with pytest.raises(ReviewerError) as error:
        run_codex_once("prompt-text", config, workdir=tmp_path)

    assert error.value.error_info.error_code == ErrorCode.AGENT_EXEC_FAILED
    assert "secret-token" not in str(error.value.error_info.context["command"])
    assert "[REDACTED]" in str(error.value.error_info.context["command"])


def test_run_codex_once_rewrites_existing_output_flags_and_keeps_sandbox_equals(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Existing output flags are replaced, sandbox=... value is preserved."""
    commands: list[list[str]] = []
    config = AppConfig(
        agent=AgentConfig(
            agent="codex",
            codex_command=(
                "codex exec "
                "--output-schema old-schema.json "
                "--output-last-message=old-output.json "
                "--sandbox=workspace-write"
            ),
        ),
    )

    def _run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        _write_output_from_command(command, '{"summary_markdown":"ok","findings":[]}')
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _run)

    run_codex_once("prompt-text", config, workdir=tmp_path)

    command = commands[0]
    assert "--output-schema" in command
    assert str(tmp_path / "codex-output-schema.json") in command
    assert "--output-last-message" in command
    assert str(tmp_path / "codex-output.json") in command
    assert "old-schema.json" not in command
    assert not any(token.startswith("--output-last-message=") for token in command)
    assert "--sandbox=workspace-write" in command


def test_run_codex_once_keeps_existing_sandbox_positional_value(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Explicit sandbox value should not be replaced by read-only."""
    commands: list[list[str]] = []
    config = AppConfig(
        agent=AgentConfig(
            agent="codex",
            codex_command="codex exec --sandbox workspace-write",
        ),
    )

    def _run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        _write_output_from_command(command, '{"summary_markdown":"ok","findings":[]}')
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _run)

    run_codex_once("prompt-text", config, workdir=tmp_path)

    command = commands[0]
    sandbox_idx = command.index("--sandbox")
    assert command[sandbox_idx + 1] == "workspace-write"


def test_run_codex_once_inserts_default_sandbox_when_flag_has_no_value(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Bare --sandbox flag should get default read-only value inserted."""
    commands: list[list[str]] = []
    config = AppConfig(
        agent=AgentConfig(
            agent="codex",
            codex_command="codex exec --sandbox --model gpt-5",
        ),
    )

    def _run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        _write_output_from_command(command, '{"summary_markdown":"ok","findings":[]}')
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _run)

    run_codex_once("prompt-text", config, workdir=tmp_path)

    command = commands[0]
    sandbox_idx = command.index("--sandbox")
    assert command[sandbox_idx + 1] == "read-only"
    assert "--model" in command


def test_run_codex_once_handles_output_schema_flag_without_value(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A bare --output-schema flag should be replaced without dropping next flags."""
    commands: list[list[str]] = []
    config = AppConfig(
        agent=AgentConfig(
            agent="codex",
            codex_command="codex exec --output-schema --model gpt-5",
        ),
    )

    def _run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        _write_output_from_command(command, '{"summary_markdown":"ok","findings":[]}')
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _run)

    run_codex_once("prompt-text", config, workdir=tmp_path)

    command = commands[0]
    assert "--model" in command
    assert "gpt-5" in command
    assert "--output-schema" in command
    assert str(tmp_path / "codex-output-schema.json") in command
