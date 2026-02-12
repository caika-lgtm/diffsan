"""Tests for skip decision helpers."""

from diffsan.contracts.models import AppConfig, Fingerprint, PriorDigest
from diffsan.core.skip import decide_skip


def test_decide_skip_auto_merge_enabled_creates_reason() -> None:
    """Auto-merge enabled should trigger skip when config allows it."""
    decision = decide_skip(
        config=AppConfig(),
        mr_payload={"merge_when_pipeline_succeeds": True},
        fingerprint=Fingerprint(value="a" * 64),
        prior_digest=None,
    )

    assert decision.should_skip is True
    assert decision.reasons[0].code == "AUTO_MERGE"
    assert decision.fingerprint is not None


def test_decide_skip_disabled_config_never_skips() -> None:
    """skip_on_auto_merge=false should always proceed."""
    decision = decide_skip(
        config=AppConfig.model_validate({"skip": {"skip_on_auto_merge": False}}),
        mr_payload={"merge_when_pipeline_succeeds": True},
        fingerprint=None,
        prior_digest=None,
    )

    assert decision.should_skip is False
    assert decision.reasons == []


def test_decide_skip_unknown_mr_fields_fail_open() -> None:
    """Unknown fields should not trigger skip."""
    decision = decide_skip(
        config=AppConfig(),
        mr_payload={"merge_status": "can_be_merged"},
        fingerprint=None,
        prior_digest=None,
    )

    assert decision.should_skip is False


def test_decide_skip_accepts_int_and_string_truthy_flags() -> None:
    """Truthy int/string values in known fields should trigger skip."""
    decision_int = decide_skip(
        config=AppConfig(),
        mr_payload={"auto_merge_enabled": 1},
        fingerprint=None,
        prior_digest=None,
    )
    decision_str = decide_skip(
        config=AppConfig(),
        mr_payload={"merge_train_when_pipeline_succeeds": "true"},
        fingerprint=None,
        prior_digest=None,
    )

    assert decision_int.should_skip is True
    assert decision_str.should_skip is True


def test_decide_skip_accepts_nested_auto_merge_payload() -> None:
    """Nested auto_merge fields should be recognized."""
    decision = decide_skip(
        config=AppConfig(),
        mr_payload={"auto_merge": {"enabled": "yes"}},
        fingerprint=None,
        prior_digest=None,
    )

    assert decision.should_skip is True


def test_decide_skip_ignores_non_truthy_nested_auto_merge() -> None:
    """Falsey nested values should not trigger skip."""
    decision = decide_skip(
        config=AppConfig(),
        mr_payload={"auto_merge": {"enabled": 0, "is_enabled": "off"}},
        fingerprint=None,
        prior_digest=None,
    )

    assert decision.should_skip is False


def test_decide_skip_same_fingerprint_enabled_by_default() -> None:
    """Matching fingerprints should trigger skip by default."""
    fingerprint = Fingerprint(value="a" * 64)
    decision = decide_skip(
        config=AppConfig(),
        mr_payload={},
        fingerprint=fingerprint,
        prior_digest=PriorDigest(prior_fingerprint=fingerprint),
    )

    assert decision.should_skip is True
    assert any(reason.code == "SAME_FINGERPRINT" for reason in decision.reasons)


def test_decide_skip_same_fingerprint_can_be_disabled() -> None:
    """skip_on_same_fingerprint=false should allow re-runs."""
    config = AppConfig.model_validate(
        {"skip": {"skip_on_auto_merge": True, "skip_on_same_fingerprint": False}}
    )
    fingerprint = Fingerprint(value="b" * 64)
    decision = decide_skip(
        config=config,
        mr_payload={},
        fingerprint=fingerprint,
        prior_digest=PriorDigest(prior_fingerprint=fingerprint),
    )

    assert decision.should_skip is False
