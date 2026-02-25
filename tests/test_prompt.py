"""Tests for prompt construction."""

from diffsan.contracts.errors import ErrorCode, ReviewerError
from diffsan.contracts.models import (
    AgentConfig,
    AppConfig,
    Fingerprint,
    PreparedDiff,
    PriorDigest,
    PriorFinding,
    PriorInlineComment,
    PriorSummary,
    RedactionReport,
    TruncationItem,
    TruncationReport,
)
from diffsan.core.prompt import (
    _bounded_excerpt,
    build_agent_request,
    build_json_repair_prompt,
)


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
        summaries=[
            PriorSummary(note_id=10, text="### Prior Summary A\n- item A"),
            PriorSummary(note_id=9, text="### Prior Summary B\n- item B"),
        ],
        inline_comments=[
            PriorInlineComment(
                discussion_id="d-1",
                note_id=101,
                path="a.py",
                line=10,
                resolved=False,
                body="Please validate this branch.",
            ),
            PriorInlineComment(
                discussion_id="d-2",
                note_id=202,
                path="a.py",
                line=12,
                resolved=True,
                body="Fixed in follow-up commit.",
            ),
        ],
    )

    request = build_agent_request(
        config=config,
        prepared=prepared,
        fingerprint=fingerprint,
        prior_digest=prior_digest,
    )

    assert "## Schema" in request.prompt
    assert "Return ONLY a JSON object." in request.prompt
    assert "Do not include planning text, analysis, or explanations." in request.prompt
    assert (
        "The first character must be '{' and the last character must be '}'."
        in request.prompt
    )
    assert '"title": "AgentReviewOutput"' in request.prompt
    assert '"meta"' not in request.prompt
    assert "Truncation occurred: True." in request.prompt
    assert "Redaction occurred: True." in request.prompt
    assert "Some strings were redacted as [REDACTED]." in request.prompt
    assert "## Prior Digest" in request.prompt
    assert "Previous review context" in request.prompt
    assert "[medium] a.py:10-12 Existing issue (f-1)" in request.prompt
    assert "Prior summaries:" in request.prompt
    assert "### Prior Summary A" in request.prompt
    assert "### Prior Summary B" in request.prompt
    assert (
        "Prior inline discussion comments (includes resolved and unresolved):"
        in request.prompt
    )
    assert (
        "[unresolved] [d-1/101] a.py:10 Please validate this branch." in request.prompt
    )
    assert "[resolved] [d-2/202] a.py:12 Fixed in follow-up commit." in request.prompt
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


def test_build_json_repair_prompt_includes_errors_and_excerpt() -> None:
    """Repair prompt contains strict instructions, errors, and bounded output."""
    config = AppConfig()
    validation_error = ReviewerError(
        "Agent output failed schema validation",
        error_code=ErrorCode.AGENT_OUTPUT_INVALID,
        context={
            "errors": [
                {"loc": ("findings", 0, "line_start"), "msg": "Field required"},
                {"loc": ("meta", "agent"), "msg": "Input should be a valid string"},
            ]
        },
    )
    previous_output = "x" * 3000

    prompt = build_json_repair_prompt(
        config=config,
        validation_error=validation_error,
        previous_output=previous_output,
    )

    assert "You produced invalid output." in prompt
    assert "Return ONLY a corrected JSON object" in prompt
    assert "Do not include planning text, analysis, or explanations." in prompt
    assert (
        "The first character must be '{' and the last character must be '}'." in prompt
    )
    assert "- meta: object" not in prompt
    assert "- findings.0.line_start: Field required" in prompt
    assert "- meta.agent: Input should be a valid string" in prompt
    assert "...[truncated]..." in prompt


def test_build_json_repair_prompt_falls_back_to_error_message() -> None:
    """When structured errors are unusable, prompt falls back to base message."""
    config = AppConfig()
    validation_error = ReviewerError(
        "Agent output failed schema validation",
        error_code=ErrorCode.AGENT_OUTPUT_INVALID,
        context={"errors": [123, {"loc": ("meta",), "msg": 7}]},
    )

    prompt = build_json_repair_prompt(
        config=config,
        validation_error=validation_error,
        previous_output="   ",
    )

    assert "- Agent output failed schema validation" in prompt
    assert "Previous output excerpt:\n<<<\n<empty>\n>>>" in prompt


def test_build_json_repair_prompt_handles_root_error_locations() -> None:
    """Non-path and empty-path locations are rendered as <root>."""
    config = AppConfig()
    validation_error = ReviewerError(
        "Agent output failed schema validation",
        error_code=ErrorCode.AGENT_OUTPUT_INVALID,
        context={
            "errors": [
                {"loc": "plain-string-loc", "msg": "bad loc"},
                {"loc": [{}], "msg": "empty path"},
            ]
        },
    )

    prompt = build_json_repair_prompt(
        config=config,
        validation_error=validation_error,
        previous_output="{}",
    )

    assert "- <root>: bad loc" in prompt
    assert "- <root>: empty path" in prompt


def test_bounded_excerpt_short_budget_returns_marker_prefix() -> None:
    """Tiny excerpt budget returns a truncated marker prefix."""
    excerpt = _bounded_excerpt("abcdef", max_chars=3)
    assert excerpt == "\n.."
