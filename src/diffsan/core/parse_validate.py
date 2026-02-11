"""Parse and validate agent output."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from diffsan.contracts.errors import ErrorCode, ReviewerError
from diffsan.contracts.models import ReviewOutput


def parse_and_validate(raw_output: str) -> ReviewOutput:
    """Parse agent raw output and validate against ReviewOutput schema."""
    try:
        payload = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        raise ReviewerError(
            "Agent output is not valid JSON",
            error_code=ErrorCode.AGENT_OUTPUT_INVALID,
            cause=exc,
            context={"excerpt": raw_output[:240]},
        ) from exc

    candidate_payload = _extract_candidate_payload(payload)

    try:
        return ReviewOutput.model_validate(candidate_payload)
    except ValidationError as exc:
        raise ReviewerError(
            "Agent output failed schema validation",
            error_code=ErrorCode.AGENT_OUTPUT_INVALID,
            cause=exc,
            context={"errors": exc.errors(include_url=False)[:10]},
        ) from exc


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
