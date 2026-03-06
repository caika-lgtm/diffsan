"""Prompt construction for agent execution."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import TYPE_CHECKING, Final

from diffsan.contracts.models import (
    AgentRequest,
    AgentRequestMeta,
    AgentReviewOutput,
    AppConfig,
    Fingerprint,
    PreparedDiff,
    PriorDigest,
)

if TYPE_CHECKING:
    from diffsan.contracts.errors import ReviewerError

_SYSTEM_TASK: Final[str] = (
    "You are diffsan, an AI code reviewer for merge request diffs. "
    "Focus on correctness and security, then high-impact maintainability issues."
)

_JSON_RULES: Final[str] = "\n".join(
    [
        "Return ONLY a JSON object.",
        "Do not wrap the JSON in markdown or backticks.",
        "Do not include any text before or after the JSON.",
        "Do not include planning text, analysis, or explanations.",
        "The first character must be '{' and the last character must be '}'.",
        "Use only allowed enum values for severity and category.",
    ]
)

_REPAIR_SCHEMA_SUMMARY: Final[str] = "\n".join(
    [
        "Top-level object fields:",
        "- summary_markdown: string",
        "- findings: array of finding objects",
        "",
        "Each finding must include:",
        "- severity: info|low|medium|high|critical",
        (
            "- category: correctness|security|performance|maintainability|style|"
            "testing|docs|other"
        ),
        "- path: string",
        "- line_start: integer",
        "- line_end: integer",
        "- body_markdown: string",
        "- suggested_patch: optional object(format, content)",
    ]
)
_MAX_REPAIR_ERROR_LINES: Final[int] = 10
_MAX_REPAIR_OUTPUT_EXCERPT_CHARS: Final[int] = 2_000


def build_agent_request(
    *,
    config: AppConfig,
    prepared: PreparedDiff,
    fingerprint: Fingerprint,
    prior_digest: PriorDigest | None = None,
) -> AgentRequest:
    """Create the prompt and metadata for one agent attempt."""
    sections = ["## Role", _SYSTEM_TASK]
    if config.agent.agent == "cursor":
        schema = AgentReviewOutput.model_json_schema()
        sections.extend(
            [
                "",
                "## Output Rules",
                _JSON_RULES,
                "",
                "## Schema",
                json.dumps(schema, indent=2, sort_keys=True),
            ]
        )
    sections.extend(
        [
            "",
            "## Review Guidance",
            _review_guidance(config),
            "",
            "## Context Flags",
            _context_flags(prepared),
        ]
    )
    if prior_digest is not None:
        sections.extend(["", "## Prior Digest", _prior_digest_text(prior_digest)])
    sections.extend(["", "## Prepared Diff", prepared.prepared_diff])
    prompt = "\n".join(sections).strip() + "\n"
    return AgentRequest(
        prompt=prompt,
        meta=AgentRequestMeta(
            fingerprint=fingerprint,
            truncation=prepared.truncation,
            redaction_found=prepared.redaction.found,
            agent=config.agent.agent,
            verbosity=config.agent.verbosity,
            skills=config.agent.skills,
        ),
    )


def build_json_repair_prompt(
    *,
    config: AppConfig,
    validation_error: ReviewerError,
    previous_output: str,
) -> str:
    """Create a strict repair prompt when agent JSON parse/validation fails."""
    error_lines = _validation_error_lines(validation_error)
    previous_output_excerpt = _bounded_excerpt(
        previous_output,
        max_chars=_MAX_REPAIR_OUTPUT_EXCERPT_CHARS,
    )
    return (
        "\n".join(
            [
                "You produced invalid output.",
                "",
                config.agent.json_repair_prompt,
                "Return ONLY a corrected JSON object that matches this schema.",
                "Do not include planning text, analysis, or explanations.",
                "The first character must be '{' and the last character must be '}'.",
                "",
                _REPAIR_SCHEMA_SUMMARY,
                "",
                "Validation error summary:",
                *error_lines,
                "",
                "Previous output excerpt:",
                "<<<",
                previous_output_excerpt,
                ">>>",
            ]
        ).strip()
        + "\n"
    )


def _review_guidance(config: AppConfig) -> str:
    lines = [
        "- Keep findings concise and actionable.",
        "- Prefer fewer high-confidence findings over noisy nits.",
        "- Include exact file paths and integer line ranges.",
        "- Avoid repeating prior findings unless the code changed materially.",
        f"- Requested verbosity: {config.agent.verbosity}.",
    ]
    if config.agent.skills:
        lines.append(f"- Extra skills to apply: {', '.join(config.agent.skills)}.")
    return "\n".join(lines)


def _context_flags(prepared: PreparedDiff) -> str:
    lines = [
        f"- Truncation occurred: {prepared.truncation.truncated}.",
        f"- Redaction occurred: {prepared.redaction.found}.",
    ]
    if prepared.truncation.truncated:
        lines.append(
            "- In summary_markdown, disclose this as a partial review and include "
            "a <details> section describing truncation."
        )
        lines.append(
            "- Truncation stats: "
            f"{prepared.truncation.original_chars} -> "
            f"{prepared.truncation.final_chars} chars, "
            f"{prepared.truncation.original_files} -> "
            f"{prepared.truncation.final_files} files."
        )
    if prepared.redaction.found:
        lines.append(
            "- Some strings were redacted as [REDACTED]. "
            "Do not attempt to infer hidden secret values."
        )
    return "\n".join(lines)


def _prior_digest_text(prior_digest: PriorDigest) -> str:
    lines = [
        "Do NOT repeat these findings unless the code changed substantially.",
        "Do NOT re-assert unresolved issues.",
    ]
    if prior_digest.prior_fingerprint is not None:
        lines.append(
            "Prior fingerprint: "
            f"{prior_digest.prior_fingerprint.algo}:{prior_digest.prior_fingerprint.value}"
        )
    for finding in prior_digest.findings:
        lines.append(
            "- "
            f"[{finding.severity}] {finding.path}:{finding.line_range} "
            f"{finding.title} ({finding.finding_id})"
        )
    if prior_digest.summaries:
        lines.append("Prior summaries:")
        for summary in prior_digest.summaries:
            note_ref = (
                f"note:{summary.note_id}"
                if summary.note_id is not None
                else "note:unknown"
            )
            lines.append(f"- [{note_ref}]")
            lines.append(summary.text)
    if prior_digest.inline_comments:
        lines.append(
            "Prior inline discussion comments (includes resolved and unresolved):"
        )
        for comment in prior_digest.inline_comments:
            status = "unknown"
            if comment.resolved is True:
                status = "resolved"
            elif comment.resolved is False:
                status = "unresolved"
            location = "<no-position>"
            if comment.path and comment.line is not None:
                location = f"{comment.path}:{comment.line}"
            elif comment.path:
                location = comment.path
            discussion_ref = comment.discussion_id or "unknown"
            note_ref = comment.note_id if comment.note_id is not None else "unknown"
            lines.append(
                f"- [{status}] [{discussion_ref}/{note_ref}] {location} {comment.body}"
            )
    if prior_digest.summary_hint:
        lines.append(f"Summary hint: {prior_digest.summary_hint}")
    return "\n".join(lines)


def _validation_error_lines(validation_error: ReviewerError) -> list[str]:
    errors = validation_error.error_info.context.get("errors")
    if isinstance(errors, list):
        lines: list[str] = []
        for item in errors[:_MAX_REPAIR_ERROR_LINES]:
            if not isinstance(item, dict):
                continue
            location = _format_error_location(item.get("loc"))
            message = item.get("msg")
            if isinstance(message, str):
                lines.append(f"- {location}: {message}")
        if lines:
            return lines

    message = validation_error.error_info.message
    cause = validation_error.error_info.cause
    if cause:
        return [f"- {message} ({cause})"]
    return [f"- {message}"]


def _format_error_location(loc: object) -> str:
    if not isinstance(loc, Sequence) or isinstance(loc, str | bytes):
        return "<root>"

    parts = [str(part) for part in loc if isinstance(part, str | int)]
    if not parts:
        return "<root>"
    return ".".join(parts)


def _bounded_excerpt(text: str, *, max_chars: int) -> str:
    trimmed = text.strip()
    if not trimmed:
        return "<empty>"
    if len(trimmed) <= max_chars:
        return trimmed

    marker = "\n...[truncated]..."
    budget = max_chars - len(marker)
    if budget <= 0:
        return marker[:max_chars]
    return trimmed[:budget] + marker
