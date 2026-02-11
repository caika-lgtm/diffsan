"""Tests for parsing and schema validation."""

from __future__ import annotations

import json

import pytest

from diffsan.contracts.errors import ErrorCode, ReviewerError
from diffsan.core.parse_validate import parse_and_validate


def test_parse_and_validate_success() -> None:
    """Valid JSON ReviewOutput passes validation."""
    raw = """{
      "summary_markdown": "ok",
      "findings": [],
      "meta": {
        "agent": "cursor",
        "token_usage": {},
        "truncated": false,
        "redaction_found": false
      }
    }"""

    review = parse_and_validate(raw)

    assert review.summary_markdown == "ok"
    assert review.findings == []


def test_parse_and_validate_invalid_json() -> None:
    """Invalid JSON raises AGENT_OUTPUT_INVALID."""
    with pytest.raises(ReviewerError) as error:
        parse_and_validate("not-json")

    assert error.value.error_info.error_code == ErrorCode.AGENT_OUTPUT_INVALID


def test_parse_and_validate_wrapped_result_json() -> None:
    """Cursor JSON envelope with stringified result payload is supported."""
    review_payload = {
        "summary_markdown": "wrapped-ok",
        "findings": [],
        "meta": {"agent": "cursor", "token_usage": {}, "truncated": False},
    }
    wrapped = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": json.dumps(review_payload),
    }
    raw = json.dumps(wrapped)

    review = parse_and_validate(raw)

    assert review.summary_markdown == "wrapped-ok"
    assert review.meta.agent == "cursor"


def test_parse_and_validate_wrapped_result_error() -> None:
    """Cursor JSON envelope error is treated as invalid output."""
    wrapped = {
        "type": "result",
        "subtype": "error",
        "is_error": True,
        "result": "failed",
    }

    with pytest.raises(ReviewerError) as error:
        parse_and_validate(json.dumps(wrapped))

    assert error.value.error_info.error_code == ErrorCode.AGENT_OUTPUT_INVALID
