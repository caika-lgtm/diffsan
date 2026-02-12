"""Tests for GitLab API client retry/error behavior."""

from __future__ import annotations

import io
from email.message import Message
from urllib import error as urllib_error

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


def test_create_note_400_maps_to_post_failed(monkeypatch) -> None:
    """HTTP 400 should fail without retry as GITLAB_POST_FAILED."""
    monkeypatch.setenv("TEST_GITLAB_TOKEN", "token")
    client = GitLabClient(_base_config(retry_max=3), sleep_fn=lambda _: None)

    def _send_request(*, method, url, token, payload):
        _ = method, url, token, payload
        raise gitlab_module._GitLabHttpError(status_code=400, body='{"error":"bad"}')

    monkeypatch.setattr(client, "_send_request", _send_request)

    with pytest.raises(ReviewerError) as error:
        client.create_note("hello")

    assert error.value.error_info.error_code == ErrorCode.GITLAB_POST_FAILED
    assert error.value.error_info.retryable is False
    assert error.value.error_info.context["status"] == 400


def test_create_note_retries_on_transport_then_succeeds(monkeypatch) -> None:
    """Transient transport errors should retry."""
    monkeypatch.setenv("TEST_GITLAB_TOKEN", "token")
    client = GitLabClient(_base_config(retry_max=2), sleep_fn=lambda _: None)
    calls = 0

    def _send_request(*, method, url, token, payload):
        _ = method, url, token, payload
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("temporary")
        return 201, '{"id": 12}'

    monkeypatch.setattr(client, "_send_request", _send_request)

    result = client.create_note("hello")

    assert calls == 2
    assert result.note_id == 12
    assert result.retry_count == 1


def test_create_note_transport_exhaustion_is_retryable(monkeypatch) -> None:
    """Transport exhaustion should surface retryable post failure."""
    monkeypatch.setenv("TEST_GITLAB_TOKEN", "token")
    client = GitLabClient(_base_config(retry_max=1), sleep_fn=lambda _: None)

    def _send_request(*, method, url, token, payload):
        _ = method, url, token, payload
        raise OSError("down")

    monkeypatch.setattr(client, "_send_request", _send_request)

    with pytest.raises(ReviewerError) as error:
        client.create_note("hello")

    assert error.value.error_info.error_code == ErrorCode.GITLAB_POST_FAILED
    assert error.value.error_info.retryable is True
    assert error.value.error_info.context["retry_count"] == 0


def test_context_missing_token(monkeypatch) -> None:
    """Missing token should raise auth error before request."""
    monkeypatch.delenv("TEST_GITLAB_TOKEN", raising=False)
    client = GitLabClient(_base_config(), sleep_fn=lambda _: None)

    with pytest.raises(ReviewerError) as error:
        client.get_mr()

    assert error.value.error_info.error_code == ErrorCode.GITLAB_AUTH_ERROR
    assert error.value.error_info.context["token_env"] == "TEST_GITLAB_TOKEN"


def test_context_missing_project_id(monkeypatch) -> None:
    """Missing project id in config and env should fail."""
    monkeypatch.setenv("TEST_GITLAB_TOKEN", "token")
    monkeypatch.delenv("CI_PROJECT_ID", raising=False)
    client = GitLabClient(
        GitLabConfig(
            base_url="https://gitlab.example.com",
            project_id=None,
            mr_iid=7,
            token_env="TEST_GITLAB_TOKEN",
        ),
        sleep_fn=lambda _: None,
    )

    with pytest.raises(ReviewerError) as error:
        client.get_mr()

    assert error.value.error_info.error_code == ErrorCode.GITLAB_FETCH_PRIOR_FAILED
    assert error.value.error_info.context["missing_env"] == "CI_PROJECT_ID"


def test_context_missing_mr_iid(monkeypatch) -> None:
    """Missing MR IID in config and env should fail."""
    monkeypatch.setenv("TEST_GITLAB_TOKEN", "token")
    monkeypatch.setenv("CI_PROJECT_ID", "123")
    monkeypatch.delenv("CI_MERGE_REQUEST_IID", raising=False)
    client = GitLabClient(
        GitLabConfig(
            base_url="https://gitlab.example.com",
            project_id=None,
            mr_iid=None,
            token_env="TEST_GITLAB_TOKEN",
        ),
        sleep_fn=lambda _: None,
    )

    with pytest.raises(ReviewerError) as error:
        client.get_mr()

    assert error.value.error_info.error_code == ErrorCode.GITLAB_FETCH_PRIOR_FAILED
    assert error.value.error_info.context["missing_env"] == "CI_MERGE_REQUEST_IID"


def test_context_invalid_mr_iid(monkeypatch) -> None:
    """Non-integer MR IID from env should fail with context."""
    monkeypatch.setenv("TEST_GITLAB_TOKEN", "token")
    monkeypatch.setenv("CI_PROJECT_ID", "123")
    monkeypatch.setenv("CI_MERGE_REQUEST_IID", "abc")
    client = GitLabClient(
        GitLabConfig(
            base_url="https://gitlab.example.com",
            project_id=None,
            mr_iid=None,
            token_env="TEST_GITLAB_TOKEN",
        ),
        sleep_fn=lambda _: None,
    )

    with pytest.raises(ReviewerError) as error:
        client.get_mr()

    assert error.value.error_info.error_code == ErrorCode.GITLAB_FETCH_PRIOR_FAILED
    assert error.value.error_info.context["mr_iid"] == "abc"


def test_send_request_success_path(monkeypatch) -> None:
    """_send_request should return status and decoded body."""
    monkeypatch.setenv("TEST_GITLAB_TOKEN", "token")
    client = GitLabClient(_base_config(), sleep_fn=lambda _: None)

    class _Response:
        status = 201

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def read(self):
            return b'{"ok":true}'

    def _urlopen(_req, timeout):
        _ = timeout
        return _Response()

    monkeypatch.setattr(gitlab_module.request, "urlopen", _urlopen)

    status, body = client._send_request(
        method="POST",
        url="https://gitlab.example.com/api/v4/projects/1/merge_requests/2/notes",
        token="token",
        payload={"body": "x"},
    )

    assert status == 201
    assert body == '{"ok":true}'


def test_send_request_http_error_is_wrapped(monkeypatch) -> None:
    """HTTPError should be wrapped with status/body in _GitLabHttpError."""
    monkeypatch.setenv("TEST_GITLAB_TOKEN", "token")
    client = GitLabClient(_base_config(), sleep_fn=lambda _: None)

    def _raise_http_error(_req, timeout):
        _ = timeout
        headers = Message()
        raise urllib_error.HTTPError(
            url="https://example.com",
            code=503,
            msg="bad",
            hdrs=headers,
            fp=io.BytesIO(b'{"message":"oops"}'),
        )

    monkeypatch.setattr(gitlab_module.request, "urlopen", _raise_http_error)

    with pytest.raises(gitlab_module._GitLabHttpError) as error:
        client._send_request(
            method="GET",
            url="https://example.com",
            token="token",
            payload=None,
        )

    assert error.value.status_code == 503
    assert '"oops"' in error.value.body


def test_send_request_url_timeout_maps_to_timeout_error(monkeypatch) -> None:
    """URLError with timeout reason should raise TimeoutError."""
    monkeypatch.setenv("TEST_GITLAB_TOKEN", "token")
    client = GitLabClient(_base_config(), sleep_fn=lambda _: None)

    def _raise_timeout(_req, timeout):
        _ = timeout
        raise urllib_error.URLError(TimeoutError("timed out"))

    monkeypatch.setattr(gitlab_module.request, "urlopen", _raise_timeout)

    with pytest.raises(TimeoutError):
        client._send_request(
            method="GET",
            url="https://example.com",
            token="token",
            payload=None,
        )


def test_helpers_cover_url_and_body_edge_cases(monkeypatch) -> None:
    """Cover helper edge cases used by client internals."""
    monkeypatch.setenv("CI_API_V4_URL", "https://ci.example.com/api/v4/")
    assert (
        gitlab_module._resolve_api_v4_url("https://ignored.example.com")
        == "https://ci.example.com/api/v4"
    )
    monkeypatch.delenv("CI_API_V4_URL", raising=False)
    assert (
        gitlab_module._resolve_api_v4_url("https://gitlab.example.com/api/v4")
        == "https://gitlab.example.com/api/v4"
    )

    assert gitlab_module._decode_json_body("   ") == {}
    assert gitlab_module._decode_json_body("[1,2,3]") == {"raw": [1, 2, 3]}
    assert gitlab_module._to_int_or_none("42") == 42
    assert gitlab_module._to_int_or_none("abc") is None
