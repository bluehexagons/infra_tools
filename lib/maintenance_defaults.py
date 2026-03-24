"""Shared defaults for maintenance and cleanup tasks."""

from __future__ import annotations

JOURNAL_MAX_USE = "100M"

# Wait up to 5 minutes for apt/dpkg locks to be released before failing.
APT_LOCK_OPTIONS = [
    "-o", "DPkg::Lock::Timeout=300",
]
