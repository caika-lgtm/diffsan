"""Milestone 1 orchestration tests."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import diffsan.run as run_module
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


def test_run_milestone1_writes_pipeline_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Non-dry run writes milestone-1 artifacts and succeeds."""

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
    review = ReviewOutput(
        summary_markdown="### Summary",
        findings=[],
        meta=ReviewMeta(agent="cursor"),
    )

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

    monkeypatch.setattr(run_module, "get_diff", _get_diff)
    monkeypatch.setattr(run_module, "prepare_diff", _prepare_diff)
    monkeypatch.setattr(run_module, "compute_fingerprint", _compute_fingerprint)
    monkeypatch.setattr(run_module, "build_agent_request", _build_agent_request)
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
    assert (workdir / "review.json").exists()

    run_payload = json.loads((workdir / "run.json").read_text(encoding="utf-8"))
    assert run_payload["ok"] is True
    assert run_payload["fingerprint"]["value"] == "f" * 64
