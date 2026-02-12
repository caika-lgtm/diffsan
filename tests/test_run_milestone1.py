"""Milestone 1 orchestration tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

import diffsan.run as run_module
from diffsan.contracts.errors import ErrorCode, ReviewerError
from diffsan.contracts.models import (
    AgentConfig,
    AgentRequest,
    AgentRequestMeta,
    AgentReviewOutput,
    AppConfig,
    DiffBundle,
    DiffRef,
    DiffSource,
    Finding,
    Fingerprint,
    PreparedDiff,
    RedactionReport,
    ReviewOutput,
    TruncationReport,
)
from diffsan.core.agent_cursor import AgentAttempt
from diffsan.io.artifacts import ArtifactStore
from diffsan.io.logging import EventLogger
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


def _agent_attempt(
    *,
    raw_stdout: str,
    raw_stderr: str,
    exit_code: int,
    duration_ms: int,
) -> AgentAttempt:
    started_at = datetime.now(tz=UTC)
    ended_at = datetime.now(tz=UTC)
    return AgentAttempt(
        raw_stdout=raw_stdout,
        raw_stderr=raw_stderr,
        exit_code=exit_code,
        started_at=started_at,
        ended_at=ended_at,
        duration_ms=duration_ms,
    )


def _read_events(workdir: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (workdir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _patch_pipeline_dependencies(
    monkeypatch,
    *,
    diff_bundle: DiffBundle,
    prepared: PreparedDiff,
    gitlab_client_cls: type | None = None,
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
    monkeypatch.setattr(
        run_module,
        "GitLabClient",
        gitlab_client_cls or _FakeGitLabClient,
    )


class _FakeGitLabClient:
    def __init__(self, config) -> None:
        _ = config

    def get_mr(self):
        return SimpleNamespace(status_code=200, payload={"iid": 1}, retry_count=0)

    def create_note(self, body: str):
        _ = body
        return SimpleNamespace(note_id=101, status_code=201, retry_count=0)

    def create_discussion(self, *, body: str, position: dict[str, object]):
        _ = body, position
        return SimpleNamespace(discussion_id=202, status_code=201, retry_count=0)


def test_run_milestone1_writes_pipeline_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Non-dry run writes review and posting artifacts and succeeds."""

    diff_bundle, prepared = _fixture_diff_and_prepared()
    review = AgentReviewOutput(
        summary_markdown="### Summary",
        findings=[],
    )

    def _run_cursor_once(prompt: str, config) -> AgentAttempt:
        _ = prompt, config
        return _agent_attempt(
            raw_stdout="{}",
            raw_stderr="",
            exit_code=0,
            duration_ms=1,
        )

    def _parse_and_validate(raw: str) -> AgentReviewOutput:
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
    monkeypatch.setenv("CI_PIPELINE_ID", "777")

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
    assert (workdir / "post_plan.json").exists()
    assert (workdir / "post_results.json").exists()

    run_payload = json.loads((workdir / "run.json").read_text(encoding="utf-8"))
    review_payload = json.loads((workdir / "review.json").read_text(encoding="utf-8"))
    post_plan_payload = json.loads(
        (workdir / "post_plan.json").read_text(encoding="utf-8")
    )
    assert run_payload["ok"] is True
    assert run_payload["fingerprint"]["value"] == "f" * 64
    assert review_payload["meta"]["fingerprint"]["value"] == "f" * 64
    assert review_payload["meta"]["agent"] == "cursor"
    assert review_payload["meta"]["timings"]["duration_ms"] == 1
    assert review_payload["meta"]["token_usage"] == {}
    assert "**MR pipeline ID:** `777`" in post_plan_payload["summary_meta_collapsible"]
    post_results = json.loads(
        (workdir / "post_results.json").read_text(encoding="utf-8")
    )
    assert post_results["ok"] is True
    assert post_results["items"][0]["kind"] == "summary_note"
    assert post_results["items"][0]["gitlab_id"] == 101


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
        }
    )

    def _run_cursor_once(prompt: str, config) -> AgentAttempt:
        _ = config
        prompts.append(prompt)
        if len(prompts) == 1:
            return _agent_attempt(
                raw_stdout="not-json",
                raw_stderr="",
                exit_code=0,
                duration_ms=1,
            )
        return _agent_attempt(
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
        return _agent_attempt(
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


def test_run_milestone3_post_failure_writes_results_and_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """GitLab posting failure keeps artifacts and fails the run."""
    diff_bundle, prepared = _fixture_diff_and_prepared()

    class _FailingGitLabClient(_FakeGitLabClient):
        def create_note(self, body: str):
            _ = body
            raise ReviewerError(
                "post failed",
                error_code=ErrorCode.GITLAB_POST_FAILED,
                retryable=True,
                context={"status": 429, "retry_count": 2},
            )

    _patch_pipeline_dependencies(
        monkeypatch,
        diff_bundle=diff_bundle,
        prepared=prepared,
        gitlab_client_cls=_FailingGitLabClient,
    )

    review = AgentReviewOutput(
        summary_markdown="### Summary",
        findings=[],
    )

    def _run_cursor_once(prompt: str, config) -> AgentAttempt:
        _ = prompt, config
        return _agent_attempt(
            raw_stdout="{}",
            raw_stderr="",
            exit_code=0,
            duration_ms=1,
        )

    def _parse_and_validate(raw: str) -> AgentReviewOutput:
        _ = raw
        return review

    monkeypatch.setattr(run_module, "run_cursor_once", _run_cursor_once)
    monkeypatch.setattr(run_module, "parse_and_validate", _parse_and_validate)
    monkeypatch.setattr(run_module, "print_summary_markdown", lambda _: None)

    workdir = tmp_path / ".diffsan"
    result = run_module.run(RunOptions(ci=True, dry_run=False, workdir=str(workdir)))

    assert result.ok is False
    assert result.error is not None
    assert result.error.error_code == ErrorCode.GITLAB_POST_FAILED
    assert (workdir / "post_plan.json").exists()
    assert (workdir / "post_results.json").exists()

    post_results = json.loads(
        (workdir / "post_results.json").read_text(encoding="utf-8")
    )
    assert post_results["ok"] is False
    assert post_results["items"][0]["kind"] == "summary_note"
    assert post_results["items"][0]["http_status"] == 429
    assert post_results["items"][0]["retry_count"] == 2
    assert (
        post_results["items"][0]["error"]["error_code"] == ErrorCode.GITLAB_POST_FAILED
    )


def test_run_milestone4_get_mr_failure_writes_results_and_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """MR metadata failure should write post results and stop before posting note."""
    diff_bundle, prepared = _fixture_diff_and_prepared()

    class _FailingGetMrGitLabClient(_FakeGitLabClient):
        def get_mr(self):
            raise ReviewerError(
                "mr fetch failed",
                error_code=ErrorCode.GITLAB_FETCH_PRIOR_FAILED,
                context={"status": 404, "retry_count": 0},
            )

    _patch_pipeline_dependencies(
        monkeypatch,
        diff_bundle=diff_bundle,
        prepared=prepared,
        gitlab_client_cls=_FailingGetMrGitLabClient,
    )

    review = AgentReviewOutput(
        summary_markdown="### Summary",
        findings=[],
    )

    def _run_cursor_once(prompt: str, config) -> AgentAttempt:
        _ = prompt, config
        return _agent_attempt(
            raw_stdout="{}",
            raw_stderr="",
            exit_code=0,
            duration_ms=1,
        )

    def _parse_and_validate(raw: str) -> AgentReviewOutput:
        _ = raw
        return review

    monkeypatch.setattr(run_module, "run_cursor_once", _run_cursor_once)
    monkeypatch.setattr(run_module, "parse_and_validate", _parse_and_validate)
    monkeypatch.setattr(run_module, "print_summary_markdown", lambda _: None)

    workdir = tmp_path / ".diffsan"
    result = run_module.run(RunOptions(ci=True, dry_run=False, workdir=str(workdir)))

    assert result.ok is False
    assert result.error is not None
    assert result.error.error_code == ErrorCode.GITLAB_FETCH_PRIOR_FAILED
    assert (workdir / "post_results.json").exists()

    post_results = json.loads(
        (workdir / "post_results.json").read_text(encoding="utf-8")
    )
    assert post_results["ok"] is False
    assert post_results["items"][0]["kind"] == "summary_note"
    assert post_results["items"][0]["ok"] is False
    assert post_results["items"][0]["http_status"] == 404
    assert (
        post_results["items"][0]["error"]["error_code"]
        == ErrorCode.GITLAB_FETCH_PRIOR_FAILED
    )

    events = _read_events(workdir)
    summary_events = [
        item for item in events if item.get("event") == "gitlab.post.summary"
    ]
    assert len(summary_events) == 1
    assert cast("dict[str, object]", summary_events[0]["data"])["ok"] is False


def test_run_milestone4_discussion_failure_is_partial_and_nonzero(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Summary still posts when discussion fails; run exits non-zero."""
    diff_bundle = DiffBundle(
        source=DiffSource(
            ref=DiffRef(
                target_branch="main",
                base_sha="a" * 40,
                head_sha="b" * 40,
            )
        ),
        raw_diff=("diff --git a/a.py b/a.py\n@@ -1 +1,2 @@\n line1\n+line2\n"),
        files=[],
    )
    prepared = PreparedDiff(
        prepared_diff=diff_bundle.raw_diff,
        truncation=TruncationReport(),
        redaction=RedactionReport(enabled=True, found=False),
        ignored_paths=[],
        included_paths=["a.py"],
    )

    class _PartiallyFailingGitLabClient(_FakeGitLabClient):
        def get_mr(self):
            return SimpleNamespace(
                status_code=200,
                payload={
                    "iid": 1,
                    "diff_refs": {
                        "base_sha": "a" * 40,
                        "head_sha": "b" * 40,
                        "start_sha": "a" * 40,
                    },
                },
                retry_count=0,
            )

        def create_discussion(self, *, body: str, position: dict[str, object]):
            _ = body, position
            raise ReviewerError(
                "invalid position",
                error_code=ErrorCode.GITLAB_POSITION_INVALID,
                context={"status": 400, "retry_count": 0},
            )

    review = AgentReviewOutput(
        summary_markdown="### Summary",
        findings=[
            Finding(
                severity="high",
                category="security",
                path="a.py",
                line_start=2,
                line_end=2,
                body_markdown="Issue on added line.",
            )
        ],
    )

    def _run_cursor_once(prompt: str, config) -> AgentAttempt:
        _ = prompt, config
        return _agent_attempt(
            raw_stdout="{}",
            raw_stderr="",
            exit_code=0,
            duration_ms=1,
        )

    def _parse_and_validate(raw: str) -> AgentReviewOutput:
        _ = raw
        return review

    _patch_pipeline_dependencies(
        monkeypatch,
        diff_bundle=diff_bundle,
        prepared=prepared,
        gitlab_client_cls=_PartiallyFailingGitLabClient,
    )
    monkeypatch.setattr(run_module, "run_cursor_once", _run_cursor_once)
    monkeypatch.setattr(run_module, "parse_and_validate", _parse_and_validate)
    monkeypatch.setattr(run_module, "print_summary_markdown", lambda _: None)

    workdir = tmp_path / ".diffsan"
    result = run_module.run(RunOptions(ci=True, dry_run=False, workdir=str(workdir)))

    assert result.ok is False
    assert result.error is not None
    assert result.error.error_code == ErrorCode.GITLAB_POST_FAILED

    post_plan = json.loads((workdir / "post_plan.json").read_text(encoding="utf-8"))
    assert len(post_plan["discussions"]) == 1
    assert post_plan["discussions"][0]["position"]["new_line"] == 2

    post_results = json.loads(
        (workdir / "post_results.json").read_text(encoding="utf-8")
    )
    assert post_results["ok"] is False
    assert post_results["items"][0]["kind"] == "summary_note"
    assert post_results["items"][0]["ok"] is True
    assert post_results["items"][1]["kind"] == "discussion"
    assert post_results["items"][1]["ok"] is False
    assert (
        post_results["items"][1]["error"]["error_code"]
        == ErrorCode.GITLAB_POSITION_INVALID
    )


def test_run_milestone4_discussion_success_emits_event_payload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Discussion success should be recorded in post results and events."""
    diff_bundle = DiffBundle(
        source=DiffSource(
            ref=DiffRef(
                target_branch="main",
                base_sha="a" * 40,
                head_sha="b" * 40,
            )
        ),
        raw_diff=("diff --git a/a.py b/a.py\n@@ -1 +1,2 @@\n line1\n+line2\n"),
        files=[],
    )
    prepared = PreparedDiff(
        prepared_diff=diff_bundle.raw_diff,
        truncation=TruncationReport(),
        redaction=RedactionReport(enabled=True, found=False),
        ignored_paths=[],
        included_paths=["a.py"],
    )

    class _DiscussionGitLabClient(_FakeGitLabClient):
        def get_mr(self):
            return SimpleNamespace(
                status_code=200,
                payload={
                    "iid": 1,
                    "diff_refs": {
                        "base_sha": "a" * 40,
                        "head_sha": "b" * 40,
                        "start_sha": "a" * 40,
                    },
                },
                retry_count=0,
            )

    review = AgentReviewOutput(
        summary_markdown="### Summary",
        findings=[
            Finding(
                severity="high",
                category="security",
                path="a.py",
                line_start=2,
                line_end=2,
                body_markdown="Issue on added line.",
            )
        ],
    )

    def _run_cursor_once(prompt: str, config) -> AgentAttempt:
        _ = prompt, config
        return _agent_attempt(
            raw_stdout="{}",
            raw_stderr="",
            exit_code=0,
            duration_ms=1,
        )

    def _parse_and_validate(raw: str) -> AgentReviewOutput:
        _ = raw
        return review

    _patch_pipeline_dependencies(
        monkeypatch,
        diff_bundle=diff_bundle,
        prepared=prepared,
        gitlab_client_cls=_DiscussionGitLabClient,
    )
    monkeypatch.setattr(run_module, "run_cursor_once", _run_cursor_once)
    monkeypatch.setattr(run_module, "parse_and_validate", _parse_and_validate)
    monkeypatch.setattr(run_module, "print_summary_markdown", lambda _: None)

    workdir = tmp_path / ".diffsan"
    result = run_module.run(RunOptions(ci=True, dry_run=False, workdir=str(workdir)))

    assert result.ok is True
    post_results = json.loads(
        (workdir / "post_results.json").read_text(encoding="utf-8")
    )
    assert post_results["ok"] is True
    assert post_results["items"][1]["kind"] == "discussion"
    assert post_results["items"][1]["ok"] is True
    assert post_results["items"][1]["gitlab_id"] == 202

    events = _read_events(workdir)
    discussion_events = [
        item for item in events if item.get("event") == "gitlab.post.discussion"
    ]
    assert len(discussion_events) == 1
    payload = cast("dict[str, object]", discussion_events[0]["data"])
    assert payload["ok"] is True
    assert payload["path"] == "a.py"
    assert payload["line"] == 2
    assert payload["http_status"] == 201
    assert payload["id"] == 202
    assert payload["retry"] == 0


def test_run_milestone2_retries_passthrough_non_output_invalid_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Non-AGENT_OUTPUT_INVALID parser errors are raised immediately."""
    artifacts = ArtifactStore(tmp_path / ".diffsan")
    events = EventLogger(artifacts.path("events.jsonl"))
    config = AppConfig(agent=AgentConfig(max_json_retries=3))

    def _run_cursor_once(prompt: str, cfg: AppConfig) -> AgentAttempt:
        _ = prompt, cfg
        return _agent_attempt(
            raw_stdout="{}",
            raw_stderr="",
            exit_code=0,
            duration_ms=1,
        )

    def _parse_and_validate(raw: str) -> AgentReviewOutput:
        _ = raw
        raise run_module.ReviewerError(
            "parser boom",
            error_code=ErrorCode.AGENT_EXEC_FAILED,
        )

    monkeypatch.setattr(run_module, "run_cursor_once", _run_cursor_once)
    monkeypatch.setattr(run_module, "parse_and_validate", _parse_and_validate)

    with pytest.raises(run_module.ReviewerError) as error:
        run_module._run_agent_with_retries(
            request_prompt="prompt",
            config=config,
            artifacts=artifacts,
            events=events,
        )

    assert error.value.error_info.error_code == ErrorCode.AGENT_EXEC_FAILED


def test_run_milestone2_writes_stderr_artifacts_on_success(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Successful parse with stderr writes canonical and per-attempt stderr files."""
    artifacts = ArtifactStore(tmp_path / ".diffsan")
    events = EventLogger(artifacts.path("events.jsonl"))
    config = AppConfig(agent=AgentConfig(max_json_retries=1))
    review = AgentReviewOutput(
        summary_markdown="ok",
        findings=[],
    )

    def _run_cursor_once(prompt: str, cfg: AppConfig) -> AgentAttempt:
        _ = prompt, cfg
        return _agent_attempt(
            raw_stdout="{}",
            raw_stderr="stderr-log",
            exit_code=0,
            duration_ms=1,
        )

    def _parse_and_validate(raw: str) -> AgentReviewOutput:
        _ = raw
        return review

    monkeypatch.setattr(run_module, "run_cursor_once", _run_cursor_once)
    monkeypatch.setattr(run_module, "parse_and_validate", _parse_and_validate)

    result = run_module._run_agent_with_retries(
        request_prompt="prompt",
        config=config,
        artifacts=artifacts,
        events=events,
    )

    assert result.summary_markdown == "ok"
    assert result.attempt.duration_ms == 1
    assert (artifacts.path("agent.stderr.attempt1.txt")).read_text(
        encoding="utf-8"
    ) == ("stderr-log")
    assert (artifacts.path("agent.stderr.txt")).read_text(encoding="utf-8") == (
        "stderr-log"
    )


def test_run_milestone2_writes_stderr_artifact_on_retry_exhaustion(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Retry exhaustion still writes canonical stderr from the last attempt."""
    artifacts = ArtifactStore(tmp_path / ".diffsan")
    events = EventLogger(artifacts.path("events.jsonl"))
    config = AppConfig(agent=AgentConfig(max_json_retries=1))

    def _run_cursor_once(prompt: str, cfg: AppConfig) -> AgentAttempt:
        _ = prompt, cfg
        return _agent_attempt(
            raw_stdout="not-json",
            raw_stderr="stderr-last",
            exit_code=0,
            duration_ms=1,
        )

    monkeypatch.setattr(run_module, "run_cursor_once", _run_cursor_once)

    with pytest.raises(run_module.ReviewerError) as error:
        run_module._run_agent_with_retries(
            request_prompt="prompt",
            config=config,
            artifacts=artifacts,
            events=events,
        )

    assert error.value.error_info.error_code == ErrorCode.AGENT_OUTPUT_INVALID
    assert (artifacts.path("agent.stderr.attempt1.txt")).read_text(
        encoding="utf-8"
    ) == ("stderr-last")
    assert (artifacts.path("agent.stderr.txt")).read_text(encoding="utf-8") == (
        "stderr-last"
    )
