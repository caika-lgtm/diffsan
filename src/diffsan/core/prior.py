"""Prior review digest extraction and embedding helpers."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from typing import TYPE_CHECKING, Any

from diffsan.contracts.models import (
    Finding,
    Fingerprint,
    PriorDigest,
    PriorFinding,
    ReviewOutput,
)

if TYPE_CHECKING:
    from diffsan.core.gitlab import GitLabClient

_MAX_PRIOR_FINDINGS = 50
_MAX_SUMMARY_HINT_CHARS = 240
_MAX_TITLE_CHARS = 120
_PRIOR_DIGEST_MARKER_RE = re.compile(
    r"<!--\s*diffsan:prior_digest:([A-Za-z0-9+/=]+)\s*-->"
)
_FINGERPRINT_MARKER_RE = re.compile(r"<!--\s*diffsan:fingerprint:([^\n>]+?)\s*-->")
_FINGERPRINT_RE = re.compile(r"\*\*Fingerprint:\*\*\s*`([^`]+)`")


def get_prior_digest(
    *,
    client: GitLabClient,
    summary_note_tag: str,
) -> PriorDigest | None:
    """Fetch MR notes and extract the newest usable prior digest."""
    notes_result = client.list_notes()
    payload = notes_result.payload
    if not isinstance(payload, list):
        return None

    notes = [item for item in payload if isinstance(item, dict)]
    return extract_prior_digest(notes=notes, summary_note_tag=summary_note_tag)


def extract_prior_digest(
    *,
    notes: list[dict[str, Any]],
    summary_note_tag: str,
) -> PriorDigest | None:
    """Extract prior digest from tagged diffsan notes, newest first."""
    tagged_notes = _tagged_diffsan_notes(notes, summary_note_tag)
    for note in tagged_notes:
        body = note.get("body")
        if not isinstance(body, str):
            continue
        digest = _parse_digest_from_note_body(body)
        if digest is not None:
            return digest

    return None


def build_embedded_prior_digest(review: ReviewOutput) -> PriorDigest:
    """Build compact digest data for embedding in summary notes."""
    findings = [
        _to_prior_finding(finding) for finding in review.findings[:_MAX_PRIOR_FINDINGS]
    ]
    summary_hint = _summary_hint(review.summary_markdown)
    return PriorDigest(
        prior_fingerprint=review.meta.fingerprint,
        findings=findings,
        summary_hint=summary_hint,
    )


def encode_prior_digest_marker(prior_digest: PriorDigest | None) -> str:
    """Serialize digest into a compact marker line for summary notes."""
    if prior_digest is None:
        return ""
    if _is_empty_digest(prior_digest):
        return ""

    encoded = base64.b64encode(
        json.dumps(
            prior_digest.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).decode("ascii")
    return f"<!-- diffsan:prior_digest:{encoded} -->"


def encode_fingerprint_marker(fingerprint: Fingerprint | None) -> str:
    """Serialize fingerprint into a marker line for fast prior lookup."""
    if fingerprint is None:
        return ""
    return f"<!-- diffsan:fingerprint:{fingerprint.algo}:{fingerprint.value} -->"


def _tagged_diffsan_notes(
    notes: list[dict[str, Any]],
    summary_note_tag: str,
) -> list[dict[str, Any]]:
    marker = f"<!-- diffsan:{summary_note_tag} -->"
    tagged = []
    for note in notes:
        body = note.get("body")
        if isinstance(body, str) and marker in body:
            tagged.append(note)

    return sorted(tagged, key=_note_sort_key, reverse=True)


def _note_sort_key(note: dict[str, Any]) -> tuple[int, str]:
    note_id = note.get("id")
    id_value = note_id if isinstance(note_id, int) else 0
    timestamp = note.get("updated_at") or note.get("created_at") or ""
    time_value = timestamp if isinstance(timestamp, str) else ""
    return id_value, time_value


def _parse_digest_from_note_body(body: str) -> PriorDigest | None:
    marker_match = _PRIOR_DIGEST_MARKER_RE.search(body)
    if marker_match is not None:
        parsed = _parse_marker_payload(marker_match.group(1))
        if parsed is not None:
            return parsed

    fingerprint = _parse_fingerprint_marker(body) or _parse_fingerprint(body)
    if fingerprint is None:
        return None
    return PriorDigest(prior_fingerprint=fingerprint, findings=[], summary_hint=None)


def _parse_marker_payload(encoded_payload: str) -> PriorDigest | None:
    try:
        decoded_bytes = base64.b64decode(encoded_payload, validate=True)
    except (ValueError, binascii.Error):
        return None

    try:
        payload = json.loads(decoded_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None

    try:
        digest = PriorDigest.model_validate(payload)
    except Exception:  # pragma: no cover - pydantic details are not important here
        return None
    return digest if not _is_empty_digest(digest) else None


def _parse_fingerprint(body: str) -> Fingerprint | None:
    match = _FINGERPRINT_RE.search(body)
    if match is None:
        return None
    return _parse_fingerprint_value(match.group(1))


def _parse_fingerprint_marker(body: str) -> Fingerprint | None:
    marker_match = _FINGERPRINT_MARKER_RE.search(body)
    if marker_match is None:
        return None
    return _parse_fingerprint_value(marker_match.group(1))


def _parse_fingerprint_value(raw: str) -> Fingerprint | None:
    value_text = raw.strip()
    algo, _, value = value_text.partition(":")
    if not algo or not value:
        return None
    return Fingerprint(algo=algo, value=value)


def _to_prior_finding(finding: Finding) -> PriorFinding:
    line_start = min(finding.line_start, finding.line_end)
    line_end = max(finding.line_start, finding.line_end)
    line_range = (
        str(line_start) if line_start == line_end else f"{line_start}-{line_end}"
    )
    title = _finding_title(finding.body_markdown)
    finding_id = finding.finding_id or _fallback_finding_id(
        path=finding.path,
        line_range=line_range,
        title=title,
        severity=finding.severity,
    )
    return PriorFinding(
        finding_id=finding_id,
        path=finding.path,
        line_range=line_range,
        title=title,
        severity=finding.severity,
    )


def _finding_title(markdown: str) -> str:
    lines = [line.strip() for line in markdown.splitlines() if line.strip()]
    text = lines[0] if lines else "Untitled finding"
    compact = re.sub(r"\s+", " ", text).strip(" -*#`")
    compact = compact or "Untitled finding"
    if len(compact) <= _MAX_TITLE_CHARS:
        return compact
    return compact[: _MAX_TITLE_CHARS - 3].rstrip() + "..."


def _fallback_finding_id(
    *,
    path: str,
    line_range: str,
    title: str,
    severity: str,
) -> str:
    digest = hashlib.sha256(
        f"{path}|{line_range}|{severity}|{title}".encode()
    ).hexdigest()
    return f"f-{digest[:12]}"


def _summary_hint(summary_markdown: str) -> str | None:
    lines = [line.strip() for line in summary_markdown.splitlines() if line.strip()]
    if not lines:
        return None

    first_line = re.sub(r"\s+", " ", lines[0]).strip(" -*#`")
    if not first_line:
        return None
    if len(first_line) <= _MAX_SUMMARY_HINT_CHARS:
        return first_line
    return first_line[: _MAX_SUMMARY_HINT_CHARS - 3].rstrip() + "..."


def _is_empty_digest(digest: PriorDigest) -> bool:
    return (
        digest.prior_fingerprint is None
        and not digest.findings
        and (digest.summary_hint is None or not digest.summary_hint.strip())
    )
