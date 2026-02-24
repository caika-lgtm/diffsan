"""Tests for prior digest extraction and embedding."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from diffsan.contracts.models import (
    Finding,
    Fingerprint,
    PriorDigest,
    ReviewMeta,
    ReviewOutput,
)
from diffsan.core.prior import (
    build_embedded_prior_digest,
    encode_fingerprint_marker,
    encode_prior_digest_marker,
    extract_prior_digest,
    get_prior_digest,
)


def test_build_embedded_prior_digest_compacts_review_findings() -> None:
    """Embedded digest includes fingerprint, compact finding, and hint."""
    review = ReviewOutput(
        summary_markdown="### AI summary",
        findings=[
            Finding(
                finding_id=None,
                severity="high",
                category="security",
                path="src/main.py",
                line_start=10,
                line_end=12,
                body_markdown="Use safer parsing logic.",
            )
        ],
        meta=ReviewMeta(fingerprint=Fingerprint(value="a" * 64)),
    )

    digest = build_embedded_prior_digest(review)

    assert digest.prior_fingerprint is not None
    assert digest.prior_fingerprint.value == "a" * 64
    assert digest.findings[0].path == "src/main.py"
    assert digest.findings[0].line_range == "10-12"
    assert digest.findings[0].title == "Use safer parsing logic."
    assert digest.findings[0].finding_id.startswith("f-")
    assert digest.summary_hint == "AI summary"
    assert digest.summaries == []
    assert digest.inline_comments == []


def test_extract_prior_digest_reads_latest_tagged_note_marker() -> None:
    """Newest tagged note with digest marker should be selected."""
    embedded = build_embedded_prior_digest(
        ReviewOutput(
            summary_markdown="summary",
            findings=[],
            meta=ReviewMeta(fingerprint=Fingerprint(value="b" * 64)),
        )
    )
    marker = encode_prior_digest_marker(embedded)
    notes = [
        {"id": 1, "body": "<!-- diffsan:ai-reviewer -->\nno marker"},
        {"id": 9, "body": f"<!-- diffsan:ai-reviewer -->\n{marker}"},
    ]

    digest = extract_prior_digest(notes=notes, summary_note_tag="ai-reviewer")

    assert digest is not None
    assert digest.prior_fingerprint is not None
    assert digest.prior_fingerprint.value == "b" * 64


def test_extract_prior_digest_falls_back_to_metadata_fingerprint() -> None:
    """Without digest marker, metadata fingerprint is still usable."""
    notes = [
        {
            "id": 5,
            "body": (
                "## **diffsan** Summary\n"
                "<!-- diffsan:ai-reviewer -->\n"
                "- **Fingerprint:** `sha256:cccccccccccccccccccccccccccccccc`"
            ),
        }
    ]

    digest = extract_prior_digest(notes=notes, summary_note_tag="ai-reviewer")

    assert digest is not None
    assert digest.prior_fingerprint is not None
    assert digest.prior_fingerprint.algo == "sha256"
    assert digest.findings == []


def test_extract_prior_digest_reads_fingerprint_marker_when_digest_missing() -> None:
    """Fingerprint marker should be used when no digest marker is present."""
    notes = [
        {
            "id": 5,
            "body": "\n".join(
                [
                    "<!-- diffsan:ai-reviewer -->",
                    "<!-- diffsan:fingerprint:sha256:abababab -->",
                ]
            ),
        }
    ]

    digest = extract_prior_digest(notes=notes, summary_note_tag="ai-reviewer")

    assert digest is not None
    assert digest.prior_fingerprint is not None
    assert digest.prior_fingerprint.algo == "sha256"
    assert digest.prior_fingerprint.value == "abababab"


def test_extract_prior_digest_collects_all_prior_summaries() -> None:
    """All tagged summary notes should contribute prior summary text."""
    notes = [
        {
            "id": 3,
            "body": (
                "<sub>1 finding(s) by `cursor` in 1.0 s</sub>\n\n"
                "### Latest Summary\n- latest item\n\n"
                "<!-- diffsan:ai-reviewer -->\n"
                "<!-- diffsan:fingerprint:sha256:aaa -->"
            ),
        },
        {
            "id": 2,
            "body": (
                "## **diffsan** Summary\n"
                "<sub><em>Automated merge request review</em></sub>\n\n"
                "### Older Summary\n- older item\n\n"
                "<!-- diffsan:ai-reviewer -->"
            ),
        },
    ]

    digest = extract_prior_digest(notes=notes, summary_note_tag="ai-reviewer")

    assert digest is not None
    assert len(digest.summaries) == 2
    assert digest.summaries[0].note_id == 3
    assert digest.summaries[0].text == "### Latest Summary\n- latest item"
    assert digest.summaries[1].note_id == 2
    assert digest.summaries[1].text == "### Older Summary\n- older item"
    assert digest.summary_hint == "Latest Summary"


def test_extract_prior_digest_collects_all_inline_discussion_comments() -> None:
    """All inline comments should be included, regardless of resolved state."""
    discussions = [
        {
            "id": "d-1",
            "resolved": False,
            "position": {"new_path": "a.py", "new_line": 5},
            "notes": [
                {"id": 10, "body": "Unresolved note", "resolved": False},
                {"id": 11, "body": "Resolved reply", "resolved": True},
            ],
        },
        {
            "id": "d-2",
            "resolved": True,
            "notes": [
                {
                    "id": 20,
                    "body": "Inline via note position",
                    "position": {"new_path": "b.py", "new_line": 8},
                }
            ],
        },
        {
            "id": "d-3",
            "resolved": False,
            "notes": [{"id": 30, "body": "General thread without position"}],
        },
    ]

    digest = extract_prior_digest(
        notes=[],
        discussions=discussions,
        summary_note_tag="ai-reviewer",
    )

    assert digest is not None
    assert len(digest.inline_comments) == 3
    assert digest.inline_comments[0].discussion_id == "d-1"
    assert digest.inline_comments[0].path == "a.py"
    assert digest.inline_comments[0].line == 5
    assert digest.inline_comments[0].resolved is False
    assert digest.inline_comments[1].resolved is True
    assert digest.inline_comments[2].discussion_id == "d-2"
    assert digest.inline_comments[2].path == "b.py"
    assert digest.inline_comments[2].line == 8


def test_get_prior_digest_returns_none_when_notes_payload_is_not_list() -> None:
    """API responses that are not note arrays should be ignored."""

    class _FakeClient:
        def list_notes(self):
            return SimpleNamespace(payload={"unexpected": True})

        def list_discussions(self):
            return SimpleNamespace(payload={"unexpected": True})

    assert (
        get_prior_digest(
            client=cast("Any", _FakeClient()),
            summary_note_tag="ai-reviewer",
        )
        is None
    )


def test_get_prior_digest_merges_note_digest_with_discussions() -> None:
    """MR notes and discussions should both contribute to prior context."""

    class _FakeClient:
        def list_notes(self):
            return SimpleNamespace(
                payload=[
                    {
                        "id": 7,
                        "body": (
                            "<sub>1 finding(s) by `cursor` in 1.0 s</sub>\n\n"
                            "### Prior Summary\n- item\n\n"
                            "<!-- diffsan:ai-reviewer -->\n"
                            "<!-- diffsan:fingerprint:sha256:abc -->"
                        ),
                    }
                ]
            )

        def list_discussions(self):
            return SimpleNamespace(
                payload=[
                    {
                        "id": "d-7",
                        "resolved": True,
                        "position": {"new_path": "a.py", "new_line": 3},
                        "notes": [{"id": 70, "body": "Done"}],
                    }
                ]
            )

    digest = get_prior_digest(
        client=cast("Any", _FakeClient()),
        summary_note_tag="ai-reviewer",
    )

    assert digest is not None
    assert digest.prior_fingerprint is not None
    assert digest.prior_fingerprint.value == "abc"
    assert digest.summaries[0].text == "### Prior Summary\n- item"
    assert digest.inline_comments[0].discussion_id == "d-7"
    assert digest.inline_comments[0].resolved is True


def test_extract_prior_digest_skips_invalid_notes_and_uses_older_valid_note() -> None:
    """Parser should continue when newer notes are malformed or missing body text."""
    fallback = build_embedded_prior_digest(
        ReviewOutput(
            summary_markdown="### fallback",
            findings=[],
            meta=ReviewMeta(fingerprint=Fingerprint(value="d" * 64)),
        )
    )
    notes = [
        {
            "id": 12,
            "body": (
                "<!-- diffsan:ai-reviewer -->\n"
                "<!-- diffsan:prior_digest:not@@base64 -->"
            ),
        },
        {"id": 11, "body": None},
        {
            "id": 10,
            "body": (
                "<!-- diffsan:ai-reviewer -->\n"
                "<!-- diffsan:prior_digest:bm90LWpzb24= -->"
            ),
        },
        {
            "id": 9,
            "body": (
                f"<!-- diffsan:ai-reviewer -->\n{encode_prior_digest_marker(fallback)}"
            ),
        },
    ]

    digest = extract_prior_digest(notes=notes, summary_note_tag="ai-reviewer")

    assert digest is not None
    assert digest.prior_fingerprint is not None
    assert digest.prior_fingerprint.value == "d" * 64


def test_extract_prior_digest_returns_none_for_invalid_fingerprint_and_no_marker() -> (
    None
):
    """Tagged notes without parseable marker/fingerprint should return no digest."""
    notes = [
        {
            "id": 1,
            "body": ("<!-- diffsan:ai-reviewer -->\n- **Fingerprint:** `sha256`"),
        }
    ]

    assert extract_prior_digest(notes=notes, summary_note_tag="ai-reviewer") is None


def test_encode_prior_digest_marker_returns_empty_for_none_and_empty_digest() -> None:
    """Marker should not be emitted when there is no useful digest payload."""
    assert encode_prior_digest_marker(None) == ""
    assert encode_prior_digest_marker(PriorDigest()) == ""


def test_encode_fingerprint_marker_returns_expected_comment() -> None:
    """Fingerprint marker should be deterministic and compact."""
    marker = encode_fingerprint_marker(Fingerprint(value="f" * 64))
    assert marker == f"<!-- diffsan:fingerprint:sha256:{'f' * 64} -->"
    assert encode_fingerprint_marker(None) == ""


def test_build_embedded_prior_digest_truncates_title_and_summary_hint() -> None:
    """Long fields should be compacted to configured limits."""
    long_line = "x" * 300
    review = ReviewOutput(
        summary_markdown=long_line,
        findings=[
            Finding(
                finding_id=None,
                severity="medium",
                category="maintainability",
                path="src/very_long.py",
                line_start=5,
                line_end=5,
                body_markdown=("# " + ("A" * 200)),
            )
        ],
        meta=ReviewMeta(fingerprint=Fingerprint(value="e" * 64)),
    )

    digest = build_embedded_prior_digest(review)

    assert digest.summary_hint is not None
    assert digest.summary_hint.endswith("...")
    assert len(digest.summary_hint) <= 240
    assert digest.findings[0].title.endswith("...")
    assert len(digest.findings[0].title) <= 120


def test_build_embedded_prior_digest_handles_empty_summary_after_markdown_trim() -> (
    None
):
    """Heading-only markdown should produce no summary hint."""
    review = ReviewOutput(
        summary_markdown="##   ",
        findings=[],
        meta=ReviewMeta(fingerprint=None),
    )

    digest = build_embedded_prior_digest(review)

    assert digest.summary_hint is None


def test_extract_prior_digest_skips_non_string_note_body() -> None:
    """Tagged notes with non-string body values should be ignored safely."""
    notes = [
        {"id": 2, "body": None},
        {
            "id": 1,
            "body": (
                "<!-- diffsan:ai-reviewer -->\n"
                "- **Fingerprint:** `sha256:ffffffffffffffffffffffffffffffff`"
            ),
        },
    ]

    digest = extract_prior_digest(notes=notes, summary_note_tag="ai-reviewer")

    assert digest is not None
    assert digest.prior_fingerprint is not None


def test_extract_prior_digest_invalid_base64_marker_returns_none() -> None:
    """Invalid base64 marker payload should be ignored."""
    notes = [
        {
            "id": 1,
            "body": (
                "<!-- diffsan:ai-reviewer -->\n<!-- diffsan:prior_digest:AA=A -->"
            ),
        }
    ]

    assert extract_prior_digest(notes=notes, summary_note_tag="ai-reviewer") is None


def test_build_embedded_prior_digest_handles_completely_empty_summary() -> None:
    """Completely empty summary text should keep summary_hint unset."""
    review = ReviewOutput(
        summary_markdown="",
        findings=[],
        meta=ReviewMeta(fingerprint=None),
    )

    digest = build_embedded_prior_digest(review)

    assert digest.summary_hint is None
