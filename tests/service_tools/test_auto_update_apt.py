"""Tests for common.service_tools.auto_update_apt."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from common.service_tools import auto_update_apt


class TestAutoUpdateApt(unittest.TestCase):
    @patch("common.service_tools.auto_update_apt.autoremove_packages")
    @patch("common.service_tools.auto_update_apt.upgrade_packages", return_value=(True, ""))
    @patch("common.service_tools.auto_update_apt.update_package_lists", return_value=True)
    @patch("common.service_tools.auto_update_apt.disable_duplicate_vivaldi_source", return_value=None)
    @patch("common.service_tools.auto_update_apt.load_notification_configs_from_state", return_value=[])
    def test_successful_update(self, _configs, _cleanup, _update, _upgrade, _autoremove):
        with self.assertLogs(auto_update_apt.logger, level="INFO") as logs:
            result = auto_update_apt.main()
        self.assertEqual(result, 0)
        _cleanup.assert_called_once()
        _update.assert_called_once()
        _upgrade.assert_called_once()
        _autoremove.assert_called_once()
        joined = "\n".join(logs.output)
        self.assertIn("Starting APT package update", joined)
        self.assertIn("APT package update completed successfully", joined)

    @patch("common.service_tools.auto_update_apt.send_notification_safe")
    @patch("common.service_tools.auto_update_apt.update_package_lists", return_value=False)
    @patch("common.service_tools.auto_update_apt.disable_duplicate_vivaldi_source", return_value=None)
    @patch("common.service_tools.auto_update_apt.load_notification_configs_from_state", return_value=["cfg"])
    def test_update_failure_notifies(self, _configs, _cleanup, _update, mock_notify):
        result = auto_update_apt.main()
        self.assertEqual(result, 1)
        mock_notify.assert_called_once()
        self.assertIn("APT update failed", mock_notify.call_args.kwargs["subject"])

    @patch("common.service_tools.auto_update_apt.send_notification_safe")
    @patch("common.service_tools.auto_update_apt.upgrade_packages", return_value=(False, "dependency error"))
    @patch("common.service_tools.auto_update_apt.update_package_lists", return_value=True)
    @patch("common.service_tools.auto_update_apt.disable_duplicate_vivaldi_source", return_value=None)
    @patch("common.service_tools.auto_update_apt.load_notification_configs_from_state", return_value=["cfg"])
    def test_upgrade_failure_notifies(self, _configs, _cleanup, _update, _upgrade, mock_notify):
        result = auto_update_apt.main()
        self.assertEqual(result, 1)
        mock_notify.assert_called_once()
        self.assertIn("APT upgrade failed", mock_notify.call_args.kwargs["subject"])
        self.assertEqual("dependency error", mock_notify.call_args.kwargs["details"])

    @patch("common.service_tools.auto_update_apt.autoremove_packages")
    @patch("common.service_tools.auto_update_apt.upgrade_packages", return_value=(True, ""))
    @patch("common.service_tools.auto_update_apt.update_package_lists", return_value=True)
    @patch(
        "common.service_tools.auto_update_apt.disable_duplicate_vivaldi_source",
        return_value="/etc/apt/sources.list.d/vivaldi.list.disabled-by-infra-tools",
    )
    @patch("common.service_tools.auto_update_apt.load_notification_configs_from_state", return_value=[])
    def test_logs_disabled_duplicate_vivaldi_source(self, _configs, _cleanup, _update, _upgrade, _autoremove):
        with self.assertLogs(auto_update_apt.logger, level="INFO") as logs:
            result = auto_update_apt.main()

        self.assertEqual(result, 0)
        self.assertIn("Disabled duplicate Vivaldi APT source", "\n".join(logs.output))

    @patch("common.service_tools.auto_update_apt.run_apt_command")
    def test_update_package_lists_logs_structured_error(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="mirror offline"
        )

        with self.assertLogs(auto_update_apt.logger, level="ERROR") as logs:
            ok = auto_update_apt.update_package_lists()

        self.assertFalse(ok)
        self.assertIn("apt-get update failed | stderr='mirror offline'", "\n".join(logs.output))


class TestRunAptCommand(unittest.TestCase):
    @patch("common.service_tools.auto_update_apt.subprocess.run")
    def test_sets_noninteractive_frontend(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        auto_update_apt.run_apt_command(["update", "-qq"])
        _, kwargs = mock_run.call_args
        self.assertEqual(kwargs["env"]["DEBIAN_FRONTEND"], "noninteractive")

    @patch("common.service_tools.auto_update_apt.subprocess.run")
    def test_passes_arguments_to_apt_get(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        auto_update_apt.run_apt_command(["dist-upgrade", "-y"])
        args, _ = mock_run.call_args
        self.assertEqual(args[0], ["apt-get", "dist-upgrade", "-y"])


class TestUpgradePackages(unittest.TestCase):
    @patch("common.service_tools.auto_update_apt.run_apt_command")
    def test_uses_dpkg_options(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        auto_update_apt.upgrade_packages()
        args = mock_run.call_args[0][0]
        self.assertIn("-o", args)
        self.assertIn("Dpkg::Options::=--force-confdef", args)
        self.assertIn("Dpkg::Options::=--force-confold", args)

    @patch("common.service_tools.auto_update_apt.run_apt_command")
    def test_upgrade_refuses_package_removals(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        auto_update_apt.upgrade_packages()
        args = mock_run.call_args[0][0]
        self.assertIn("--no-remove", args)

    @patch("common.service_tools.auto_update_apt.run_apt_command")
    def test_upgrade_uses_lock_timeout(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        auto_update_apt.upgrade_packages()
        args = mock_run.call_args[0][0]
        self.assertIn("DPkg::Lock::Timeout=300", args)

    @patch("common.service_tools.auto_update_apt.run_apt_command")
    def test_update_uses_lock_timeout(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        auto_update_apt.update_package_lists()
        args = mock_run.call_args[0][0]
        self.assertIn("DPkg::Lock::Timeout=300", args)

    @patch("common.service_tools.auto_update_apt.run_apt_command")
    def test_autoremove_uses_lock_timeout(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        auto_update_apt.autoremove_packages()
        args = mock_run.call_args[0][0]
        self.assertIn("DPkg::Lock::Timeout=300", args)


if __name__ == "__main__":
    unittest.main()
