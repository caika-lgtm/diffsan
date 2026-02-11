"""Additional coverage for small core helpers."""

from diffsan.contracts.models import ReviewMeta, ReviewOutput
from diffsan.core.fingerprint import compute_fingerprint
from diffsan.core.format import print_summary_markdown


def test_compute_fingerprint_is_stable() -> None:
    """Fingerprint should be deterministic for identical input."""
    value_a = compute_fingerprint("same-diff")
    value_b = compute_fingerprint("same-diff")
    value_c = compute_fingerprint("different-diff")

    assert value_a.value == value_b.value
    assert value_a.value != value_c.value


def test_print_summary_markdown_emits_to_stdout(capsys) -> None:
    """Formatter prints review summary to stdout."""
    review = ReviewOutput(
        summary_markdown="### Hello",
        findings=[],
        meta=ReviewMeta(agent="cursor"),
    )

    print_summary_markdown(review)

    captured = capsys.readouterr()
    assert captured.out == "### Hello\n"
