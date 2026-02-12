"""Tests for summary/post formatting helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from diffsan.contracts.models import (
    AppConfig,
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
