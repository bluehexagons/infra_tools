"""Helpers for marking tests that should not run with the default suite.

Tests decorated with :func:`expensive` are skipped unless the user explicitly
opts in with ``INFRA_TOOLS_RUN_EXPENSIVE=1`` in the environment. This keeps the
default ``python3 -m unittest discover -s tests`` run fast and free of
side-effects (network, real Proxmox hosts, etc.) while still allowing those
tests to be exercised on demand.

Usage:
    from tests.expensive_support import expensive

    @expensive("Talks to a real Proxmox host over SSH")
    class TestRealProxmox(unittest.TestCase):
        ...

To run expensive tests:
    INFRA_TOOLS_RUN_EXPENSIVE=1 python3 -m unittest discover -s tests
"""

from __future__ import annotations

import os
import unittest


EXPENSIVE_ENV_VAR = "INFRA_TOOLS_RUN_EXPENSIVE"


def expensive_tests_enabled() -> bool:
    """Return True if the user opted in to expensive tests."""
    value = os.environ.get(EXPENSIVE_ENV_VAR, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def expensive(reason: str = "expensive test"):
    """Skip the wrapped test/class unless ``INFRA_TOOLS_RUN_EXPENSIVE`` is set."""
    return unittest.skipUnless(
        expensive_tests_enabled(),
        f"{reason} (set {EXPENSIVE_ENV_VAR}=1 to run)",
    )
