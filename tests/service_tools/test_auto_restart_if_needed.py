"""Tests for common.service_tools.auto_restart_if_needed."""

from __future__ import annotations

import os
import sys
import subprocess
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from common.service_tools import auto_restart_if_needed


class TestAutoRestartIfNeeded(unittest.TestCase):
    @patch("common.service_tools.auto_restart_if_needed.send_notification_safe")
    @patch("common.service_tools.auto_restart_if_needed.load_notification_configs_from_state", return_value=["cfg"])
    @patch("common.service_tools.auto_restart_if_needed.get_logged_in_users", return_value=["user pts/0"])
    @patch("common.service_tools.auto_restart_if_needed.is_no_restart_mode", return_value=False)
    @patch("common.service_tools.auto_restart_if_needed.check_restart_required", return_value=True)
    def test_manual_restart_notification_when_users_logged_in(
        self, _check, _no_restart, _users, _load, mock_notify
    ):
        with self.assertLogs(auto_restart_if_needed.logger, level="INFO") as logs:
            result = auto_restart_if_needed.main()
        self.assertEqual(result, 0)
        mock_notify.assert_called_once()
        self.assertIn("manual restart needed", mock_notify.call_args.kwargs["subject"])
        self.assertIn("Users are logged in, skipping restart | session_type='ssh-console'", "\n".join(logs.output))

    @patch("common.service_tools.auto_restart_if_needed.perform_restart", return_value=0)
    @patch("common.service_tools.auto_restart_if_needed.check_rdp_sessions", return_value=False)
    @patch("common.service_tools.auto_restart_if_needed.check_desktop_sessions", return_value=False)
    @patch("common.service_tools.auto_restart_if_needed.get_logged_in_users", return_value=[])
    @patch("common.service_tools.auto_restart_if_needed.is_no_restart_mode", return_value=False)
    @patch("common.service_tools.auto_restart_if_needed.load_notification_configs_from_state", return_value=["cfg"])
    @patch("common.service_tools.auto_restart_if_needed.check_restart_required", return_value=True)
    def test_auto_restart_path(
        self, _check, _load, _no_restart, _users, _desktop, _rdp, mock_restart
    ):
        result = auto_restart_if_needed.main()
        self.assertEqual(result, 0)
        mock_restart.assert_called_once_with(["cfg"])

    @patch("common.service_tools.auto_restart_if_needed.send_notification_safe")
    @patch("common.service_tools.auto_restart_if_needed.subprocess.run", side_effect=subprocess.CalledProcessError(1, "shutdown"))
    def test_perform_restart_failure_notifies(self, _run, mock_notify):
        with self.assertLogs(auto_restart_if_needed.logger, level="ERROR") as logs:
            result = auto_restart_if_needed.perform_restart(["cfg"])
        self.assertEqual(result, 1)
        self.assertEqual(mock_notify.call_count, 2)
        self.assertIn("automatic restart failed", mock_notify.call_args.kwargs["subject"])
        self.assertIn("Failed to initiate restart | error=", "\n".join(logs.output))

    @patch("common.service_tools.auto_restart_if_needed.send_notification_safe")
    @patch("common.service_tools.auto_restart_if_needed.load_notification_configs_from_state", return_value=["cfg"])
    @patch("common.service_tools.auto_restart_if_needed.is_no_restart_mode", return_value=True)
    @patch("common.service_tools.auto_restart_if_needed.check_restart_required", return_value=True)
    def test_no_restart_mode_sends_notification(self, _check, _no_restart, _load, mock_notify):
        result = auto_restart_if_needed.main()
        self.assertEqual(result, 0)
        mock_notify.assert_called_once()
        self.assertIn("automatic restart disabled", mock_notify.call_args.kwargs["subject"])

    @patch("common.service_tools.auto_restart_if_needed.perform_restart")
    @patch("common.service_tools.auto_restart_if_needed.send_notification_safe")
    @patch("common.service_tools.auto_restart_if_needed.load_notification_configs_from_state", return_value=["cfg"])
    @patch("common.service_tools.auto_restart_if_needed.is_no_restart_mode", return_value=True)
    @patch("common.service_tools.auto_restart_if_needed.check_restart_required", return_value=True)
    def test_no_restart_mode_does_not_restart(self, _check, _no_restart, _load, _notify, mock_restart):
        auto_restart_if_needed.main()
        mock_restart.assert_not_called()


class TestIsNoRestartMode(unittest.TestCase):
    @patch("common.service_tools.auto_restart_if_needed.load_setup_config", return_value={"no_restart": True, "username": "u", "system_type": "server_proxmox"})
    def test_returns_true_when_configured(self, _load):
        self.assertTrue(auto_restart_if_needed.is_no_restart_mode())

    @patch("common.service_tools.auto_restart_if_needed.load_setup_config", return_value={"no_restart": False, "username": "u", "system_type": "server_lite"})
    def test_returns_false_when_not_configured(self, _load):
        self.assertFalse(auto_restart_if_needed.is_no_restart_mode())

    @patch("common.service_tools.auto_restart_if_needed.load_setup_config", return_value=None)
    def test_returns_false_when_no_state(self, _load):
        self.assertFalse(auto_restart_if_needed.is_no_restart_mode())

    @patch("common.service_tools.auto_restart_if_needed.load_setup_config", return_value={"username": "u", "system_type": "server_lite"})
    def test_returns_false_when_key_missing(self, _load):
        self.assertFalse(auto_restart_if_needed.is_no_restart_mode())

    @patch("common.service_tools.auto_restart_if_needed.load_setup_config", return_value={"username": "u", "system_type": "server_proxmox"})
    def test_returns_true_for_server_proxmox_when_key_missing(self, _load):
        self.assertTrue(auto_restart_if_needed.is_no_restart_mode())


if __name__ == "__main__":
    unittest.main()
