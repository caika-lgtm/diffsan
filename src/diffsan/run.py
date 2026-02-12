"""Top-level run harness for diffsan."""

from __future__ import annotations

import os
from dataclasses import dataclass
from time import perf_counter
from typing import Final, cast

from diffsan import __version__
from diffsan.contracts.errors import ErrorCode, ErrorInfo, ReviewerError
from diffsan.contracts.events import EventLevel, EventName
from diffsan.contracts.models import (
    AppConfig,
    ArtifactPointers,
    DiffRef,
    Finding,
    Fingerprint,
    ModeConfig,
    PostResultItem,
    PostResults,
    ReviewMeta,
    ReviewOutput,
    RunResult,
    SkipReason,
    TimingMeta,
    TruncationReport,
)
from diffsan.core.agent_cursor import AgentAttempt, run_cursor_once
from diffsan.core.diff_provider import get_diff
from diffsan.core.fingerprint import compute_fingerprint
from diffsan.core.format import (
    build_post_plan,
    build_summary_note_body,
    print_summary_markdown,
)
from diffsan.core.gitlab import GitLabClient
from diffsan.core.parse_validate import parse_and_validate
from diffsan.core.preprocess import prepare_diff
from diffsan.core.prior import (
    build_embedded_prior_digest,
    encode_fingerprint_marker,
    encode_prior_digest_marker,
    get_prior_digest,
)
from diffsan.core.prompt import build_agent_request, build_json_repair_prompt
from diffsan.core.skip import decide_skip
from diffsan.io.artifacts import ArtifactStore
from diffsan.io.logging import EventLogger

DEFAULT_WORKDIR: Final[str] = ".diffsan"
RUN_ARTIFACT_NAME: Final[str] = "run.json"
EVENTS_ARTIFACT_NAME: Final[str] = "events.jsonl"
DIFF_RAW_ARTIFACT_NAME: Final[str] = "diff.raw.patch"
DIFF_PREPARED_ARTIFACT_NAME: Final[str] = "diff.prepared.patch"
TRUNCATION_ARTIFACT_NAME: Final[str] = "truncation.json"
REDACTION_ARTIFACT_NAME: Final[str] = "redaction.json"
PRIOR_DIGEST_ARTIFACT_NAME: Final[str] = "prior_digest.json"
PROMPT_ARTIFACT_NAME: Final[str] = "prompt.txt"
RAW_OUTPUT_ARTIFACT_NAME: Final[str] = "agent.raw.txt"
RAW_STDERR_ARTIFACT_NAME: Final[str] = "agent.stderr.txt"
RAW_OUTPUT_ATTEMPT_ARTIFACT_TEMPLATE: Final[str] = "agent.raw.attempt{attempt}.txt"
RAW_STDERR_ATTEMPT_ARTIFACT_TEMPLATE: Final[str] = "agent.stderr.attempt{attempt}.txt"
REVIEW_ARTIFACT_NAME: Final[str] = "review.json"
POST_PLAN_ARTIFACT_NAME: Final[str] = "post_plan.json"
POST_RESULTS_ARTIFACT_NAME: Final[str] = "post_results.json"


@dataclass(frozen=True, slots=True)
class RunOptions:
    """CLI-provided run options."""

    ci: bool = False
    dry_run: bool = False
    workdir: str = DEFAULT_WORKDIR
    note_timezone: str = "SGT"


@dataclass(frozen=True, slots=True)
class PipelineOutcome:
    """Data returned from one pipeline execution."""

    skipped: bool = False
    fingerprint: Fingerprint | None = None
    skip_reasons: tuple[SkipReason, ...] = ()


@dataclass(frozen=True, slots=True)
class ValidatedAgentOutput:
    """Validated agent-owned review fields and the source attempt timing."""

    summary_markdown: str
    findings: list[Finding]
    attempt: AgentAttempt


def run(options: RunOptions) -> RunResult:
    """Execute one diffsan run and always write `run.json`."""
    try:
        artifacts = ArtifactStore(options.workdir)
    except OSError as exc:
        fallback = ArtifactStore(DEFAULT_WORKDIR)
        fallback_events = EventLogger(fallback.path(EVENTS_ARTIFACT_NAME), echo=True)
        failure = RunResult(
            ok=False,
            skipped=False,
            error=ErrorInfo(
                error_code=ErrorCode.CONFIG_PARSE_ERROR,
                message=f"Failed to create workdir: {options.workdir}",
                retryable=False,
                cause=f"{exc.__class__.__name__}: {exc}",
            ),
            artifacts=ArtifactPointers(workdir=str(fallback.workdir)),
        )
        fallback_events.emit(
            EventName.ERROR_RAISED,
            level=EventLevel.ERROR,
            data=failure.error.model_dump(mode="json") if failure.error else {},
        )
        fallback_events.emit(
            EventName.RUN_FINISHED,
            data={"ok": False, "skipped": False, "duration_ms": 0},
        )
        fallback.write_json(RUN_ARTIFACT_NAME, failure)
        return failure

    events = EventLogger(artifacts.path(EVENTS_ARTIFACT_NAME), echo=True)
    config = AppConfig(mode=ModeConfig(ci=options.ci))

    run_result = RunResult(
        ok=False,
        skipped=False,
        artifacts=ArtifactPointers(workdir=str(artifacts.workdir)),
    )
    start = perf_counter()

    events.emit(
        EventName.RUN_STARTED,
        data={
            "version": __version__,
            "ci": options.ci,
            "workdir": str(artifacts.workdir),
        },
    )
    events.emit(
        EventName.CONFIG_LOADED,
        data={
            "ci": config.mode.ci,
            "agent": config.agent.agent,
            "verbosity": config.agent.verbosity,
        },
    )

    try:
        outcome = _run_pipeline(
            options=options,
            _config=config,
            _artifacts=artifacts,
            events=events,
        )
        run_result.ok = True
        run_result.skipped = outcome.skipped
        run_result.fingerprint = outcome.fingerprint
        run_result.skip_reasons = list(outcome.skip_reasons)
    except ReviewerError as exc:
        run_result.error = exc.error_info
        events.emit(
            EventName.ERROR_RAISED,
            level=EventLevel.ERROR,
            data=exc.error_info.model_dump(mode="json"),
        )
    except Exception as exc:  # pragma: no cover - defensive safety net
        normalized = ErrorInfo(
            error_code=ErrorCode.FORMAT_FAILED,
            message="Unhandled runtime failure",
            retryable=False,
            cause=f"{exc.__class__.__name__}: {exc}",
        )
        run_result.error = normalized
        events.emit(
            EventName.ERROR_RAISED,
            level=EventLevel.ERROR,
            data=normalized.model_dump(mode="json"),
        )
    finally:
        duration_ms = int((perf_counter() - start) * 1000)
        events.emit(
            EventName.RUN_FINISHED,
            data={
                "ok": run_result.ok,
                "skipped": run_result.skipped,
                "duration_ms": duration_ms,
            },
        )
        artifacts.write_json(RUN_ARTIFACT_NAME, run_result)

    return run_result


def _run_pipeline(
    *,
    options: RunOptions,
    _config: AppConfig,
    _artifacts: ArtifactStore,
    events: EventLogger,
) -> PipelineOutcome:
    """Milestone-5 pipeline with skip rules and prior digest support."""
    if options.dry_run:
        events.emit(
            EventName.SKIP_DECIDED,
            data={"should_skip": False, "reasons": [], "fingerprint": None},
        )
        return PipelineOutcome(skipped=False, fingerprint=None)

    diff_bundle = get_diff(ci=_config.mode.ci)
    _artifacts.write_text(DIFF_RAW_ARTIFACT_NAME, diff_bundle.raw_diff)
    events.emit(
        EventName.DIFF_FETCHED,
        data={
            "chars": len(diff_bundle.raw_diff),
            "files": len(diff_bundle.files),
            "base_sha": diff_bundle.source.ref.base_sha,
            "head_sha": diff_bundle.source.ref.head_sha,
        },
    )

    prepared = prepare_diff(diff_bundle, _config)
    _artifacts.write_text(DIFF_PREPARED_ARTIFACT_NAME, prepared.prepared_diff)
    _artifacts.write_json(TRUNCATION_ARTIFACT_NAME, prepared.truncation)
    _artifacts.write_json(REDACTION_ARTIFACT_NAME, prepared.redaction)
    events.emit(
        EventName.DIFF_PREPARED,
        data={
            "final_chars": len(prepared.prepared_diff),
            "truncated": prepared.truncation.truncated,
            "redaction_found": prepared.redaction.found,
        },
    )

    fingerprint = compute_fingerprint(diff_bundle.raw_diff)
    gitlab_client: GitLabClient | None = None
    mr_payload: dict[str, object] | None = None
    prior_digest = None
    if _config.mode.ci and _config.gitlab.enabled:
        gitlab_client = GitLabClient(_config.gitlab)
        try:
            mr_result = gitlab_client.get_mr()
        except ReviewerError:
            mr_payload = None
        else:
            mr_payload = _extract_mr_payload(mr_result.payload)
            if mr_payload is not None:
                try:
                    prior_digest = get_prior_digest(
                        client=gitlab_client,
                        summary_note_tag=_config.gitlab.summary_note_tag,
                    )
                except ReviewerError:
                    prior_digest = None

    _artifacts.write_json(
        PRIOR_DIGEST_ARTIFACT_NAME,
        prior_digest if prior_digest is not None else {},
    )
    skip_decision = decide_skip(
        config=_config,
        mr_payload=mr_payload,
        fingerprint=fingerprint,
        prior_digest=prior_digest,
    )
    events.emit(
        EventName.SKIP_DECIDED,
        data={
            "should_skip": skip_decision.should_skip,
            "reasons": [
                reason.model_dump(mode="json") for reason in skip_decision.reasons
            ],
            "fingerprint": f"{fingerprint.algo}:{fingerprint.value}",
        },
    )
    if skip_decision.should_skip:
        for reason in skip_decision.reasons:
            print(f"Skipping diffsan review: {reason.message}")
        return PipelineOutcome(
            skipped=True,
            fingerprint=fingerprint,
            skip_reasons=tuple(skip_decision.reasons),
        )

    request = build_agent_request(
        config=_config,
        prepared=prepared,
        fingerprint=fingerprint,
        prior_digest=prior_digest,
    )
    _artifacts.write_text(PROMPT_ARTIFACT_NAME, request.prompt)
    events.emit(
        EventName.PROMPT_WRITTEN,
        data={"path": PROMPT_ARTIFACT_NAME, "chars": len(request.prompt)},
    )

    agent_review = _run_agent_with_retries(
        request_prompt=request.prompt,
        config=_config,
        artifacts=_artifacts,
        events=events,
    )
    review = ReviewOutput(
        summary_markdown=agent_review.summary_markdown,
        findings=agent_review.findings,
        meta=ReviewMeta(
            fingerprint=fingerprint,
            agent=_config.agent.agent,
            timings=TimingMeta(
                started_at=agent_review.attempt.started_at,
                ended_at=agent_review.attempt.ended_at,
                duration_ms=agent_review.attempt.duration_ms,
            ),
            token_usage={},
            truncated=prepared.truncation.truncated,
            redaction_found=prepared.redaction.found,
        ),
    )
    _artifacts.write_json(REVIEW_ARTIFACT_NAME, review)
    events.emit(
        EventName.REVIEW_VALIDATED,
        data={
            "findings": len(review.findings),
            "truncated": review.meta.truncated,
        },
    )

    print_summary_markdown(review)
    if _config.mode.ci and _config.gitlab.enabled:
        _post_summary_note_to_gitlab(
            config=_config,
            artifacts=_artifacts,
            events=events,
            client=gitlab_client,
            mr_payload=mr_payload,
            review=review,
            fingerprint=fingerprint,
            truncation=prepared.truncation,
            prepared_diff=prepared.prepared_diff,
            diff_ref=diff_bundle.source.ref,
            note_timezone=options.note_timezone,
        )

    return PipelineOutcome(skipped=False, fingerprint=fingerprint, skip_reasons=())


def _run_agent_with_retries(
    *,
    request_prompt: str,
    config: AppConfig,
    artifacts: ArtifactStore,
    events: EventLogger,
) -> ValidatedAgentOutput:
    max_attempts = max(1, config.agent.max_json_retries)
    prompt = request_prompt
    last_invalid_error: ReviewerError | None = None
    last_attempt: AgentAttempt | None = None

    for attempt_number in range(1, max_attempts + 1):
        attempt = run_cursor_once(prompt, config)
        last_attempt = attempt
        _write_attempt_artifacts(
            artifacts=artifacts,
            attempt_number=attempt_number,
            attempt=attempt,
        )
        events.emit(
            EventName.AGENT_ATTEMPT,
            data={
                "attempt": attempt_number,
                "exit_code": attempt.exit_code,
                "duration_ms": attempt.duration_ms,
            },
        )

        try:
            review = parse_and_validate(attempt.raw_stdout)
        except ReviewerError as exc:
            if exc.error_info.error_code != ErrorCode.AGENT_OUTPUT_INVALID:
                raise
            last_invalid_error = exc
            if attempt_number >= max_attempts:
                break
            prompt = build_json_repair_prompt(
                config=config,
                validation_error=exc,
                previous_output=attempt.raw_stdout,
            )
            continue

        artifacts.write_text(RAW_OUTPUT_ARTIFACT_NAME, attempt.raw_stdout)
        if attempt.raw_stderr:
            artifacts.write_text(RAW_STDERR_ARTIFACT_NAME, attempt.raw_stderr)
        return ValidatedAgentOutput(
            summary_markdown=review.summary_markdown,
            findings=review.findings,
            attempt=attempt,
        )

    if last_attempt is not None:
        artifacts.write_text(RAW_OUTPUT_ARTIFACT_NAME, last_attempt.raw_stdout)
        if last_attempt.raw_stderr:
            artifacts.write_text(RAW_STDERR_ARTIFACT_NAME, last_attempt.raw_stderr)

    if last_invalid_error is None:  # pragma: no cover - defensive guard
        raise ReviewerError(
            "Agent output failed without parse/validation details",
            error_code=ErrorCode.AGENT_OUTPUT_INVALID,
            context={"attempts": max_attempts, "agent": config.agent.agent},
        )

    raise ReviewerError(
        f"Failed to obtain valid JSON output after {max_attempts} attempts",
        error_code=ErrorCode.AGENT_OUTPUT_INVALID,
        context={
            "attempts": max_attempts,
            "agent": config.agent.agent,
            "last_error": last_invalid_error.error_info.message,
        },
        cause=(
            last_invalid_error.error_info.cause or last_invalid_error.error_info.message
        ),
    )


def _write_attempt_artifacts(
    *,
    artifacts: ArtifactStore,
    attempt_number: int,
    attempt: AgentAttempt,
) -> None:
    artifacts.write_text(
        RAW_OUTPUT_ATTEMPT_ARTIFACT_TEMPLATE.format(attempt=attempt_number),
        attempt.raw_stdout,
    )
    if attempt.raw_stderr:
        artifacts.write_text(
            RAW_STDERR_ATTEMPT_ARTIFACT_TEMPLATE.format(attempt=attempt_number),
            attempt.raw_stderr,
        )


def _post_summary_note_to_gitlab(
    *,
    config: AppConfig,
    artifacts: ArtifactStore,
    events: EventLogger,
    client: GitLabClient | None,
    mr_payload: dict[str, object] | None,
    review: ReviewOutput,
    fingerprint: Fingerprint,
    truncation: TruncationReport,
    prepared_diff: str,
    diff_ref: DiffRef,
    note_timezone: str,
) -> None:
    resolved_client = client or GitLabClient(config.gitlab)
    resolved_mr_payload = mr_payload
    if resolved_mr_payload is None:
        try:
            mr_result = resolved_client.get_mr()
        except ReviewerError as exc:
            retry_count = _extract_retry_count(exc)
            http_status = _extract_http_status(exc)
            post_results = PostResults(
                ok=False,
                items=[
                    PostResultItem(
                        kind="summary_note",
                        ok=False,
                        http_status=http_status,
                        retry_count=retry_count,
                        error=exc.error_info,
                    )
                ],
            )
            artifacts.write_json(POST_RESULTS_ARTIFACT_NAME, post_results)
            events.emit(
                EventName.GITLAB_POST_SUMMARY,
                level=EventLevel.ERROR,
                data={
                    "ok": False,
                    "http_status": http_status,
                    "retry": retry_count,
                },
            )
            raise
        resolved_mr_payload = _extract_mr_payload(mr_result.payload) or {}

    mr_diff_refs = _extract_mr_diff_refs(resolved_mr_payload)
    post_plan = build_post_plan(
        review=review,
        config=config,
        fallback_fingerprint=fingerprint,
        note_timezone=note_timezone,
        pipeline_id=os.getenv("CI_PIPELINE_ID"),
        prepared_diff=prepared_diff,
        diff_ref=diff_ref,
        mr_diff_refs=mr_diff_refs,
    )
    artifacts.write_json(POST_PLAN_ARTIFACT_NAME, post_plan)
    events.emit(
        EventName.POST_PLAN_BUILT,
        data={
            "discussions": len(post_plan.discussions),
            "idempotent_summary": post_plan.idempotent_summary,
        },
    )

    discussion_items: list[PostResultItem] = []
    summary_error_lines: list[str] = []
    failed_discussions = 0
    for discussion in post_plan.discussions:
        if discussion.position is None:  # pragma: no cover - contract guard
            continue
        try:
            result = resolved_client.create_discussion(
                body=discussion.body_markdown,
                position=discussion.position.model_dump(mode="json"),
            )
        except ReviewerError as exc:
            failed_discussions += 1
            retry_count = _extract_retry_count(exc)
            http_status = _extract_http_status(exc)
            discussion_items.append(
                PostResultItem(
                    kind="discussion",
                    ok=False,
                    http_status=http_status,
                    retry_count=retry_count,
                    error=exc.error_info,
                )
            )
            summary_error_lines.append(
                _format_discussion_error_for_note(
                    path=discussion.path,
                    line=discussion.position.new_line,
                    http_status=http_status,
                    error=exc,
                )
            )
            events.emit(
                EventName.GITLAB_POST_DISCUSSION,
                level=EventLevel.ERROR,
                data={
                    "ok": False,
                    "path": discussion.path,
                    "line": discussion.position.new_line,
                    "http_status": http_status,
                    "retry": retry_count,
                    "error_code": exc.error_info.error_code,
                },
            )
            continue

        discussion_items.append(
            PostResultItem(
                kind="discussion",
                ok=True,
                http_status=result.status_code,
                gitlab_id=result.discussion_id,
                retry_count=result.retry_count,
            )
        )
        events.emit(
            EventName.GITLAB_POST_DISCUSSION,
            data={
                "ok": True,
                "path": discussion.path,
                "line": discussion.position.new_line,
                "http_status": result.status_code,
                "id": result.discussion_id,
                "retry": result.retry_count,
            },
        )

    note_body = build_summary_note_body(
        post_plan=post_plan,
        summary_note_tag=config.gitlab.summary_note_tag,
        fingerprint_marker=encode_fingerprint_marker(
            review.meta.fingerprint or fingerprint
        ),
        prior_digest_marker=encode_prior_digest_marker(
            build_embedded_prior_digest(review)
        ),
        truncation=truncation,
        redaction_found=review.meta.redaction_found,
        include_secret_warning=config.secrets.post_warning_to_mr,
        run_errors=summary_error_lines,
    )

    summary_item: PostResultItem
    summary_error: ReviewerError | None = None
    try:
        note_result = resolved_client.create_note(note_body)
    except ReviewerError as exc:
        summary_error = exc
        retry_count = _extract_retry_count(exc)
        http_status = _extract_http_status(exc)
        summary_item = PostResultItem(
            kind="summary_note",
            ok=False,
            http_status=http_status,
            retry_count=retry_count,
            error=exc.error_info,
        )
        events.emit(
            EventName.GITLAB_POST_SUMMARY,
            level=EventLevel.ERROR,
            data={
                "ok": False,
                "http_status": http_status,
                "retry": retry_count,
            },
        )
    else:
        summary_item = PostResultItem(
            kind="summary_note",
            ok=True,
            http_status=note_result.status_code,
            gitlab_id=note_result.note_id,
            retry_count=note_result.retry_count,
        )
        events.emit(
            EventName.GITLAB_POST_SUMMARY,
            data={
                "ok": True,
                "http_status": note_result.status_code,
                "id": note_result.note_id,
                "retry": note_result.retry_count,
            },
        )

    post_items = [summary_item, *discussion_items]
    post_results = PostResults(
        ok=summary_item.ok and failed_discussions == 0,
        items=post_items,
    )
    artifacts.write_json(POST_RESULTS_ARTIFACT_NAME, post_results)
    if summary_error is not None:
        raise summary_error
    if failed_discussions > 0:
        raise ReviewerError(
            "GitLab discussion posting partially failed",
            error_code=ErrorCode.GITLAB_POST_FAILED,
            context={
                "failed_discussions": failed_discussions,
                "total_discussions": len(post_plan.discussions),
            },
        )


def _extract_http_status(error: ReviewerError) -> int | None:
    status = error.error_info.context.get("status")
    return status if isinstance(status, int) else None


def _extract_retry_count(error: ReviewerError) -> int:
    retry_count = error.error_info.context.get("retry_count")
    return retry_count if isinstance(retry_count, int) else 0


def _extract_mr_payload(
    payload: dict[str, object] | list[object],
) -> dict[str, object] | None:
    return payload if isinstance(payload, dict) else None


def _extract_mr_diff_refs(payload: dict[str, object]) -> dict[str, object] | None:
    diff_refs = payload.get("diff_refs")
    return cast("dict[str, object]", diff_refs) if isinstance(diff_refs, dict) else None


def _format_discussion_error_for_note(
    *,
    path: str,
    line: int,
    http_status: int | None,
    error: ReviewerError,
) -> str:
    status_text = f" (HTTP {http_status})" if http_status is not None else ""
    return (
        f"`{path}:{line}` "
        f"[{error.error_info.error_code}] "
        f"{error.error_info.message}{status_text}"
    )
