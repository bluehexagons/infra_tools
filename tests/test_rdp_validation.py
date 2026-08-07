"""Tests for xRDP login prerequisite validation."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.config import SetupConfig
from lib.validation import validate_rdp_settings


class TestValidateRdpSettings(unittest.TestCase):
    def test_rdp_requires_a_password(self) -> None:
        config = SetupConfig(
            host="agent-vm",
            username="agent",
            system_type="workstation_dev",
            enable_rdp=True,
        )

        with self.assertRaisesRegex(ValueError, "--rdp requires --password"):
            validate_rdp_settings(config)

    def test_rdp_accepts_a_non_root_user_with_password(self) -> None:
        config = SetupConfig(
            host="agent-vm",
            username="agent",
            system_type="workstation_dev",
            enable_rdp=True,
            password="correct-horse-battery-staple",
        )

        validate_rdp_settings(config)

    def test_rdp_rejects_root(self) -> None:
        config = SetupConfig(
            host="agent-vm",
            username="root",
            system_type="workstation_dev",
            enable_rdp=True,
            password="correct-horse-battery-staple",
        )

        with self.assertRaisesRegex(ValueError, "cannot be used with the root"):
            validate_rdp_settings(config)


if __name__ == "__main__":
    unittest.main()
