"""GitLab API client helpers for MR metadata and posting notes/discussions."""

from __future__ import annotations

import json
import os
import random
import socket
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib import error, parse, request

from diffsan.contracts.errors import ErrorCode, ReviewerError

if TYPE_CHECKING:
    from diffsan.contracts.models import GitLabConfig


@dataclass(frozen=True, slots=True)
class GitLabRequestResult:
    """Result from a successful GitLab API request."""

    status_code: int
    payload: dict[str, Any] | list[Any]
    retry_count: int = 0


@dataclass(frozen=True, slots=True)
class GitLabNoteResult:
    """Summary note creation result."""

    note_id: int | None
    status_code: int
    retry_count: int = 0


@dataclass(frozen=True, slots=True)
class GitLabDiscussionResult:
    """Inline discussion creation result."""

    discussion_id: int | None
    status_code: int
    retry_count: int = 0


@dataclass(frozen=True, slots=True)
class _GitLabContext:
    api_v4_url: str
    project_id: str
    mr_iid: int
    token: str


@dataclass(frozen=True, slots=True)
class _GitLabHttpError(Exception):
    status_code: int
    body: str


class GitLabClient:
    """Minimal GitLab API client with bounded retries for transient failures."""

    def __init__(
        self,
        config: GitLabConfig,
        *,
        timeout_seconds: float = 10.0,
        sleep_fn: Any = time.sleep,
    ) -> None:
        self.config = config
        self.timeout_seconds = timeout_seconds
        self._sleep = sleep_fn

    def get_mr(self) -> GitLabRequestResult:
        """Fetch MR metadata for current context."""
        context = self._resolve_context(error_code=ErrorCode.GITLAB_FETCH_PRIOR_FAILED)
        return self._request_json(
            method="GET",
            context=context,
            path=self._mr_api_path(context),
            payload=None,
            error_code=ErrorCode.GITLAB_FETCH_PRIOR_FAILED,
            action="fetch merge request",
            invalid_400_error_code=None,
        )

    def list_notes(self) -> GitLabRequestResult:
        """List MR notes for prior digest extraction."""
        context = self._resolve_context(error_code=ErrorCode.GITLAB_FETCH_PRIOR_FAILED)
        return self._request_json(
            method="GET",
            context=context,
            path=f"{self._mr_api_path(context)}/notes?per_page=100",
            payload=None,
            error_code=ErrorCode.GITLAB_FETCH_PRIOR_FAILED,
            action="list merge request notes",
            invalid_400_error_code=None,
        )

    def create_note(self, body: str) -> GitLabNoteResult:
        """Create one MR note and return the GitLab note id if present."""
        context = self._resolve_context(error_code=ErrorCode.GITLAB_POST_FAILED)
        response = self._request_json(
            method="POST",
            context=context,
            path=f"{self._mr_api_path(context)}/notes",
            payload={"body": body},
            error_code=ErrorCode.GITLAB_POST_FAILED,
            action="create MR note",
            invalid_400_error_code=None,
        )
        payload = response.payload if isinstance(response.payload, dict) else {}
        note_id = _to_int_or_none(payload.get("id"))
        return GitLabNoteResult(
            note_id=note_id,
            status_code=response.status_code,
            retry_count=response.retry_count,
        )

    def create_discussion(
        self,
        *,
        body: str,
        position: dict[str, Any],
    ) -> GitLabDiscussionResult:
        """Create one inline MR discussion."""
        context = self._resolve_context(error_code=ErrorCode.GITLAB_POST_FAILED)
        response = self._request_json(
            method="POST",
            context=context,
            path=f"{self._mr_api_path(context)}/discussions",
            payload={"body": body, "position": position},
            error_code=ErrorCode.GITLAB_POST_FAILED,
            action="create MR discussion",
            invalid_400_error_code=ErrorCode.GITLAB_POSITION_INVALID,
        )
        payload = response.payload if isinstance(response.payload, dict) else {}
        return GitLabDiscussionResult(
            discussion_id=_to_int_or_none(payload.get("id")),
            status_code=response.status_code,
            retry_count=response.retry_count,
        )

    def _request_json(
        self,
        *,
        method: str,
        context: _GitLabContext,
        path: str,
        payload: dict[str, Any] | None,
        error_code: ErrorCode,
        action: str,
        invalid_400_error_code: ErrorCode | None,
    ) -> GitLabRequestResult:
        url = f"{context.api_v4_url}{path}"
        retry_max = max(1, self.config.retry_max)
        last_transport_error: Exception | None = None

        for attempt_idx in range(retry_max):
            retry_count = attempt_idx
            try:
                status_code, response_body = self._send_request(
                    method=method,
                    url=url,
                    token=context.token,
                    payload=payload,
                )
            except _GitLabHttpError as exc:
                error_payload = _decode_json_body(exc.body)
                if exc.status_code in {401, 403}:
                    raise ReviewerError(
                        "GitLab authentication failed",
                        error_code=ErrorCode.GITLAB_AUTH_ERROR,
                        context={
                            "status": exc.status_code,
                            "url": url,
                            "action": action,
                            "retry_count": retry_count,
                        },
                        cause=exc.body[:500] or "unauthorized",
                    ) from exc
                if exc.status_code == 404:
                    raise ReviewerError(
                        "GitLab resource was not found",
                        error_code=error_code,
                        context={
                            "status": exc.status_code,
                            "url": url,
                            "action": action,
                            "retry_count": retry_count,
                        },
                        cause=exc.body[:500] or "not found",
                    ) from exc
                if exc.status_code == 400 and invalid_400_error_code is not None:
                    raise ReviewerError(
                        "GitLab rejected discussion position",
                        error_code=invalid_400_error_code,
                        context={
                            "status": exc.status_code,
                            "url": url,
                            "action": action,
                            "retry_count": retry_count,
                            "response": error_payload,
                        },
                        cause=exc.body[:500] or "invalid discussion position",
                    ) from exc
                if _is_retryable_http_status(exc.status_code):
                    if attempt_idx < retry_max - 1:
                        self._sleep(_compute_backoff_seconds(attempt_idx))
                        continue
                    raise ReviewerError(
                        f"GitLab {action} failed after retries",
                        error_code=error_code,
                        retryable=True,
                        context={
                            "status": exc.status_code,
                            "url": url,
                            "action": action,
                            "retry_count": retry_count,
                            "response": error_payload,
                        },
                        cause=exc.body[:500] or "transient API failure",
                    ) from exc

                raise ReviewerError(
                    f"GitLab {action} failed",
                    error_code=error_code,
                    context={
                        "status": exc.status_code,
                        "url": url,
                        "action": action,
                        "retry_count": retry_count,
                        "response": error_payload,
                    },
                    cause=exc.body[:500] or "API rejected request",
                ) from exc
            except (error.URLError, OSError, TimeoutError) as exc:
                last_transport_error = exc
                if attempt_idx < retry_max - 1:
                    self._sleep(_compute_backoff_seconds(attempt_idx))
                    continue
                raise ReviewerError(
                    f"GitLab {action} failed after retries",
                    error_code=error_code,
                    retryable=True,
                    context={
                        "url": url,
                        "action": action,
                        "retry_count": retry_count,
                    },
                    cause=exc,
                ) from exc

            response_payload = _decode_json_body(response_body)
            return GitLabRequestResult(
                status_code=status_code,
                payload=response_payload,
                retry_count=retry_count,
            )

        assert last_transport_error is not None
        raise ReviewerError(
            f"GitLab {action} failed",
            error_code=error_code,
            retryable=True,
            context={"url": url, "action": action},
            cause=last_transport_error,
        )

    def _send_request(
        self,
        *,
        method: str,
        url: str,
        token: str,
        payload: dict[str, Any] | None,
    ) -> tuple[int, str]:
        body_bytes = None
        headers = {"PRIVATE-TOKEN": token}
        if payload is not None:
            body_bytes = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = request.Request(url=url, method=method, data=body_bytes, headers=headers)
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8", errors="replace")
                return int(response.status), body
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise _GitLabHttpError(status_code=int(exc.code), body=body) from exc
        except error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, TimeoutError | socket.timeout):
                raise TimeoutError(str(reason)) from exc
            raise

    def _resolve_context(self, *, error_code: ErrorCode) -> _GitLabContext:
        token = os.getenv(self.config.token_env)
        if not token:
            raise ReviewerError(
                "Missing GitLab token",
                error_code=ErrorCode.GITLAB_AUTH_ERROR,
                context={"token_env": self.config.token_env},
            )

        project_id = self.config.project_id or os.getenv("CI_PROJECT_ID")
        if not project_id:
            raise ReviewerError(
                "Missing GitLab project id",
                error_code=error_code,
                context={"missing_env": "CI_PROJECT_ID"},
            )

        mr_iid_raw = (
            str(self.config.mr_iid)
            if self.config.mr_iid is not None
            else os.getenv("CI_MERGE_REQUEST_IID")
        )
        if not mr_iid_raw:
            raise ReviewerError(
                "Missing GitLab MR IID",
                error_code=error_code,
                context={"missing_env": "CI_MERGE_REQUEST_IID"},
            )
        try:
            mr_iid = int(mr_iid_raw)
        except ValueError as exc:
            raise ReviewerError(
                "GitLab MR IID must be an integer",
                error_code=error_code,
                context={"mr_iid": mr_iid_raw},
                cause=exc,
            ) from exc

        api_v4_url = _resolve_api_v4_url(self.config.base_url)
        return _GitLabContext(
            api_v4_url=api_v4_url,
            project_id=project_id,
            mr_iid=mr_iid,
            token=token,
        )

    def _mr_api_path(self, context: _GitLabContext) -> str:
        encoded_project = parse.quote(context.project_id, safe="")
        return f"/projects/{encoded_project}/merge_requests/{context.mr_iid}"


def _resolve_api_v4_url(base_url: str) -> str:
    from_ci = os.getenv("CI_API_V4_URL")
    if from_ci:
        return from_ci.rstrip("/")
    normalized = base_url.rstrip("/")
    if normalized.endswith("/api/v4"):
        return normalized
    return f"{normalized}/api/v4"


def _decode_json_body(body: str) -> dict[str, Any] | list[Any]:
    stripped = body.strip()
    if not stripped:
        return {}
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return {"raw": stripped[:1000]}
    if isinstance(payload, dict | list):
        return payload
    return {"raw": payload}


def _is_retryable_http_status(status_code: int) -> bool:
    return status_code == 429 or status_code >= 500


def _compute_backoff_seconds(attempt_idx: int) -> float:
    # Exponential backoff starting at 1s, with small jitter to reduce bursts.
    base = float(2**attempt_idx)
    return base + random.uniform(0.0, 0.25)


def _to_int_or_none(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None
