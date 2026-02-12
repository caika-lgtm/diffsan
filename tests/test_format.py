"""Tests for summary/post formatting helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from diffsan.contracts.models import (
    AppConfig,
    DiffRef,
    Finding,
    Fingerprint,
    PostPlan,
    ReviewMeta,
    ReviewOutput,
    TimingMeta,
    TruncationItem,
    TruncationReport,
)
from diffsan.core.format import build_post_plan, build_summary_note_body


def test_build_post_plan_includes_metadata_collapsible() -> None:
    """Post plan should include the metadata collapsible block."""
    review = ReviewOutput(
        summary_markdown="### AI Review Summary",
        findings=[],
        meta=ReviewMeta(
            agent="cursor",
            timings=TimingMeta(
                started_at=datetime(2026, 2, 12, 12, 0, 0, tzinfo=UTC),
                ended_at=datetime(2026, 2, 12, 12, 0, 2, tzinfo=UTC),
                duration_ms=2000,
            ),
            token_usage={"prompt_tokens": 10, "completion_tokens": 20},
            truncated=True,
            redaction_found=True,
        ),
    )
    plan = build_post_plan(
        review=review,
        config=AppConfig(),
        fallback_fingerprint=Fingerprint(value="a" * 64),
        note_timezone="SGT",
    )

    assert isinstance(plan, PostPlan)
    assert plan.summary_markdown == "### AI Review Summary"
    assert (
        "<details><summary><strong>Metadata</strong></summary>"
        in plan.summary_meta_collapsible
    )
    assert "**Fingerprint:** `sha256:" in plan.summary_meta_collapsible
    assert "**Findings:** `0`" in plan.summary_meta_collapsible
    assert "**Duration:** `2.0 s`" in plan.summary_meta_collapsible
    assert "**Started:** `12 Feb 2026, 8:00PM SGT`" in plan.summary_meta_collapsible
    assert "**Ended:** `12 Feb 2026, 8:00PM SGT`" in plan.summary_meta_collapsible
    assert "**Token usage:**" in plan.summary_meta_collapsible
    assert "**Truncated:** `true`" in plan.summary_meta_collapsible
    assert "**Redaction found:** `true`" in plan.summary_meta_collapsible


def test_build_summary_note_body_includes_tag_and_truncation_and_warning() -> None:
    """Rendered summary note body includes marker and truncation disclosure."""
    plan = PostPlan(
        summary_markdown="### AI Review Summary\n- Item",
        summary_meta_collapsible=(
            "<details><summary><strong>Metadata</strong></summary>\n\n"
            "- **Agent:** `cursor`\n"
            "</details>"
        ),
        discussions=[],
    )
    truncation = TruncationReport(
        truncated=True,
        original_chars=1000,
        final_chars=250,
        original_files=10,
        final_files=3,
        items=[TruncationItem(kind="file", path="docs/readme.md", details="Dropped")],
    )
    body = build_summary_note_body(
        post_plan=plan,
        summary_note_tag="ai-reviewer",
        truncation=truncation,
        redaction_found=True,
        include_secret_warning=True,
    )

    assert "## **diffsan** Summary" in body
    assert "<sub><em>Automated merge request review</em></sub>" in body
    assert "<!-- diffsan:ai-reviewer -->" in body
    assert "<details><summary><strong>Truncation details</strong></summary>" in body
    assert "**Original chars:** `1000`" in body
    assert "`[file]` `docs/readme.md` Dropped" in body
    assert "### **Secret Scan Warning**" in body


def test_build_summary_note_body_omits_secret_warning_when_disabled() -> None:
    """Secret warning section is optional."""
    body = build_summary_note_body(
        post_plan=PostPlan(summary_markdown="s", summary_meta_collapsible="m"),
        summary_note_tag="ai-reviewer",
        truncation=TruncationReport(),
        redaction_found=True,
        include_secret_warning=False,
    )

    assert "Secret Scan Warning" not in body
    assert "<details><summary><strong>Truncation details</strong></summary>" not in body


def test_build_post_plan_formats_minutes_and_handles_timezone_fallbacks() -> None:
    """Metadata formatting should handle unknown fingerprint and timezone fallback."""
    review = ReviewOutput(
        summary_markdown="summary",
        findings=[],
        meta=ReviewMeta(
            agent="cursor",
            timings=TimingMeta(
                started_at=datetime(2026, 2, 12, 12, 0, 0, tzinfo=UTC),
                ended_at=datetime(2026, 2, 12, 12, 2, 5, tzinfo=UTC),
                duration_ms=125000,
            ),
            token_usage={},
            truncated=False,
            redaction_found=False,
        ),
    )

    plan_invalid_tz = build_post_plan(
        review=review,
        config=AppConfig(),
        fallback_fingerprint=None,
        note_timezone="Invalid/Zone",
    )
    plan_empty_tz = build_post_plan(
        review=review,
        config=AppConfig(),
        fallback_fingerprint=None,
        note_timezone="",
    )

    assert "**Fingerprint:** `unknown`" in plan_invalid_tz.summary_meta_collapsible
    assert "**Duration:** `2m 5s`" in plan_invalid_tz.summary_meta_collapsible
    assert "SGT" in plan_invalid_tz.summary_meta_collapsible
    assert "SGT" in plan_empty_tz.summary_meta_collapsible


def test_build_summary_note_body_truncation_without_items() -> None:
    """Truncation section should render even when item list is empty."""
    body = build_summary_note_body(
        post_plan=PostPlan(summary_markdown="s", summary_meta_collapsible="m"),
        summary_note_tag="ai-reviewer",
        truncation=TruncationReport(
            truncated=True,
            original_chars=20,
            final_chars=10,
            original_files=2,
            final_files=1,
            items=[],
        ),
        redaction_found=False,
        include_secret_warning=False,
    )

    assert "<details><summary><strong>Truncation details</strong></summary>" in body
    assert "**Items:**" not in body


def test_build_post_plan_includes_pipeline_id_when_available() -> None:
    """Pipeline id should be visible in metadata when provided."""
    review = ReviewOutput(
        summary_markdown="summary",
        findings=[],
        meta=ReviewMeta(agent="cursor"),
    )
    plan = build_post_plan(
        review=review,
        config=AppConfig(),
        fallback_fingerprint=None,
        note_timezone="SGT",
        pipeline_id="123456",
    )

    assert "**MR pipeline ID:** `123456`" in plan.summary_meta_collapsible


def test_build_post_plan_maps_discussions_and_unpositioned_findings() -> None:
    """Findings on added lines should map to discussions; others go to summary."""
    review = ReviewOutput(
        summary_markdown="### Summary",
        findings=[
            Finding(
                severity="high",
                category="security",
                path="src/main.py",
                line_start=2,
                line_end=2,
                body_markdown="Use safer parsing.",
            ),
            Finding(
                severity="medium",
                category="correctness",
                path="src/main.py",
                line_start=42,
                line_end=42,
                body_markdown="Potential off-by-one.",
            ),
        ],
        meta=ReviewMeta(agent="cursor"),
    )
    prepared_diff = (
        "diff --git a/src/main.py b/src/main.py\n"
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@ -1,2 +1,3 @@\n"
        " def run():\n"
        "+    return parse_safe()\n"
        "     return parse()\n"
    )

    plan = build_post_plan(
        review=review,
        config=AppConfig(),
        fallback_fingerprint=None,
        note_timezone="SGT",
        prepared_diff=prepared_diff,
        diff_ref=DiffRef(
            base_sha="a" * 40,
            head_sha="b" * 40,
        ),
    )

    assert len(plan.discussions) == 1
    assert plan.discussions[0].path == "src/main.py"
    assert plan.discussions[0].position is not None
    assert plan.discussions[0].position.new_line == 2
    assert "### Unpositioned findings" in plan.summary_markdown
    assert "`src/main.py:42`" in plan.summary_markdown


def test_build_post_plan_unpositioned_section_without_summary_and_long_body() -> None:
    """Unpositioned-only output should render section and truncate long body preview."""
    review = ReviewOutput(
        summary_markdown="",
        findings=[
            Finding(
                severity="medium",
                category="maintainability",
                path="./b/src/main.py",
                line_start=9,
                line_end=9,
                body_markdown=("long " * 80).strip(),
            )
        ],
        meta=ReviewMeta(agent="cursor"),
    )

    plan = build_post_plan(
        review=review,
        config=AppConfig(),
        fallback_fingerprint=None,
        note_timezone="SGT",
    )

    assert plan.discussions == []
    assert plan.summary_markdown.startswith("### Unpositioned findings")
    assert "`src/main.py:9`" in plan.summary_markdown
    assert "..." in plan.summary_markdown


def test_build_post_plan_handles_backslash_hunk_line_and_mismatch_path() -> None:
    """Diff parser ignores '\\' hunk lines and mismatched paths stay unpositioned."""
    review = ReviewOutput(
        summary_markdown="summary",
        findings=[
            Finding(
                severity="low",
                category="style",
                path="a/src/main.py",
                line_start=2,
                line_end=2,
                body_markdown="style nits",
            ),
            Finding(
                severity="low",
                category="style",
                path="src/other.py",
                line_start=2,
                line_end=2,
                body_markdown="won't map",
            ),
        ],
        meta=ReviewMeta(agent="cursor"),
    )
    prepared_diff = (
        "diff --git a/src/main.py b/src/main.py\n"
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@ -1 +1,2 @@\n"
        " old\n"
        "+new\n"
        "\\ No newline at end of file\n"
    )

    plan = build_post_plan(
        review=review,
        config=AppConfig(),
        fallback_fingerprint=None,
        note_timezone="SGT",
        prepared_diff=prepared_diff,
        diff_ref=DiffRef(base_sha="a" * 40, head_sha="b" * 40),
    )

    assert len(plan.discussions) == 1
    assert plan.discussions[0].position is not None
    assert plan.discussions[0].position.new_path == "src/main.py"
    assert plan.discussions[0].position.new_line == 2
    assert "`src/other.py:2`" in plan.summary_markdown
