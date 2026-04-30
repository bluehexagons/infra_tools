"""Example expensive test guarded by INFRA_TOOLS_RUN_EXPENSIVE.

This module exists primarily to verify the gating mechanism. Tests inside it
should *only* run when the environment variable is set, so the default suite
remains fast. Real expensive tests (e.g. a live Proxmox round-trip) belong
here.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from tests.expensive_support import EXPENSIVE_ENV_VAR, expensive


@expensive("Reserved slot for live Proxmox integration tests")
class TestProxmoxLiveStub(unittest.TestCase):
    """Placeholder to demonstrate the @expensive decorator.

    Real implementations should connect to a Proxmox host (perhaps configured
    via a dedicated env var like PROXMOX_TEST_HOST) and exercise list/start/
    stop/destroy against a throwaway container.
    """

    def test_placeholder(self) -> None:
        # When this runs (INFRA_TOOLS_RUN_EXPENSIVE=1), confirm the gate flag is set.
        self.assertIn(os.environ.get(EXPENSIVE_ENV_VAR, "").lower(),
                      {"1", "true", "yes", "on"})


if __name__ == "__main__":
    unittest.main()
