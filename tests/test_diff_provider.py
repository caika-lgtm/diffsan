"""Tests for CI diff retrieval."""

from __future__ import annotations

import subprocess

import pytest

from diffsan.contracts.errors import ErrorCode, ReviewerError
from diffsan.core.diff_provider import get_diff


def test_get_diff_ci_parses_files(monkeypatch: pytest.MonkeyPatch) -> None:
    """CI diff fetch returns bundle and file stats."""
    raw_diff = """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1,2 @@
-print(\"old\")
+print(\"new\")
+print(\"more\")
diff --git a/docs/readme.md b/docs/readme.md
--- a/docs/readme.md
+++ b/docs/readme.md
@@ -1 +1 @@
-old
+new
"""

    monkeypatch.setenv("CI_MERGE_REQUEST_TARGET_BRANCH_NAME", "main")
    monkeypatch.setenv("CI_MERGE_REQUEST_SOURCE_BRANCH_NAME", "feature")
    monkeypatch.setenv("CI_MERGE_REQUEST_DIFF_BASE_SHA", "abc123")
    monkeypatch.setenv("CI_COMMIT_SHA", "def456")

    commands: list[list[str]] = []

    def _run(
        command: list[str],
        *,
        check: bool,
        text: bool,
        capture_output: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert check is False
        assert text is True
        assert capture_output is True
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=raw_diff, stderr="")

    monkeypatch.setattr(subprocess, "run", _run)

    bundle = get_diff(ci=True)

    assert commands == [["git", "diff", "--no-color", "origin/main...def456"]]
    assert bundle.source.ref.target_branch == "main"
    assert bundle.source.ref.source_branch == "feature"
    assert bundle.source.ref.base_sha == "abc123"
    assert bundle.source.ref.head_sha == "def456"
    assert bundle.raw_diff == raw_diff
    assert [item.path for item in bundle.files] == ["src/app.py", "docs/readme.md"]
    assert bundle.files[0].additions == 2
    assert bundle.files[0].deletions == 1


def test_get_diff_missing_ci_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing CI env fails with DIFF_FETCH_FAILED."""
    monkeypatch.delenv("CI_MERGE_REQUEST_TARGET_BRANCH_NAME", raising=False)
    monkeypatch.delenv("CI_COMMIT_SHA", raising=False)

    with pytest.raises(ReviewerError) as error:
        get_diff(ci=True)

    assert error.value.error_info.error_code == ErrorCode.DIFF_FETCH_FAILED
