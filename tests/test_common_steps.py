"""Tests for common setup steps."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from common.common_steps import (
    CONTROL_PLANE_PACKAGES,
    check_debian_package_sources,
    update_and_upgrade_packages,
)
from lib.config import SetupConfig


class TestUpdateAndUpgradePackages(unittest.TestCase):
    @patch("common.common_steps.check_debian_package_sources")
    @patch("common.common_steps.run")
    def test_updates_and_upgrades_packages(self, mock_run, mock_check_sources):
        order = []

        def run_side_effect(command, *_args, **_kwargs):
            order.append(command)
            return MagicMock(returncode=0)

        mock_run.side_effect = run_side_effect

        with tempfile.TemporaryDirectory() as temporary:
            with patch(
                "common.common_steps.PACKAGE_UPDATE_MARKER",
                os.path.join(temporary, "state", "package-update-complete"),
            ):
                update_and_upgrade_packages(
                    SetupConfig(
                        host="testhost",
                        username="testuser",
                        system_type="server_lite",
                    )
                )

        mock_check_sources.assert_called_once()
        self.assertEqual(
            order[0],
            "apt-get -o DPkg::Lock::Timeout=120 -o Dpkg::Use-Pty=0 update -q",
        )
        expected_dpkg_options = (
            "-o Dpkg::Options::=--force-confdef "
            "-o Dpkg::Options::=--force-confold"
        )
        self.assertEqual(order[1], f"apt-get upgrade -y -qq {expected_dpkg_options}")
        self.assertEqual(order[2], f"apt-get autoremove -y -qq {expected_dpkg_options}")

    @patch("common.common_steps.check_debian_package_sources")
    @patch("common.common_steps.run")
    def test_skips_completed_package_reconciliation(self, mock_run, mock_check_sources):
        with tempfile.TemporaryDirectory() as temporary:
            marker = os.path.join(temporary, "package-update-complete")
            open(marker, "w", encoding="utf-8").close()
            with patch("common.common_steps.PACKAGE_UPDATE_MARKER", marker):
                update_and_upgrade_packages(
                    SetupConfig(
                        host="testhost",
                        username="testuser",
                        system_type="server_lite",
                    )
                )

        mock_run.assert_not_called()
        mock_check_sources.assert_called_once()


class TestControlPlanePackages(unittest.TestCase):
    def test_uses_debian_trixie_dns_package_name(self):
        self.assertIn("bind9-dnsutils", CONTROL_PLANE_PACKAGES)
        self.assertNotIn("dnsutils", CONTROL_PLANE_PACKAGES)


class TestDebianPackageSources(unittest.TestCase):
    @patch("common.common_steps.ensure_debian_package_sources")
    def test_checks_sources_before_package_update(self, mock_ensure):
        check_debian_package_sources(
            SetupConfig(host="testhost", username="testuser", system_type="server_lite")
        )
        mock_ensure.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
