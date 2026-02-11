"""Parse and validate agent output."""

from __future__ import annotations

import json

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

    try:
        return ReviewOutput.model_validate(payload)
    except ValidationError as exc:
        raise ReviewerError(
            "Agent output failed schema validation",
            error_code=ErrorCode.AGENT_OUTPUT_INVALID,
            cause=exc,
            context={"errors": exc.errors(include_url=False)[:10]},
        ) from exc
