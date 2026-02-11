"""Top-level run harness for diffsan."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Final

from diffsan import __version__
from diffsan.contracts.errors import ErrorCode, ErrorInfo, ReviewerError
from diffsan.contracts.events import EventLevel, EventName
from diffsan.contracts.models import AppConfig, ArtifactPointers, ModeConfig, RunResult
from diffsan.io.artifacts import ArtifactStore
from diffsan.io.logging import EventLogger

DEFAULT_WORKDIR: Final[str] = ".diffsan"
RUN_ARTIFACT_NAME: Final[str] = "run.json"
EVENTS_ARTIFACT_NAME: Final[str] = "events.jsonl"


@dataclass(frozen=True, slots=True)
class RunOptions:
    """CLI-provided run options."""

    ci: bool = False
    dry_run: bool = False
    workdir: str = DEFAULT_WORKDIR


def run(options: RunOptions) -> RunResult:
    """Execute one diffsan run and always write `run.json`."""
    try:
        artifacts = ArtifactStore(options.workdir)
    except OSError as exc:
        fallback = ArtifactStore(DEFAULT_WORKDIR)
        fallback_events = EventLogger(fallback.path(EVENTS_ARTIFACT_NAME))
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

    events = EventLogger(artifacts.path(EVENTS_ARTIFACT_NAME))
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
        _run_pipeline(
            options=options,
            _config=config,
            _artifacts=artifacts,
            events=events,
        )
        run_result.ok = True
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
) -> None:
    """Milestone-0 pipeline stub.

    Real diff fetching/agent execution work lands in Milestone 1+.
    """
    events.emit(
        EventName.SKIP_DECIDED,
        data={"should_skip": False, "reasons": [], "fingerprint": None},
    )

    if options.dry_run:
        return

    events.emit(
        EventName.DIFF_FETCHED,
        data={"chars": 0, "files": 0, "base_sha": None, "head_sha": None},
    )
