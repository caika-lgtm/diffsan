"""Tests for GitLab API client retry/error behavior."""

from __future__ import annotations

import pytest

import diffsan.core.gitlab as gitlab_module
from diffsan.contracts.errors import ErrorCode, ReviewerError
from diffsan.contracts.models import GitLabConfig
from diffsan.core.gitlab import GitLabClient


def _base_config(*, retry_max: int = 3) -> GitLabConfig:
    return GitLabConfig(
        base_url="https://gitlab.example.com",
        project_id="123",
        mr_iid=7,
        token_env="TEST_GITLAB_TOKEN",
        retry_max=retry_max,
    )


def test_create_note_success_returns_id(monkeypatch) -> None:
    """Successful note creation returns note id and no retries."""
    monkeypatch.setenv("TEST_GITLAB_TOKEN", "token")
    client = GitLabClient(_base_config(), sleep_fn=lambda _: None)

    captured: dict[str, object] = {}

    def _send_request(*, method, url, token, payload):
        captured["method"] = method
        captured["url"] = url
        captured["token"] = token
        captured["payload"] = payload
        return 201, '{"id": 456}'

    monkeypatch.setattr(client, "_send_request", _send_request)

    result = client.create_note("hello")

    assert result.note_id == 456
    assert result.status_code == 201
    assert result.retry_count == 0
    assert captured["method"] == "POST"
    assert captured["url"] == (
        "https://gitlab.example.com/api/v4/projects/123/merge_requests/7/notes"
    )
    assert captured["token"] == "token"
    assert captured["payload"] == {"body": "hello"}


def test_create_note_retries_429_then_succeeds(monkeypatch) -> None:
    """HTTP 429 should be retried and eventually succeed."""
    monkeypatch.setenv("TEST_GITLAB_TOKEN", "token")
    client = GitLabClient(_base_config(retry_max=3), sleep_fn=lambda _: None)

    calls = 0

    def _send_request(*, method, url, token, payload):
        _ = method, url, token, payload
        nonlocal calls
        calls += 1
        if calls == 1:
            raise gitlab_module._GitLabHttpError(status_code=429, body="rate limited")
        return 201, '{"id": 999}'

    monkeypatch.setattr(client, "_send_request", _send_request)

    result = client.create_note("hello")

    assert calls == 2
    assert result.note_id == 999
    assert result.retry_count == 1


def test_create_note_auth_error_fails_fast(monkeypatch) -> None:
    """401/403 should map to GITLAB_AUTH_ERROR without retries."""
    monkeypatch.setenv("TEST_GITLAB_TOKEN", "token")
    client = GitLabClient(_base_config(retry_max=4), sleep_fn=lambda _: None)

    calls = 0

    def _send_request(*, method, url, token, payload):
        _ = method, url, token, payload
        nonlocal calls
        calls += 1
        raise gitlab_module._GitLabHttpError(status_code=401, body="unauthorized")

    monkeypatch.setattr(client, "_send_request", _send_request)

    with pytest.raises(ReviewerError) as error:
        client.create_note("hello")

    assert calls == 1
    assert error.value.error_info.error_code == ErrorCode.GITLAB_AUTH_ERROR
    assert error.value.error_info.retryable is False


def test_create_note_5xx_exhaustion_is_retryable(monkeypatch) -> None:
    """5xx exhaustion should fail with retryable GITLAB_POST_FAILED."""
    monkeypatch.setenv("TEST_GITLAB_TOKEN", "token")
    client = GitLabClient(_base_config(retry_max=2), sleep_fn=lambda _: None)

    calls = 0

    def _send_request(*, method, url, token, payload):
        _ = method, url, token, payload
        nonlocal calls
        calls += 1
        raise gitlab_module._GitLabHttpError(status_code=502, body="bad gateway")

    monkeypatch.setattr(client, "_send_request", _send_request)

    with pytest.raises(ReviewerError) as error:
        client.create_note("hello")

    assert calls == 2
    assert error.value.error_info.error_code == ErrorCode.GITLAB_POST_FAILED
    assert error.value.error_info.retryable is True
    assert error.value.error_info.context["status"] == 502
    assert error.value.error_info.context["retry_count"] == 1


def test_get_mr_404_uses_fetch_error_code(monkeypatch) -> None:
    """MR fetch maps 404 to GITLAB_FETCH_PRIOR_FAILED."""
    monkeypatch.setenv("TEST_GITLAB_TOKEN", "token")
    client = GitLabClient(_base_config(), sleep_fn=lambda _: None)

    def _send_request(*, method, url, token, payload):
        _ = method, url, token, payload
        raise gitlab_module._GitLabHttpError(status_code=404, body="missing")

    monkeypatch.setattr(client, "_send_request", _send_request)

    with pytest.raises(ReviewerError) as error:
        client.get_mr()

    assert error.value.error_info.error_code == ErrorCode.GITLAB_FETCH_PRIOR_FAILED
