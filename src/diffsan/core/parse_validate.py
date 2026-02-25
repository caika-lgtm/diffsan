"""Parse and validate agent output."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from diffsan.contracts.errors import ErrorCode, ReviewerError
from diffsan.contracts.models import AgentReviewOutput

_MAX_JSON_START_CANDIDATES = 32


def parse_and_validate(raw_output: str) -> AgentReviewOutput:
    """Parse agent raw output and validate agent-owned review fields."""
    payload = _decode_json_payload(raw_output)
    candidate_payload = _extract_candidate_payload(payload)

    try:
        return AgentReviewOutput.model_validate(candidate_payload)
    except ValidationError as exc:
        raise ReviewerError(
            "Agent output failed schema validation",
            error_code=ErrorCode.AGENT_OUTPUT_INVALID,
            cause=exc,
            context={"errors": exc.errors(include_url=False)[:10]},
        ) from exc


def _decode_json_payload(raw_output: str) -> Any:
    """Decode agent JSON, allowing non-JSON preamble before an object payload."""
    try:
        return json.loads(raw_output)
    except json.JSONDecodeError as exc:
        recovered_payload = _recover_object_after_leading_text(raw_output)
        if recovered_payload is not None:
            return recovered_payload
        raise ReviewerError(
            "Agent output is not valid JSON",
            error_code=ErrorCode.AGENT_OUTPUT_INVALID,
            cause=exc,
            context={"excerpt": raw_output[:240]},
        ) from exc


def _recover_object_after_leading_text(raw_output: str) -> Any | None:
    """Parse the first valid top-level JSON object found in mixed text output."""
    candidates = _json_object_start_candidates(raw_output)
    if not candidates:
        return None

    decoder = json.JSONDecoder()
    for start in candidates:
        try:
            payload, end = decoder.raw_decode(raw_output, idx=start)
        except json.JSONDecodeError:
            continue
        _ = end
        return payload
    return None


def _json_object_start_candidates(raw_output: str) -> list[int]:
    """Return likely top-level JSON object starts in raw output text."""
    indices: list[int] = []
    search_start = 0
    while len(indices) < _MAX_JSON_START_CANDIDATES:
        idx = raw_output.find("{", search_start)
        if idx < 0:
            break
        indices.append(idx)
        search_start = idx + 1
    return indices


def _extract_candidate_payload(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload

    if "result" not in payload:
        return payload

    if payload.get("is_error") is True:
        raise ReviewerError(
            "Agent reported an error in JSON envelope",
            error_code=ErrorCode.AGENT_OUTPUT_INVALID,
            context={
                "type": payload.get("type"),
                "subtype": payload.get("subtype"),
                "is_error": True,
            },
        )

    result_payload = payload["result"]
    if isinstance(result_payload, dict):
        return result_payload

    if isinstance(result_payload, str):
        try:
            return json.loads(result_payload)
        except json.JSONDecodeError as exc:
            raise ReviewerError(
                "Agent envelope result field is not valid JSON",
                error_code=ErrorCode.AGENT_OUTPUT_INVALID,
                cause=exc,
                context={"result_excerpt": result_payload[:240]},
            ) from exc

    raise ReviewerError(
        "Agent envelope result field has unsupported type",
        error_code=ErrorCode.AGENT_OUTPUT_INVALID,
        context={"result_type": type(result_payload).__name__},
    )
