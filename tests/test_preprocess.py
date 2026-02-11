"""Tests for diff preprocessing."""

import pytest

from diffsan.contracts.errors import ErrorCode, ReviewerError
from diffsan.contracts.models import (
    AppConfig,
    DiffBundle,
    DiffRef,
    DiffSource,
    LimitsConfig,
    SecretsConfig,
    TruncationConfig,
)
from diffsan.core.preprocess import prepare_diff


def test_prepare_diff_filters_truncates_and_redacts() -> None:
    """Preprocessor applies limits and redaction without leaking raw values."""
    marker = "REDACT_ME_MARKER_12345"
    raw_diff = f"""diff --git a/docs/readme.md b/docs/readme.md
--- a/docs/readme.md
+++ b/docs/readme.md
@@ -1 +1 @@
-old docs
+new docs
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,3 @@
-note = \"{marker}\"
+note = \"{marker}\"
+print(\"ok\")
"""
    config = AppConfig(
        limits=LimitsConfig(max_diff_chars=10_000, max_files=1, max_hunks_per_file=10),
        truncation=TruncationConfig(
            priority_extensions=[".py"],
            depriority_extensions=[".md"],
            include_extensions=None,
            ignore_globs=[],
        ),
        secrets=SecretsConfig(
            enabled=True,
            extra_patterns=[r"REDACT_ME_MARKER_12345"],
        ),
    )
    diff = DiffBundle(
        source=DiffSource(ref=DiffRef(target_branch="main", head_sha="head")),
        raw_diff=raw_diff,
        files=[],
    )

    prepared = prepare_diff(diff, config)

    assert prepared.included_paths == ["src/app.py"]
    assert prepared.truncation.truncated is True
    assert any(item.kind == "file" for item in prepared.truncation.items)
    assert prepared.redaction.found is True
    assert marker not in prepared.prepared_diff
    assert "[REDACTED]" in prepared.prepared_diff
    assert prepared.redaction.matches
    assert all(match.match_sha256 for match in prepared.redaction.matches)


def test_prepare_diff_truncates_hunks_chars_and_respects_filters() -> None:
    """Preprocessor applies ignore/include filters and truncation knobs."""
    raw_diff = """diff --git a/docs/readme.md b/docs/readme.md
--- a/docs/readme.md
+++ b/docs/readme.md
@@ -1 +1 @@
-old docs
+new docs
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-a
+b
@@ -10 +10 @@
-x
+y
"""
    config = AppConfig(
        limits=LimitsConfig(max_diff_chars=40, max_files=5, max_hunks_per_file=1),
        truncation=TruncationConfig(
            priority_extensions=[".py"],
            depriority_extensions=[".md"],
            include_extensions=[".py"],
            ignore_globs=["docs/**"],
        ),
        secrets=SecretsConfig(enabled=False, extra_patterns=[]),
    )
    diff = DiffBundle(
        source=DiffSource(ref=DiffRef(target_branch="main", head_sha="head")),
        raw_diff=raw_diff,
        files=[],
    )

    prepared = prepare_diff(diff, config)

    assert prepared.ignored_paths == ["docs/readme.md"]
    assert prepared.included_paths == ["src/app.py"]
    assert prepared.truncation.truncated is True
    assert any(item.kind == "hunk" for item in prepared.truncation.items)
    assert any(item.kind == "chars" for item in prepared.truncation.items)
    assert prepared.redaction.enabled is False
    assert prepared.redaction.found is False


def test_prepare_diff_invalid_extra_pattern_raises() -> None:
    """Invalid redaction regex should fail with REDACTION_ENGINE_FAILED."""
    diff = DiffBundle(
        source=DiffSource(ref=DiffRef(target_branch="main", head_sha="head")),
        raw_diff="diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-a\n+b\n",
        files=[],
    )
    config = AppConfig(
        secrets=SecretsConfig(enabled=True, extra_patterns=["["]),
    )

    with pytest.raises(ReviewerError) as error:
        prepare_diff(diff, config)

    assert error.value.error_info.error_code == ErrorCode.REDACTION_ENGINE_FAILED
