"""Formatting helpers for Milestone 1 output."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from diffsan.contracts.models import ReviewOutput


def print_summary_markdown(review: ReviewOutput) -> None:
    """Print summary markdown to stdout."""
    print(review.summary_markdown)
