"""Tests for parsing and schema validation."""

from __future__ import annotations

import json

import pytest

from diffsan.contracts.errors import ErrorCode, ReviewerError
from diffsan.core.parse_validate import parse_and_validate


def test_parse_and_validate_success() -> None:
    """Valid agent JSON payload passes validation."""
    raw = """{
      "summary_markdown": "ok",
      "findings": []
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


def test_parse_and_validate_schema_validation_error() -> None:
    """JSON that does not match ReviewOutput raises AGENT_OUTPUT_INVALID."""
    with pytest.raises(ReviewerError) as error:
        parse_and_validate("{}")

    assert error.value.error_info.error_code == ErrorCode.AGENT_OUTPUT_INVALID


def test_parse_and_validate_wrapped_result_dict_payload() -> None:
    """Cursor envelope with object result payload is supported."""
    wrapped = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": {
            "summary_markdown": "wrapped-dict-ok",
            "findings": [],
        },
    }

    review = parse_and_validate(json.dumps(wrapped))

    assert review.summary_markdown == "wrapped-dict-ok"


def test_parse_and_validate_meta_field_is_rejected() -> None:
    """Agent payloads including meta should fail schema validation."""
    raw = json.dumps(
        {
            "summary_markdown": "ok",
            "findings": [],
            "meta": {"agent": "cursor"},
        }
    )

    with pytest.raises(ReviewerError) as error:
        parse_and_validate(raw)

    assert error.value.error_info.error_code == ErrorCode.AGENT_OUTPUT_INVALID


def test_parse_and_validate_wrapped_result_invalid_json_string() -> None:
    """Invalid JSON inside envelope result is reported as AGENT_OUTPUT_INVALID."""
    wrapped = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": "{not-json",
    }

    with pytest.raises(ReviewerError) as error:
        parse_and_validate(json.dumps(wrapped))

    assert error.value.error_info.error_code == ErrorCode.AGENT_OUTPUT_INVALID


def test_parse_and_validate_wrapped_result_unsupported_type() -> None:
    """Non-str/non-dict envelope result payloads are rejected."""
    wrapped = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": 123,
    }

    with pytest.raises(ReviewerError) as error:
        parse_and_validate(json.dumps(wrapped))

    assert error.value.error_info.error_code == ErrorCode.AGENT_OUTPUT_INVALID
