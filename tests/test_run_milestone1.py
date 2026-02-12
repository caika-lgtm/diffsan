"""Milestone 1 orchestration tests."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import diffsan.run as run_module
from diffsan.contracts.errors import ErrorCode
from diffsan.contracts.models import (
    AgentRequest,
    AgentRequestMeta,
    DiffBundle,
    DiffRef,
    DiffSource,
    Fingerprint,
    PreparedDiff,
    RedactionReport,
    ReviewMeta,
    ReviewOutput,
    TruncationReport,
)
from diffsan.core.agent_cursor import AgentAttempt
from diffsan.run import RunOptions

if TYPE_CHECKING:
    from pathlib import Path


def _fixture_diff_and_prepared() -> tuple[DiffBundle, PreparedDiff]:
    diff_bundle = DiffBundle(
        source=DiffSource(ref=DiffRef(target_branch="main", head_sha="deadbeef")),
        raw_diff="diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-a\n+b\n",
        files=[],
    )
    prepared = PreparedDiff(
        prepared_diff=diff_bundle.raw_diff,
        truncation=TruncationReport(),
        redaction=RedactionReport(enabled=True, found=False),
        ignored_paths=[],
        included_paths=["a.py"],
    )
    return diff_bundle, prepared


def _patch_pipeline_dependencies(
    monkeypatch,
    *,
    diff_bundle: DiffBundle,
    prepared: PreparedDiff,
) -> None:
    def _get_diff(*, ci: bool) -> DiffBundle:
        _ = ci
        return diff_bundle

    def _prepare_diff(diff: DiffBundle, config) -> PreparedDiff:
        _ = diff, config
        return prepared

    def _compute_fingerprint(raw_diff: str) -> Fingerprint:
        _ = raw_diff
        return Fingerprint(value="f" * 64)

    def _build_agent_request(
        *,
        config,
        prepared: PreparedDiff,
        fingerprint: Fingerprint,
    ) -> AgentRequest:
        _ = config, prepared
        return AgentRequest(
            prompt="prompt",
            meta=AgentRequestMeta(fingerprint=fingerprint),
        )

    monkeypatch.setattr(run_module, "get_diff", _get_diff)
    monkeypatch.setattr(run_module, "prepare_diff", _prepare_diff)
    monkeypatch.setattr(run_module, "compute_fingerprint", _compute_fingerprint)
    monkeypatch.setattr(run_module, "build_agent_request", _build_agent_request)


def test_run_milestone1_writes_pipeline_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Non-dry run writes milestone-1 artifacts and succeeds."""

    diff_bundle, prepared = _fixture_diff_and_prepared()
    review = ReviewOutput(
        summary_markdown="### Summary",
        findings=[],
        meta=ReviewMeta(agent="cursor"),
    )

    def _run_cursor_once(prompt: str, config) -> AgentAttempt:
        _ = prompt, config
        return AgentAttempt(
            raw_stdout="{}",
            raw_stderr="",
            exit_code=0,
            duration_ms=1,
        )

    def _parse_and_validate(raw: str) -> ReviewOutput:
        _ = raw
        return review

    def _print_summary_markdown(review: ReviewOutput) -> None:
        _ = review

    _patch_pipeline_dependencies(
        monkeypatch,
        diff_bundle=diff_bundle,
        prepared=prepared,
    )
    monkeypatch.setattr(run_module, "run_cursor_once", _run_cursor_once)
    monkeypatch.setattr(run_module, "parse_and_validate", _parse_and_validate)
    monkeypatch.setattr(run_module, "print_summary_markdown", _print_summary_markdown)

    workdir = tmp_path / ".diffsan"
    result = run_module.run(RunOptions(ci=True, dry_run=False, workdir=str(workdir)))

    assert result.ok is True
    assert result.fingerprint is not None

    assert (workdir / "events.jsonl").exists()
    assert (workdir / "run.json").exists()
    assert (workdir / "diff.raw.patch").exists()
    assert (workdir / "diff.prepared.patch").exists()
    assert (workdir / "truncation.json").exists()
    assert (workdir / "redaction.json").exists()
    assert (workdir / "prompt.txt").exists()
    assert (workdir / "agent.raw.txt").exists()
    assert (workdir / "agent.raw.attempt1.txt").exists()
    assert (workdir / "review.json").exists()

    run_payload = json.loads((workdir / "run.json").read_text(encoding="utf-8"))
    assert run_payload["ok"] is True
    assert run_payload["fingerprint"]["value"] == "f" * 64


def test_run_milestone2_retries_invalid_then_succeeds(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Retry loop repairs invalid first output and succeeds on second attempt."""
    diff_bundle, prepared = _fixture_diff_and_prepared()
    _patch_pipeline_dependencies(
        monkeypatch,
        diff_bundle=diff_bundle,
        prepared=prepared,
    )

    prompts: list[str] = []
    valid_payload = json.dumps(
        {
            "summary_markdown": "### Repaired summary",
            "findings": [],
            "meta": {"agent": "cursor", "token_usage": {}, "truncated": False},
        }
    )

    def _run_cursor_once(prompt: str, config) -> AgentAttempt:
        _ = config
        prompts.append(prompt)
        if len(prompts) == 1:
            return AgentAttempt(
                raw_stdout="not-json",
                raw_stderr="",
                exit_code=0,
                duration_ms=1,
            )
        return AgentAttempt(
            raw_stdout=valid_payload,
            raw_stderr="",
            exit_code=0,
            duration_ms=2,
        )

    def _print_summary_markdown(review: ReviewOutput) -> None:
        _ = review

    monkeypatch.setattr(run_module, "run_cursor_once", _run_cursor_once)
    monkeypatch.setattr(run_module, "print_summary_markdown", _print_summary_markdown)

    workdir = tmp_path / ".diffsan"
    result = run_module.run(RunOptions(ci=True, dry_run=False, workdir=str(workdir)))

    assert result.ok is True
    assert len(prompts) == 2
    assert "Validation error summary:" in prompts[1]
    assert "Return ONLY a corrected JSON object" in prompts[1]
    assert (workdir / "agent.raw.attempt1.txt").exists()
    assert (workdir / "agent.raw.attempt2.txt").exists()
    assert (workdir / "agent.raw.txt").read_text(encoding="utf-8") == valid_payload
    run_payload = json.loads((workdir / "run.json").read_text(encoding="utf-8"))
    assert run_payload["ok"] is True


def test_run_milestone2_retry_exhaustion_sets_agent_output_invalid(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Retry exhaustion fails the run with AGENT_OUTPUT_INVALID."""
    diff_bundle, prepared = _fixture_diff_and_prepared()
    _patch_pipeline_dependencies(
        monkeypatch,
        diff_bundle=diff_bundle,
        prepared=prepared,
    )

    call_count = 0

    def _run_cursor_once(prompt: str, config) -> AgentAttempt:
        nonlocal call_count
        _ = prompt, config
        call_count += 1
        return AgentAttempt(
            raw_stdout="not-json",
            raw_stderr="",
            exit_code=0,
            duration_ms=1,
        )

    def _print_summary_markdown(review: ReviewOutput) -> None:
        _ = review

    monkeypatch.setattr(run_module, "run_cursor_once", _run_cursor_once)
    monkeypatch.setattr(run_module, "print_summary_markdown", _print_summary_markdown)

    workdir = tmp_path / ".diffsan"
    result = run_module.run(RunOptions(ci=True, dry_run=False, workdir=str(workdir)))

    assert call_count == 3
    assert result.ok is False
    assert result.error is not None
    assert result.error.error_code == ErrorCode.AGENT_OUTPUT_INVALID
    assert result.error.context["attempts"] == 3
    assert (workdir / "agent.raw.attempt1.txt").exists()
    assert (workdir / "agent.raw.attempt2.txt").exists()
    assert (workdir / "agent.raw.attempt3.txt").exists()

    run_payload = json.loads((workdir / "run.json").read_text(encoding="utf-8"))
    assert run_payload["ok"] is False
    assert run_payload["error"]["error_code"] == ErrorCode.AGENT_OUTPUT_INVALID
