"""Formatting helpers for review output and GitLab summary notes."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from diffsan.contracts.models import (
    AppConfig,
    DiffRef,
    DiscussionPlan,
    DiscussionPosition,
    Finding,
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
_DIFF_HEADER_RE = re.compile(r"^diff --git a/(.+?) b/(.+)$")
_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


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
    prepared_diff: str | None = None,
    diff_ref: DiffRef | None = None,
    mr_diff_refs: dict[str, object] | None = None,
) -> PostPlan:
    """Build a post plan for summary and inline discussions."""
    position_refs = _resolve_position_refs(diff_ref=diff_ref, mr_diff_refs=mr_diff_refs)
    added_lines_by_path = _collect_added_lines(prepared_diff or "")
    discussions: list[DiscussionPlan] = []
    unpositioned: list[Finding] = []

    for finding in review.findings:
        discussion = _finding_to_discussion(
            finding=finding,
            position_refs=position_refs,
            added_lines_by_path=added_lines_by_path,
        )
        if discussion is None:
            unpositioned.append(finding)
            continue
        discussions.append(discussion)

    return PostPlan(
        summary_markdown=_append_unpositioned_findings(
            review.summary_markdown,
            unpositioned,
        ),
        summary_meta_collapsible=_build_summary_meta_collapsible(
            review=review,
            fallback_fingerprint=fallback_fingerprint,
            note_timezone=note_timezone,
            pipeline_id=pipeline_id,
        ),
        discussions=discussions,
        idempotent_summary=config.gitlab.idempotent_summary,
        prior_summary_note_id=None,
    )


def _resolve_position_refs(
    *,
    diff_ref: DiffRef | None,
    mr_diff_refs: dict[str, object] | None,
) -> tuple[str, str, str] | None:
    base_sha = _coalesce_sha(
        diff_ref.base_sha if diff_ref is not None else None,
        _maybe_str(mr_diff_refs, "base_sha"),
    )
    head_sha = _coalesce_sha(
        diff_ref.head_sha if diff_ref is not None else None,
        _maybe_str(mr_diff_refs, "head_sha"),
    )
    start_sha = _coalesce_sha(
        _maybe_str(mr_diff_refs, "start_sha"),
        base_sha,
    )
    if not (base_sha and head_sha and start_sha):
        return None
    return base_sha, head_sha, start_sha


def _coalesce_sha(*values: str | None) -> str | None:
    for value in values:
        if value is None:
            continue
        normalized = value.strip()
        if normalized:
            return normalized
    return None


def _maybe_str(values: dict[str, object] | None, key: str) -> str | None:
    if not values:
        return None
    value = values.get(key)
    return value if isinstance(value, str) else None


def _collect_added_lines(prepared_diff: str) -> dict[str, set[int]]:
    lines_by_path: dict[str, set[int]] = {}
    current_path: str | None = None
    current_new_line: int | None = None

    for line in prepared_diff.splitlines():
        header_match = _DIFF_HEADER_RE.match(line)
        if header_match:
            path_a, path_b = header_match.groups()
            current_path = _normalize_path(path_b if path_b != "/dev/null" else path_a)
            lines_by_path.setdefault(current_path, set())
            current_new_line = None
            continue

        hunk_match = _HUNK_HEADER_RE.match(line)
        if hunk_match:
            current_new_line = int(hunk_match.group(1))
            continue

        if current_path is None or current_new_line is None:
            continue

        if line.startswith("+") and not line.startswith("+++ "):
            lines_by_path[current_path].add(current_new_line)
            current_new_line += 1
            continue
        if line.startswith("-") and not line.startswith("--- "):
            continue
        if line.startswith(" "):
            current_new_line += 1
            continue
        if line.startswith("\\"):
            continue

    return lines_by_path


def _finding_to_discussion(
    *,
    finding: Finding,
    position_refs: tuple[str, str, str] | None,
    added_lines_by_path: dict[str, set[int]],
) -> DiscussionPlan | None:
    if position_refs is None:
        return None

    normalized_path = _normalize_path(finding.path)
    added_lines = added_lines_by_path.get(normalized_path)
    if not added_lines:
        return None

    line_start = min(finding.line_start, finding.line_end)
    line_end = max(finding.line_start, finding.line_end)

    new_line: int | None = None
    for line_number in range(line_start, line_end + 1):
        if line_number in added_lines:
            new_line = line_number
            break
    if new_line is None:
        return None

    base_sha, head_sha, start_sha = position_refs
    return DiscussionPlan(
        path=normalized_path,
        line_start=line_start,
        line_end=line_end,
        body_markdown=(
            f"**[{finding.category}/{finding.severity}]**\n\n"
            f"{finding.body_markdown.strip()}"
        ),
        position=DiscussionPosition(
            position_type="text",
            base_sha=base_sha,
            head_sha=head_sha,
            start_sha=start_sha,
            new_path=normalized_path,
            new_line=new_line,
        ),
        severity=finding.severity,
        category=finding.category,
    )


def _append_unpositioned_findings(
    summary_markdown: str,
    findings: list[Finding],
) -> str:
    summary = summary_markdown.strip()
    if not findings:
        return summary

    section: list[str] = [
        "### Unpositioned findings",
        (
            "The following findings could not be mapped to a new-line diff position "
            "and were not posted inline."
        ),
    ]
    for finding in findings:
        normalized_path = _normalize_path(finding.path)
        line_start = min(finding.line_start, finding.line_end)
        line_end = max(finding.line_start, finding.line_end)
        line_ref = (
            str(line_start) if line_start == line_end else f"{line_start}-{line_end}"
        )
        section.append(
            f"- **[{finding.category}/{finding.severity}]** "
            f"`{normalized_path}:{line_ref}` "
            f"{_single_line(finding.body_markdown)}"
        )

    section_text = "\n".join(section)
    if not summary:
        return section_text
    return f"{summary}\n\n{section_text}"


def _single_line(markdown: str, limit: int = 160) -> str:
    text = " ".join(part.strip() for part in markdown.splitlines() if part.strip())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3].rstrip()}..."


def _normalize_path(path: str) -> str:
    normalized = path.strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized.startswith("a/") or normalized.startswith("b/"):
        normalized = normalized[2:]
    return normalized


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
