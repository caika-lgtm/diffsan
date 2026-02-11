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


def test_get_diff_non_ci_mode_rejected() -> None:
    """Standalone mode is not implemented for diff provider."""
    with pytest.raises(ReviewerError) as error:
        get_diff(ci=False)

    assert error.value.error_info.error_code == ErrorCode.DIFF_FETCH_FAILED


def test_get_diff_missing_head_sha(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing CI_COMMIT_SHA fails with DIFF_FETCH_FAILED."""
    monkeypatch.setenv("CI_MERGE_REQUEST_TARGET_BRANCH_NAME", "main")
    monkeypatch.delenv("CI_COMMIT_SHA", raising=False)

    with pytest.raises(ReviewerError) as error:
        get_diff(ci=True)

    assert error.value.error_info.error_code == ErrorCode.DIFF_FETCH_FAILED
    assert error.value.error_info.context.get("missing_env") == "CI_COMMIT_SHA"


def test_get_diff_falls_back_to_local_target_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If origin/<target> fails, provider retries with local target branch name."""
    monkeypatch.setenv("CI_MERGE_REQUEST_TARGET_BRANCH_NAME", "main")
    monkeypatch.setenv("CI_COMMIT_SHA", "deadbeef")

    calls = {"count": 0}

    def _run(
        command: list[str],
        *,
        check: bool,
        text: bool,
        capture_output: bool,
    ) -> subprocess.CompletedProcess[str]:
        _ = check, text, capture_output
        calls["count"] += 1
        if calls["count"] == 1:
            assert command[-1] == "origin/main...deadbeef"
            return subprocess.CompletedProcess(
                command,
                1,
                stdout="",
                stderr="missing origin ref",
            )
        assert command[-1] == "main...deadbeef"
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                "preamble\n"
                "diff --git a/bin.dat b/bin.dat\n"
                "Binary files a/bin.dat and b/bin.dat differ\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", _run)

    bundle = get_diff(ci=True)

    assert calls["count"] == 2
    assert bundle.files[0].path == "bin.dat"
    assert bundle.files[0].is_binary is True


def test_get_diff_wraps_subprocess_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    """OSError during git invocation is normalized into ReviewerError."""
    monkeypatch.setenv("CI_MERGE_REQUEST_TARGET_BRANCH_NAME", "main")
    monkeypatch.setenv("CI_COMMIT_SHA", "deadbeef")

    def _boom(
        command: list[str],
        *,
        check: bool,
        text: bool,
        capture_output: bool,
    ) -> subprocess.CompletedProcess[str]:
        _ = command, check, text, capture_output
        raise OSError("git unavailable")

    monkeypatch.setattr(subprocess, "run", _boom)

    with pytest.raises(ReviewerError) as error:
        get_diff(ci=True)

    assert error.value.error_info.error_code == ErrorCode.DIFF_FETCH_FAILED


def test_get_diff_raises_after_all_target_refs_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both candidate refs failing should raise the final normalized error."""
    monkeypatch.setenv("CI_MERGE_REQUEST_TARGET_BRANCH_NAME", "main")
    monkeypatch.setenv("CI_COMMIT_SHA", "deadbeef")

    def _run(
        command: list[str],
        *,
        check: bool,
        text: bool,
        capture_output: bool,
    ) -> subprocess.CompletedProcess[str]:
        _ = check, text, capture_output
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="fatal: fail")

    monkeypatch.setattr(subprocess, "run", _run)

    with pytest.raises(ReviewerError) as error:
        get_diff(ci=True)

    assert error.value.error_info.error_code == ErrorCode.DIFF_FETCH_FAILED
    assert "target ref 'main'" in error.value.error_info.message
