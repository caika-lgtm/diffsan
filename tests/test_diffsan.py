"""Tests for diffsan."""

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from diffsan import __version__
from diffsan.cli import app
from diffsan.contracts.errors import ErrorCode, ReviewerError
from diffsan.run import RUN_ARTIFACT_NAME

runner = CliRunner()
ANSI_OR_CSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def test_version() -> None:
    """Test that version is defined."""
    assert __version__ is not None
    assert isinstance(__version__, str)


def test_cli_version() -> None:
    """Test CLI version command."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_cli_help() -> None:
    """Test CLI help output."""
    result = runner.invoke(app, ["--help"], color=False)
    assert result.exit_code == 0
    plain = ANSI_OR_CSI_RE.sub("", result.stdout)
    assert re.search(r"--\s*dry\s*-\s*run", plain)


def test_cli_dry_run_writes_artifacts(tmp_path: Path) -> None:
    """Dry run writes milestone-0 required artifacts."""
    workdir = tmp_path / ".diffsan"
    result = runner.invoke(
        app,
        ["--ci", "--dry-run", "--workdir", str(workdir)],
    )

    assert result.exit_code == 0
    assert "[diffsan] run.started" in result.stdout
    assert "[diffsan] config.loaded" in result.stdout
    assert "[diffsan] skip.decided" in result.stdout
    assert "[diffsan] run.finished | ok=True" in result.stdout
    assert (workdir / "events.jsonl").exists()
    run_json = workdir / RUN_ARTIFACT_NAME
    assert run_json.exists()

    payload = json.loads(run_json.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["skipped"] is False
    assert payload["error"] is None


def test_cli_failure_writes_run_json_and_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failures still persist structured run.json and return non-zero."""

    def _boom(**_: object) -> None:
        raise ReviewerError(
            "synthetic failure",
            error_code=ErrorCode.DIFF_FETCH_FAILED,
            context={"step": "test"},
        )

    import diffsan.run as run_module

    monkeypatch.setattr(run_module, "_run_pipeline", _boom)
    workdir = tmp_path / ".diffsan"

    result = runner.invoke(
        app,
        ["--ci", "--dry-run", "--workdir", str(workdir)],
    )

    assert result.exit_code == 1
    assert "[diffsan] run.started" in result.output
    assert "[diffsan] run.finished | ok=False" in result.output
    assert "[diffsan] error.raised" in result.output
    assert "error_code=DIFF_FETCH_FAILED" in result.output
    assert "message=synthetic failure" in result.output
    payload = json.loads((workdir / RUN_ARTIFACT_NAME).read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert payload["error"]["error_code"] == ErrorCode.DIFF_FETCH_FAILED


def test_cli_non_ci_failure_prints_events(tmp_path: Path) -> None:
    """Non-CI runs still surface key error events in console output."""
    workdir = tmp_path / ".diffsan"
    result = runner.invoke(app, ["--workdir", str(workdir)])

    assert result.exit_code == 1
    assert "[diffsan] run.started" in result.output
    assert "[diffsan] config.loaded" in result.output
    assert "[diffsan] error.raised" in result.output
    assert "error_code=DIFF_FETCH_FAILED" in result.output
    assert "supports CI mode only" in result.output
    assert "[diffsan] run.finished | ok=False" in result.output


def test_run_workdir_creation_failure_falls_back_to_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run() falls back to default workdir when requested workdir creation fails."""
    import diffsan.run as run_module

    original_artifact_store = run_module.ArtifactStore
    fallback_dir = tmp_path / "fallback-workdir"
    calls = 0

    def _artifact_store(workdir: str):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("cannot create workdir")
        return original_artifact_store(workdir)

    monkeypatch.setattr(run_module, "DEFAULT_WORKDIR", str(fallback_dir))
    monkeypatch.setattr(run_module, "ArtifactStore", _artifact_store)

    result = run_module.run(
        run_module.RunOptions(ci=True, dry_run=True, workdir=str(tmp_path / "bad"))
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.error_code == ErrorCode.CONFIG_PARSE_ERROR
    assert (fallback_dir / run_module.RUN_ARTIFACT_NAME).exists()
