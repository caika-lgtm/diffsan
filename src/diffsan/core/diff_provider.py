"""Diff acquisition for CI pipelines."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from typing import Final

from diffsan.contracts.errors import ErrorCode, ReviewerError
from diffsan.contracts.models import DiffBundle, DiffFile, DiffRef, DiffSource

_DIFF_HEADER_RE: Final[re.Pattern[str]] = re.compile(r"^diff --git a/(.+?) b/(.+)$")


@dataclass(frozen=True, slots=True)
class CiDiffContext:
    """GitLab CI variables needed to compute MR diff text."""

    target_branch: str
    source_branch: str | None
    base_sha: str | None
    head_sha: str


def get_diff(*, ci: bool) -> DiffBundle:
    """Fetch diff text for current run context."""
    if not ci:
        raise ReviewerError(
            "Diff retrieval currently supports CI mode only",
            error_code=ErrorCode.DIFF_FETCH_FAILED,
            context={"mode": "standalone"},
        )

    context = _read_ci_context()
    raw_diff = _run_git_diff(context)
    files = _parse_files(raw_diff)
    return DiffBundle(
        source=DiffSource(
            kind="git-diff",
            ref=DiffRef(
                target_branch=context.target_branch,
                source_branch=context.source_branch,
                base_sha=context.base_sha,
                head_sha=context.head_sha,
            ),
        ),
        raw_diff=raw_diff,
        files=files,
    )


def _read_ci_context() -> CiDiffContext:
    target_branch = os.getenv("CI_MERGE_REQUEST_TARGET_BRANCH_NAME")
    if not target_branch:
        raise ReviewerError(
            "Missing CI variable for target branch",
            error_code=ErrorCode.DIFF_FETCH_FAILED,
            context={"missing_env": "CI_MERGE_REQUEST_TARGET_BRANCH_NAME"},
        )

    head_sha = os.getenv("CI_COMMIT_SHA")
    if not head_sha:
        raise ReviewerError(
            "Missing CI variable for head commit SHA",
            error_code=ErrorCode.DIFF_FETCH_FAILED,
            context={"missing_env": "CI_COMMIT_SHA"},
        )

    return CiDiffContext(
        target_branch=target_branch,
        source_branch=os.getenv("CI_MERGE_REQUEST_SOURCE_BRANCH_NAME"),
        base_sha=os.getenv("CI_MERGE_REQUEST_DIFF_BASE_SHA"),
        head_sha=head_sha,
    )


def _run_git_diff(context: CiDiffContext) -> str:
    candidates = [f"origin/{context.target_branch}", context.target_branch]
    last_error: ReviewerError | None = None
    for target_ref in candidates:
        command = ["git", "diff", "--no-color", f"{target_ref}...{context.head_sha}"]
        try:
            result = subprocess.run(
                command,
                check=False,
                text=True,
                capture_output=True,
            )
        except OSError as exc:
            raise ReviewerError(
                "Failed to execute git diff",
                error_code=ErrorCode.DIFF_FETCH_FAILED,
                cause=exc,
                context={"command": " ".join(command)},
            ) from exc

        if result.returncode == 0:
            return result.stdout

        last_error = ReviewerError(
            f"git diff failed for target ref '{target_ref}'",
            error_code=ErrorCode.DIFF_FETCH_FAILED,
            cause=result.stderr.strip() or "unknown git error",
            context={
                "command": " ".join(command),
                "returncode": result.returncode,
            },
        )

    assert last_error is not None
    raise last_error


def _parse_files(raw_diff: str) -> list[DiffFile]:
    files: list[DiffFile] = []
    active: DiffFile | None = None
    for line in raw_diff.splitlines():
        header_match = _DIFF_HEADER_RE.match(line)
        if header_match:
            path_a, path_b = header_match.groups()
            path = path_b if path_b != "/dev/null" else path_a
            active = DiffFile(path=path)
            files.append(active)
            continue
        if active is None:
            continue
        if line.startswith("Binary files ") or line.startswith("GIT binary patch"):
            active.is_binary = True
            continue
        if line.startswith("+++ ") or line.startswith("--- "):
            continue
        if line.startswith("+"):
            active.additions += 1
            continue
        if line.startswith("-"):
            active.deletions += 1

    return files
