"""Tests for common setup steps."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from common.common_steps import CONTROL_PLANE_PACKAGES, update_and_upgrade_packages
from lib.config import SetupConfig


class TestUpdateAndUpgradePackages(unittest.TestCase):
    @patch("common.common_steps.run")
    def test_updates_and_upgrades_packages(self, mock_run):
        order = []

        def run_side_effect(command, *_args, **_kwargs):
            order.append(command)
            return MagicMock(returncode=0)

        mock_run.side_effect = run_side_effect

        update_and_upgrade_packages(SetupConfig(host="testhost", username="testuser", system_type="server_lite"))

        self.assertEqual(order[0], "apt-get update -qq")
        self.assertEqual(order[1], "apt-get upgrade -y -qq")
        self.assertEqual(order[2], "apt-get autoremove -y -qq")


class TestControlPlanePackages(unittest.TestCase):
    def test_uses_debian_trixie_dns_package_name(self):
        self.assertIn("bind9-dnsutils", CONTROL_PLANE_PACKAGES)
        self.assertNotIn("dnsutils", CONTROL_PLANE_PACKAGES)


if __name__ == "__main__":
    unittest.main()
