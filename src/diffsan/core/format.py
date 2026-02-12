"""Formatting helpers for review output and GitLab summary notes."""

from __future__ import annotations

import json

from diffsan.contracts.models import (
    AppConfig,
    Fingerprint,
    PostPlan,
    ReviewOutput,
    TruncationReport,
)


def print_summary_markdown(review: ReviewOutput) -> None:
    """Print summary markdown to stdout."""
    print(review.summary_markdown)


def build_post_plan(
    *,
    review: ReviewOutput,
    config: AppConfig,
    fallback_fingerprint: Fingerprint | None,
) -> PostPlan:
    """Build a milestone-3 post plan for MR summary posting."""
    return PostPlan(
        summary_markdown=review.summary_markdown,
        summary_meta_collapsible=_build_summary_meta_collapsible(
            review=review,
            fallback_fingerprint=fallback_fingerprint,
        ),
        discussions=[],
        idempotent_summary=config.gitlab.idempotent_summary,
        prior_summary_note_id=None,
    )


def build_summary_note_body(
    *,
    post_plan: PostPlan,
    summary_note_tag: str,
    truncation: TruncationReport,
    redaction_found: bool,
    include_secret_warning: bool,
) -> str:
    """Render the final markdown body for the summary note."""
    sections: list[str] = [
        post_plan.summary_markdown.strip(),
        f"<!-- diffsan:{summary_note_tag} -->",
        post_plan.summary_meta_collapsible,
        _build_truncation_details_collapsible(truncation),
    ]
    if include_secret_warning and redaction_found:
        sections.append(
            "\n".join(
                [
                    "### Secret Scan Warning",
                    (
                        "Potential secrets were detected and redacted before prompting "
                        "the agent. Raw secret values are intentionally omitted."
                    ),
                ]
            )
        )
    return "\n\n".join(section for section in sections if section.strip()) + "\n"


def _build_summary_meta_collapsible(
    *,
    review: ReviewOutput,
    fallback_fingerprint: Fingerprint | None,
) -> str:
    fingerprint = review.meta.fingerprint or fallback_fingerprint
    fingerprint_text = "unknown"
    if fingerprint is not None:
        fingerprint_text = f"{fingerprint.algo}:{fingerprint.value}"
    lines = [
        "<details><summary>Metadata</summary>",
        "",
        f"- fingerprint: {fingerprint_text}",
        f"- agent: {review.meta.agent}",
    ]
    if review.meta.timings is not None:
        lines.extend(
            [
                f"- duration_ms: {review.meta.timings.duration_ms}",
                f"- started_at: {review.meta.timings.started_at.isoformat()}",
                f"- ended_at: {review.meta.timings.ended_at.isoformat()}",
            ]
        )
    if review.meta.token_usage:
        lines.append(
            f"- token_usage: `{json.dumps(review.meta.token_usage, sort_keys=True)}`"
        )
    lines.extend(
        [
            f"- truncated: {review.meta.truncated}",
            f"- redaction_found: {review.meta.redaction_found}",
            "</details>",
        ]
    )
    return "\n".join(lines)


def _build_truncation_details_collapsible(truncation: TruncationReport) -> str:
    lines = [
        "<details><summary>Truncation details</summary>",
        "",
        f"- truncated: {truncation.truncated}",
        f"- original_chars: {truncation.original_chars}",
        f"- final_chars: {truncation.final_chars}",
        f"- original_files: {truncation.original_files}",
        f"- final_files: {truncation.final_files}",
    ]
    if truncation.items:
        lines.append("- items:")
        for item in truncation.items:
            path = f" `{item.path}`" if item.path else ""
            lines.append(f"  - [{item.kind}]{path} {item.details}")
    lines.append("</details>")
    return "\n".join(lines)
