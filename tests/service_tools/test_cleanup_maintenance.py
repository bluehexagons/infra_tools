"""Tests for common.service_tools.cleanup_maintenance."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from common.service_tools import cleanup_maintenance


class TestCleanupMaintenance(unittest.TestCase):
    @patch("common.service_tools.cleanup_maintenance.cleanup_optional_cache", return_value=None)
    @patch("common.service_tools.cleanup_maintenance.cleanup_apt_cache", return_value=[])
    @patch("common.service_tools.cleanup_maintenance.load_notification_configs_from_state", return_value=[])
    def test_successful_cleanup_returns_zero(self, _configs, mock_apt, mock_optional):
        with self.assertLogs(cleanup_maintenance.logger, level="INFO") as logs:
            result = cleanup_maintenance.main()
        self.assertEqual(result, 0)
        mock_apt.assert_called_once()
        self.assertEqual(mock_optional.call_count, 6)
        joined = "\n".join(logs.output)
        self.assertIn("Starting cleanup maintenance", joined)
        self.assertIn("Cleanup maintenance completed successfully", joined)

    @patch("common.service_tools.cleanup_maintenance.send_notification_safe")
    @patch("common.service_tools.cleanup_maintenance.cleanup_optional_cache", side_effect=[None, "journal vacuum: failed", None, None, None, None])
    @patch("common.service_tools.cleanup_maintenance.cleanup_apt_cache", return_value=[])
    @patch("common.service_tools.cleanup_maintenance.load_notification_configs_from_state", return_value=["cfg"])
    def test_failure_notifies(self, _configs, _apt, _optional, mock_notify):
        result = cleanup_maintenance.main()
        self.assertEqual(result, 1)
        mock_notify.assert_called_once()
        self.assertIn("cleanup maintenance failed", mock_notify.call_args.kwargs["subject"])
        self.assertIn("journal vacuum: failed", mock_notify.call_args.kwargs["details"])


class TestCleanupHelpers(unittest.TestCase):
    @patch("common.service_tools.cleanup_maintenance.run_command")
    def test_run_cleanup_command_logs_structured_failure(self, mock_run_command):
        mock_run_command.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="permission denied",
        )

        with self.assertLogs(cleanup_maintenance.logger, level="WARNING") as logs:
            failure = cleanup_maintenance.run_cleanup_command(["apt-get", "clean"], "APT clean")

        self.assertEqual(failure, "APT clean: permission denied")
        self.assertIn("APT clean failed | stderr='permission denied'", "\n".join(logs.output))

    @patch("common.service_tools.cleanup_maintenance.run_command")
    @patch("common.service_tools.cleanup_maintenance.shutil.which", return_value="/usr/bin/apt-get")
    def test_cleanup_apt_cache_uses_noninteractive_env(self, _which, mock_run_command):
        mock_run_command.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        cleanup_maintenance.cleanup_apt_cache()

        first_call = mock_run_command.call_args_list[0]
        self.assertEqual(
            first_call.args[0],
            ["/usr/bin/apt-get", "autoclean", "-qq", "-o", "DPkg::Lock::Timeout=300"],
        )
        self.assertEqual(first_call.kwargs["env"]["DEBIAN_FRONTEND"], "noninteractive")
        self.assertEqual(
            mock_run_command.call_args_list[1].args[0],
            ["/usr/bin/apt-get", "clean", "-o", "DPkg::Lock::Timeout=300"],
        )

    @patch("common.service_tools.cleanup_maintenance.run_cleanup_command", return_value=None)
    @patch("common.service_tools.cleanup_maintenance.shutil.which", side_effect=[None, "/usr/bin/pip"])
    def test_cleanup_optional_cache_uses_first_available_executable(self, _which, mock_cleanup):
        result = cleanup_maintenance.cleanup_optional_cache(
            ["pip3", "pip"],
            ["cache", "purge"],
            "pip cache cleanup",
        )

        self.assertIsNone(result)
        mock_cleanup.assert_called_once_with(
            ["/usr/bin/pip", "cache", "purge"],
            "pip cache cleanup",
        )


if __name__ == "__main__":
    unittest.main()
