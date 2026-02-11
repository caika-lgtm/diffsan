"""Diff fingerprinting utilities."""

from __future__ import annotations

import hashlib

from diffsan.contracts.models import Fingerprint


def compute_fingerprint(raw_diff: str) -> Fingerprint:
    """Compute deterministic fingerprint from raw diff text."""
    return Fingerprint(value=hashlib.sha256(raw_diff.encode("utf-8")).hexdigest())
