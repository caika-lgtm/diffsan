"""Top-level run harness for diffsan."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Final

from diffsan import __version__
from diffsan.contracts.errors import ErrorCode, ErrorInfo, ReviewerError
from diffsan.contracts.events import EventLevel, EventName
from diffsan.contracts.models import (
    AppConfig,
    ArtifactPointers,
    Fingerprint,
    ModeConfig,
    RunResult,
)
from diffsan.core.agent_cursor import run_cursor_once
from diffsan.core.diff_provider import get_diff
from diffsan.core.fingerprint import compute_fingerprint
from diffsan.core.format import print_summary_markdown
from diffsan.core.parse_validate import parse_and_validate
from diffsan.core.preprocess import prepare_diff
from diffsan.core.prompt import build_agent_request
from diffsan.io.artifacts import ArtifactStore
from diffsan.io.logging import EventLogger

DEFAULT_WORKDIR: Final[str] = ".diffsan"
RUN_ARTIFACT_NAME: Final[str] = "run.json"
EVENTS_ARTIFACT_NAME: Final[str] = "events.jsonl"
DIFF_RAW_ARTIFACT_NAME: Final[str] = "diff.raw.patch"
DIFF_PREPARED_ARTIFACT_NAME: Final[str] = "diff.prepared.patch"
TRUNCATION_ARTIFACT_NAME: Final[str] = "truncation.json"
REDACTION_ARTIFACT_NAME: Final[str] = "redaction.json"
PROMPT_ARTIFACT_NAME: Final[str] = "prompt.txt"
RAW_OUTPUT_ARTIFACT_NAME: Final[str] = "agent.raw.txt"
RAW_STDERR_ARTIFACT_NAME: Final[str] = "agent.stderr.txt"
REVIEW_ARTIFACT_NAME: Final[str] = "review.json"


@dataclass(frozen=True, slots=True)
class RunOptions:
    """CLI-provided run options."""

    ci: bool = False
    dry_run: bool = False
    workdir: str = DEFAULT_WORKDIR


@dataclass(frozen=True, slots=True)
class PipelineOutcome:
    """Data returned from one pipeline execution."""

    skipped: bool = False
    fingerprint: Fingerprint | None = None


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
    """Milestone-1 pipeline: diff -> prompt -> agent -> validate -> stdout."""
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
    events.emit(
        EventName.SKIP_DECIDED,
        data={
            "should_skip": False,
            "reasons": [],
            "fingerprint": f"{fingerprint.algo}:{fingerprint.value}",
        },
    )

    request = build_agent_request(
        config=_config,
        prepared=prepared,
        fingerprint=fingerprint,
    )
    _artifacts.write_text(PROMPT_ARTIFACT_NAME, request.prompt)
    events.emit(
        EventName.PROMPT_WRITTEN,
        data={"path": PROMPT_ARTIFACT_NAME, "chars": len(request.prompt)},
    )

    attempt = run_cursor_once(request.prompt, _config)
    _artifacts.write_text(RAW_OUTPUT_ARTIFACT_NAME, attempt.raw_stdout)
    if attempt.raw_stderr:
        _artifacts.write_text(RAW_STDERR_ARTIFACT_NAME, attempt.raw_stderr)
    events.emit(
        EventName.AGENT_ATTEMPT,
        data={
            "attempt": 1,
            "exit_code": attempt.exit_code,
            "duration_ms": attempt.duration_ms,
        },
    )

    review = parse_and_validate(attempt.raw_stdout)
    review = review.model_copy(
        update={
            "meta": review.meta.model_copy(
                update={
                    "fingerprint": review.meta.fingerprint or fingerprint,
                    "agent": review.meta.agent or _config.agent.agent,
                    "truncated": prepared.truncation.truncated,
                    "redaction_found": prepared.redaction.found,
                }
            )
        }
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
    return PipelineOutcome(skipped=False, fingerprint=fingerprint)
