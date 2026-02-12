"""Formatting helpers for review output and GitLab summary notes."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from diffsan.contracts.models import (
    AppConfig,
    Fingerprint,
    PostPlan,
    ReviewOutput,
    TruncationReport,
)

if TYPE_CHECKING:
    from datetime import datetime

_DEFAULT_NOTE_TIMEZONE = "Asia/Singapore"
_TIMEZONE_ALIASES = {
    "SGT": "Asia/Singapore",
}


def print_summary_markdown(review: ReviewOutput) -> None:
    """Print summary markdown to stdout."""
    print(review.summary_markdown)


def build_post_plan(
    *,
    review: ReviewOutput,
    config: AppConfig,
    fallback_fingerprint: Fingerprint | None,
    note_timezone: str,
    pipeline_id: str | None = None,
) -> PostPlan:
    """Build a milestone-3 post plan for MR summary posting."""
    return PostPlan(
        summary_markdown=review.summary_markdown,
        summary_meta_collapsible=_build_summary_meta_collapsible(
            review=review,
            fallback_fingerprint=fallback_fingerprint,
            note_timezone=note_timezone,
            pipeline_id=pipeline_id,
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
        "## **diffsan** Summary",
        "<sub><em>Automated merge request review</em></sub>",
        post_plan.summary_markdown.strip(),
        f"<!-- diffsan:{summary_note_tag} -->",
        post_plan.summary_meta_collapsible,
    ]
    if truncation.truncated:
        sections.append(_build_truncation_details_collapsible(truncation))
    if include_secret_warning and redaction_found:
        sections.append(
            "\n".join(
                [
                    "### **Secret Scan Warning**",
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
    note_timezone: str,
    pipeline_id: str | None,
) -> str:
    fingerprint = review.meta.fingerprint or fallback_fingerprint
    fingerprint_text = "unknown"
    if fingerprint is not None:
        fingerprint_text = f"{fingerprint.algo}:{fingerprint.value}"
    lines = [
        "<details><summary><strong>Metadata</strong></summary>",
        "",
        f"- **Fingerprint:** `{fingerprint_text}`",
        f"- **Agent:** `{review.meta.agent}`",
        f"- **Findings:** `{len(review.findings)}`",
    ]
    if pipeline_id:
        lines.append(f"- **MR pipeline ID:** `{pipeline_id}`")
    if review.meta.timings is not None:
        started_text = _format_datetime_human(
            review.meta.timings.started_at,
            note_timezone,
        )
        ended_text = _format_datetime_human(
            review.meta.timings.ended_at,
            note_timezone,
        )
        duration_text = _format_duration(review.meta.timings.duration_ms)
        lines.extend(
            [
                f"- **Started:** `{started_text}`",
                f"- **Ended:** `{ended_text}`",
                f"- **Duration:** `{duration_text}`",
            ]
        )
    if review.meta.token_usage:
        lines.append(
            "- **Token usage:** "
            f"`{json.dumps(review.meta.token_usage, sort_keys=True)}`"
        )
    lines.extend(
        [
            f"- **Truncated:** `{str(review.meta.truncated).lower()}`",
            f"- **Redaction found:** `{str(review.meta.redaction_found).lower()}`",
            "</details>",
        ]
    )
    return "\n".join(lines)


def _build_truncation_details_collapsible(truncation: TruncationReport) -> str:
    lines = [
        "<details><summary><strong>Truncation details</strong></summary>",
        "",
        f"- **Original chars:** `{truncation.original_chars}`",
        f"- **Final chars:** `{truncation.final_chars}`",
        f"- **Original files:** `{truncation.original_files}`",
        f"- **Final files:** `{truncation.final_files}`",
    ]
    if truncation.items:
        lines.append("- **Items:**")
        for item in truncation.items:
            path = f" `{item.path}`" if item.path else ""
            lines.append(f"  - `[{item.kind}]`{path} {item.details}")
    lines.append("</details>")
    return "\n".join(lines)


def _format_datetime_human(value: datetime, timezone_name: str) -> str:
    timezone, label_override = _resolve_timezone(timezone_name)
    local = value.astimezone(timezone)
    hour = local.strftime("%I").lstrip("0") or "0"
    label = label_override or local.strftime("%Z") or timezone.key
    return f"{local.strftime('%d %b %Y')}, {hour}:{local.strftime('%M%p')} {label}"


def _format_duration(duration_ms: int) -> str:
    if duration_ms < 1_000:
        return f"{duration_ms} ms"
    if duration_ms < 60_000:
        return f"{duration_ms / 1_000:.1f} s"
    minutes = duration_ms // 60_000
    seconds = (duration_ms % 60_000) // 1_000
    return f"{minutes}m {seconds}s"


def _resolve_timezone(timezone_name: str) -> tuple[ZoneInfo, str | None]:
    normalized = timezone_name.strip()
    if not normalized:
        normalized = "SGT"
    upper = normalized.upper()
    zone_name = _TIMEZONE_ALIASES.get(upper, normalized)
    label_override = upper if upper in _TIMEZONE_ALIASES else None
    try:
        return ZoneInfo(zone_name), label_override
    except ZoneInfoNotFoundError:
        return ZoneInfo(_DEFAULT_NOTE_TIMEZONE), "SGT"
