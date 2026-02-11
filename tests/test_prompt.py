"""Tests for prompt construction."""

from diffsan.contracts.models import (
    AgentConfig,
    AppConfig,
    Fingerprint,
    PreparedDiff,
    PriorDigest,
    PriorFinding,
    RedactionReport,
    TruncationItem,
    TruncationReport,
)
from diffsan.core.prompt import build_agent_request


def test_build_agent_request_with_prior_truncation_and_redaction() -> None:
    """Prompt includes schema, context flags, and prior digest details."""
    config = AppConfig(
        agent=AgentConfig(verbosity="high", skills=["security", "python"]),
    )
    prepared = PreparedDiff(
        prepared_diff="diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-a\n+b\n",
        truncation=TruncationReport(
            truncated=True,
            original_chars=1000,
            final_chars=200,
            original_files=5,
            final_files=1,
            items=[TruncationItem(kind="chars", details="Stopped at limit")],
        ),
        redaction=RedactionReport(enabled=True, found=True),
        ignored_paths=["docs/readme.md"],
        included_paths=["a.py"],
    )
    fingerprint = Fingerprint(value="a" * 64)
    prior_digest = PriorDigest(
        prior_fingerprint=Fingerprint(value="b" * 64),
        findings=[
            PriorFinding(
                finding_id="f-1",
                path="a.py",
                line_range="10-12",
                title="Existing issue",
                severity="medium",
            )
        ],
        summary_hint="Previous review context",
    )

    request = build_agent_request(
        config=config,
        prepared=prepared,
        fingerprint=fingerprint,
        prior_digest=prior_digest,
    )

    assert "## Schema" in request.prompt
    assert "Return ONLY a JSON object." in request.prompt
    assert "Truncation occurred: True." in request.prompt
    assert "Redaction occurred: True." in request.prompt
    assert "Some strings were redacted as [REDACTED]." in request.prompt
    assert "## Prior Digest" in request.prompt
    assert "Previous review context" in request.prompt
    assert "[medium] a.py:10-12 Existing issue (f-1)" in request.prompt
    assert "Extra skills to apply: security, python." in request.prompt
    assert request.meta.fingerprint == fingerprint
    assert request.meta.redaction_found is True
    assert request.meta.verbosity == "high"
    assert request.meta.skills == ["security", "python"]


def test_build_agent_request_without_prior_or_flags() -> None:
    """Prompt omits optional sections when no prior digest/flags exist."""
    config = AppConfig(
        agent=AgentConfig(verbosity="low", skills=[]),
    )
    prepared = PreparedDiff(
        prepared_diff="diff --git a/a.py b/a.py\n",
        truncation=TruncationReport(truncated=False),
        redaction=RedactionReport(enabled=True, found=False),
        ignored_paths=[],
        included_paths=["a.py"],
    )

    request = build_agent_request(
        config=config,
        prepared=prepared,
        fingerprint=Fingerprint(value="c" * 64),
    )

    assert "## Prior Digest" not in request.prompt
    assert "Truncation occurred: False." in request.prompt
    assert "Redaction occurred: False." in request.prompt
    assert "Extra skills to apply" not in request.prompt
