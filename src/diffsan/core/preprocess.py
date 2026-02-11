"""Prepare diff text for safe and bounded prompting."""

from __future__ import annotations

import fnmatch
import hashlib
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Final

from diffsan.contracts.errors import ErrorCode, ReviewerError
from diffsan.contracts.models import (
    AppConfig,
    DiffBundle,
    PreparedDiff,
    RedactionMatch,
    RedactionReport,
    TruncationItem,
    TruncationReport,
)

_DIFF_HEADER_RE: Final[re.Pattern[str]] = re.compile(r"^diff --git a/(.+?) b/(.+)$")


@dataclass(frozen=True, slots=True)
class _SecretPattern:
    name: str
    pattern: re.Pattern[str]


@dataclass(frozen=True, slots=True)
class _DiffFileBlock:
    path: str
    content: str
    order: int


def prepare_diff(diff: DiffBundle, config: AppConfig) -> PreparedDiff:
    """Apply ignore rules, prioritization, truncation, and secret redaction."""
    blocks = _split_blocks(diff.raw_diff)

    ignored_paths: list[str] = []
    filtered_blocks: list[_DiffFileBlock] = []
    for block in blocks:
        if _should_ignore(block.path, config.truncation.ignore_globs):
            ignored_paths.append(block.path)
            continue
        if not _is_allowed_extension(block.path, config.truncation.include_extensions):
            ignored_paths.append(block.path)
            continue
        filtered_blocks.append(block)

    ranked_blocks = sorted(
        filtered_blocks,
        key=lambda block: (_priority_key(block.path, config), block.order),
    )

    truncation_items: list[TruncationItem] = []
    limited_blocks = ranked_blocks
    if len(ranked_blocks) > config.limits.max_files:
        dropped = ranked_blocks[config.limits.max_files :]
        limited_blocks = ranked_blocks[: config.limits.max_files]
        truncation_items.extend(
            TruncationItem(
                kind="file",
                path=block.path,
                details=f"Dropped due to max_files={config.limits.max_files}",
            )
            for block in dropped
        )

    hunk_limited_blocks: list[_DiffFileBlock] = []
    for block in limited_blocks:
        content, did_truncate = _limit_hunks(
            block.content,
            config.limits.max_hunks_per_file,
        )
        if did_truncate:
            truncation_items.append(
                TruncationItem(
                    kind="hunk",
                    path=block.path,
                    details=(
                        "Dropped hunks due to "
                        f"max_hunks_per_file={config.limits.max_hunks_per_file}"
                    ),
                )
            )
        hunk_limited_blocks.append(
            _DiffFileBlock(path=block.path, content=content, order=block.order)
        )

    prepared_text = "".join(block.content for block in hunk_limited_blocks)
    if len(prepared_text) > config.limits.max_diff_chars:
        prepared_text = prepared_text[: config.limits.max_diff_chars]
        truncation_items.append(
            TruncationItem(
                kind="chars",
                path=None,
                details=f"Stopped at max_diff_chars={config.limits.max_diff_chars}",
            )
        )

    redacted_text, redaction_report = _redact(
        prepared_text,
        enabled=config.secrets.enabled,
        extra_patterns=config.secrets.extra_patterns,
    )

    truncation = TruncationReport(
        truncated=bool(truncation_items),
        original_chars=len(diff.raw_diff),
        final_chars=len(redacted_text),
        original_files=len(blocks),
        final_files=len(hunk_limited_blocks),
        items=truncation_items,
    )

    return PreparedDiff(
        prepared_diff=redacted_text,
        truncation=truncation,
        redaction=redaction_report,
        ignored_paths=sorted(set(ignored_paths)),
        included_paths=[block.path for block in hunk_limited_blocks],
    )


def _split_blocks(raw_diff: str) -> list[_DiffFileBlock]:
    blocks: list[_DiffFileBlock] = []
    current: list[str] = []
    current_path: str | None = None
    order = 0

    for line in raw_diff.splitlines(keepends=True):
        match = _DIFF_HEADER_RE.match(line.rstrip("\n"))
        if match:
            if current_path is not None:
                blocks.append(
                    _DiffFileBlock(
                        path=current_path,
                        content="".join(current),
                        order=order,
                    )
                )
                order += 1
            path_a, path_b = match.groups()
            current_path = path_b if path_b != "/dev/null" else path_a
            current = [line]
            continue
        if current_path is not None:
            current.append(line)

    if current_path is not None:
        blocks.append(
            _DiffFileBlock(path=current_path, content="".join(current), order=order)
        )

    return blocks


def _should_ignore(path: str, ignore_globs: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in ignore_globs)


def _is_allowed_extension(path: str, include_extensions: list[str] | None) -> bool:
    if include_extensions is None:
        return True
    ext = PurePosixPath(path).suffix
    return ext in include_extensions


def _priority_key(path: str, config: AppConfig) -> int:
    ext = PurePosixPath(path).suffix
    if ext in config.truncation.priority_extensions:
        rank = 0
    elif ext in config.truncation.depriority_extensions:
        rank = 2
    else:
        rank = 1
    return rank


def _limit_hunks(block: str, max_hunks: int) -> tuple[str, bool]:
    lines = block.splitlines(keepends=True)
    hunk_starts = [index for index, line in enumerate(lines) if line.startswith("@@ ")]
    if len(hunk_starts) <= max_hunks:
        return block, False
    cut_starts = hunk_starts[:max_hunks]
    end_indexes = [*hunk_starts[1:], len(lines)]
    kept_ranges = list(zip(cut_starts, end_indexes[:max_hunks], strict=True))
    prefix_end = cut_starts[0]
    kept = lines[:prefix_end]
    for start, end in kept_ranges:
        kept.extend(lines[start:end])
    return "".join(kept), True


def _redact(
    prepared_text: str,
    *,
    enabled: bool,
    extra_patterns: list[str],
) -> tuple[str, RedactionReport]:
    if not enabled:
        return prepared_text, RedactionReport(enabled=False, found=False)

    patterns = _build_secret_patterns(extra_patterns)
    matches: list[RedactionMatch] = []
    current_path: str | None = None
    redacted_lines: list[str] = []
    for line_no, line in enumerate(prepared_text.splitlines(keepends=True), start=1):
        header_match = _DIFF_HEADER_RE.match(line.rstrip("\n"))
        if header_match:
            path_a, path_b = header_match.groups()
            current_path = path_b if path_b != "/dev/null" else path_a

        redacted_line = line
        for secret_pattern in patterns:
            redacted_line = _apply_redaction_pattern(
                redacted_line,
                secret_pattern=secret_pattern,
                matches=matches,
                path=current_path,
                line_no=line_no,
            )
        redacted_lines.append(redacted_line)

    report = RedactionReport(
        enabled=True,
        found=bool(matches),
        matches=matches,
    )
    return "".join(redacted_lines), report


def _build_secret_patterns(extra_patterns: list[str]) -> list[_SecretPattern]:
    patterns: list[tuple[str, str]] = [
        ("AWS_ACCESS_KEY_ID", r"\bAKIA[0-9A-Z]{16}\b"),
        ("GITHUB_TOKEN", r"\bgh[pousr]_[A-Za-z0-9]{36,255}\b"),
        ("PRIVATE_KEY_HEADER", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        (
            "GENERIC_SECRET_ASSIGNMENT",
            r"(?i)\b(?:api[_-]?key|secret|token|password)\b\s*[:=]\s*['\"][^'\"]{8,}['\"]",
        ),
    ]
    patterns.extend(
        (f"EXTRA_PATTERN_{idx + 1}", value) for idx, value in enumerate(extra_patterns)
    )

    compiled: list[_SecretPattern] = []
    for pattern_name, pattern in patterns:
        try:
            compiled.append(_SecretPattern(pattern_name, re.compile(pattern)))
        except re.error as exc:
            raise ReviewerError(
                f"Invalid redaction pattern: {pattern_name}",
                error_code=ErrorCode.REDACTION_ENGINE_FAILED,
                cause=exc,
                context={"pattern_name": pattern_name},
            ) from exc
    return compiled


def _apply_redaction_pattern(
    text: str,
    *,
    secret_pattern: _SecretPattern,
    matches: list[RedactionMatch],
    path: str | None,
    line_no: int,
) -> str:
    return secret_pattern.pattern.sub(
        lambda match: _replace_match(
            match,
            pattern_name=secret_pattern.name,
            matches=matches,
            path=path,
            line_no=line_no,
        ),
        text,
    )


def _replace_match(
    match: re.Match[str],
    *,
    pattern_name: str,
    matches: list[RedactionMatch],
    path: str | None,
    line_no: int,
) -> str:
    token = "[REDACTED]"
    secret = match.group(0)
    matches.append(
        RedactionMatch(
            pattern_name=pattern_name,
            path=path,
            line_hint=line_no,
            match_sha256=hashlib.sha256(secret.encode("utf-8")).hexdigest(),
            match_length=len(secret),
        )
    )
    return token
