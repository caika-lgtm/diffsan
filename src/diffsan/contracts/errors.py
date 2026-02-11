"""Error contracts used by the diffsan runtime."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ErrorCode(StrEnum):
    """Canonical error codes written to artifacts and events."""

    CONFIG_PARSE_ERROR = "CONFIG_PARSE_ERROR"
    DIFF_FETCH_FAILED = "DIFF_FETCH_FAILED"
    DIFF_PARSE_FAILED = "DIFF_PARSE_FAILED"
    REDACTION_ENGINE_FAILED = "REDACTION_ENGINE_FAILED"
    GITLAB_FETCH_PRIOR_FAILED = "GITLAB_FETCH_PRIOR_FAILED"
    AGENT_EXEC_FAILED = "AGENT_EXEC_FAILED"
    AGENT_OUTPUT_INVALID = "AGENT_OUTPUT_INVALID"
    FORMAT_FAILED = "FORMAT_FAILED"
    GITLAB_AUTH_ERROR = "GITLAB_AUTH_ERROR"
    GITLAB_POSITION_INVALID = "GITLAB_POSITION_INVALID"
    GITLAB_POST_FAILED = "GITLAB_POST_FAILED"


class ErrorInfo(BaseModel):
    """Structured error information persisted in run artifacts."""

    model_config = ConfigDict(extra="forbid")

    error_code: ErrorCode
    message: str
    retryable: bool = False
    context: dict[str, Any] = Field(default_factory=dict)
    cause: str | None = None


class ReviewerError(Exception):
    """Domain exception with normalized error payload."""

    def __init__(
        self,
        message: str,
        *,
        error_code: ErrorCode,
        retryable: bool = False,
        context: dict[str, Any] | None = None,
        cause: BaseException | str | None = None,
    ) -> None:
        cause_text = _format_cause(cause)
        self._error_info = ErrorInfo(
            error_code=error_code,
            message=message,
            retryable=retryable,
            context=context or {},
            cause=cause_text,
        )
        super().__init__(message)

    @property
    def error_info(self) -> ErrorInfo:
        """Return normalized error payload."""
        return self._error_info


def _format_cause(cause: BaseException | str | None) -> str | None:
    if cause is None:
        return None
    if isinstance(cause, BaseException):
        return f"{cause.__class__.__name__}: {cause}"
    return cause
