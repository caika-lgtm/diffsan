"""Event contracts for structured run logs."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EventLevel(StrEnum):
    """Allowed event levels."""

    ERROR = "error"
    WARN = "warn"
    INFO = "info"
    DEBUG = "debug"


class EventName(StrEnum):
    """Canonical event names used by diffsan."""

    RUN_STARTED = "run.started"
    RUN_FINISHED = "run.finished"
    CONFIG_LOADED = "config.loaded"
    DIFF_FETCHED = "diff.fetched"
    DIFF_PREPARED = "diff.prepared"
    SKIP_DECIDED = "skip.decided"
    PROMPT_WRITTEN = "prompt.written"
    AGENT_ATTEMPT = "agent.attempt"
    REVIEW_VALIDATED = "review.validated"
    POST_PLAN_BUILT = "post.plan_built"
    GITLAB_POST_SUMMARY = "gitlab.post.summary"
    GITLAB_POST_DISCUSSION = "gitlab.post.discussion"
    ERROR_RAISED = "error.raised"


class Event(BaseModel):
    """Single JSONL event payload."""

    model_config = ConfigDict(extra="forbid")

    ts: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    level: EventLevel = EventLevel.INFO
    event: str
    data: dict[str, Any] = Field(default_factory=dict)
