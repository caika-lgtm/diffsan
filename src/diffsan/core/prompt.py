"""Prompt construction for agent execution."""

from __future__ import annotations

import json
from typing import Final

from diffsan.contracts.models import (
    AgentRequest,
    AgentRequestMeta,
    AppConfig,
    Fingerprint,
    PreparedDiff,
    PriorDigest,
    ReviewOutput,
)

_SYSTEM_TASK: Final[str] = (
    "You are diffsan, an AI code reviewer for merge request diffs. "
    "Focus on correctness and security, then high-impact maintainability issues."
)

_JSON_RULES: Final[str] = "\n".join(
    [
        "Return ONLY a JSON object.",
        "Do not wrap the JSON in markdown or backticks.",
        "Do not include any text before or after the JSON.",
        "Use only allowed enum values for severity and category.",
    ]
)


def build_agent_request(
    *,
    config: AppConfig,
    prepared: PreparedDiff,
    fingerprint: Fingerprint,
    prior_digest: PriorDigest | None = None,
) -> AgentRequest:
    """Create the prompt and metadata for one agent attempt."""
    schema = ReviewOutput.model_json_schema()
    sections = [
        "## Role",
        _SYSTEM_TASK,
        "",
        "## Output Rules",
        _JSON_RULES,
        "",
        "## Schema",
        json.dumps(schema, indent=2, sort_keys=True),
        "",
        "## Review Guidance",
        _review_guidance(config),
        "",
        "## Context Flags",
        _context_flags(prepared),
    ]
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
    if prior_digest.summary_hint:
        lines.append(f"Summary hint: {prior_digest.summary_hint}")
    return "\n".join(lines)
