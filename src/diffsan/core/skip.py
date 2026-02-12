"""Skip decision helpers for pipeline runs."""

from __future__ import annotations

from typing import Any

from diffsan.contracts.models import (
    AppConfig,
    Fingerprint,
    PriorDigest,
    SkipDecision,
    SkipReason,
)

_AUTO_MERGE_REASON_CODE = "AUTO_MERGE"
_AUTO_MERGE_REASON_MESSAGE = "MR has auto-merge enabled"
_SAME_FINGERPRINT_REASON_CODE = "SAME_FINGERPRINT"
_SAME_FINGERPRINT_REASON_MESSAGE = "Diff fingerprint matches latest diffsan review"
_AUTO_MERGE_BOOL_FIELDS = (
    "auto_merge_enabled",
    "merge_when_pipeline_succeeds",
    "merge_train_when_pipeline_succeeds",
)
_TRUE_VALUES = {"1", "true", "yes", "on"}


def decide_skip(
    *,
    config: AppConfig,
    mr_payload: dict[str, Any] | None,
    fingerprint: Fingerprint | None,
    prior_digest: PriorDigest | None,
) -> SkipDecision:
    """Build skip decision based on runtime config and MR metadata."""
    reasons: list[SkipReason] = []
    if (
        config.skip.skip_on_auto_merge
        and mr_payload is not None
        and _is_auto_merge_enabled(mr_payload)
    ):
        reasons.append(
            SkipReason(
                code=_AUTO_MERGE_REASON_CODE,
                message=_AUTO_MERGE_REASON_MESSAGE,
            )
        )
    if config.skip.skip_on_same_fingerprint and _is_same_fingerprint(
        fingerprint=fingerprint, prior_digest=prior_digest
    ):
        reasons.append(
            SkipReason(
                code=_SAME_FINGERPRINT_REASON_CODE,
                message=_SAME_FINGERPRINT_REASON_MESSAGE,
            )
        )

    return SkipDecision(
        should_skip=bool(reasons),
        reasons=reasons,
        fingerprint=fingerprint,
        prior_digest=prior_digest,
    )


def _is_auto_merge_enabled(mr_payload: dict[str, Any]) -> bool:
    for field in _AUTO_MERGE_BOOL_FIELDS:
        if _truthy(mr_payload.get(field)):
            return True

    auto_merge = mr_payload.get("auto_merge")
    if isinstance(auto_merge, dict):
        for field in ("enabled", "is_enabled"):
            if _truthy(auto_merge.get(field)):
                return True

    return False


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in _TRUE_VALUES
    return False


def _is_same_fingerprint(
    *,
    fingerprint: Fingerprint | None,
    prior_digest: PriorDigest | None,
) -> bool:
    if fingerprint is None or prior_digest is None:
        return False
    prior_fingerprint = prior_digest.prior_fingerprint
    if prior_fingerprint is None:
        return False
    return (
        fingerprint.algo == prior_fingerprint.algo
        and fingerprint.value == prior_fingerprint.value
    )
