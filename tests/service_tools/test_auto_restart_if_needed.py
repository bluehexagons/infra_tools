"""Tests for common.service_tools.auto_restart_if_needed."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from common.service_tools import auto_restart_if_needed


class TestAutoRestartIfNeeded(unittest.TestCase):
    @patch("common.service_tools.auto_restart_if_needed.perform_restart")
    @patch("common.service_tools.auto_restart_if_needed.record_deferral")
    @patch("common.service_tools.auto_restart_if_needed.get_uptime_seconds", return_value=None)
    @patch("common.service_tools.auto_restart_if_needed.can_restart_system", return_value=True)
    @patch("common.service_tools.auto_restart_if_needed.load_restart_policy", return_value={"auto_restart": True, "force_days": 7, "grace": 5})
    @patch("common.service_tools.auto_restart_if_needed.check_restart_required", return_value=True)
    @patch("common.service_tools.auto_restart_if_needed.load_notification_configs_from_state", return_value=["cfg"])
    def test_defers_when_uptime_cannot_be_read(
        self, _load, _check, _policy, _can_restart, _uptime, mock_defer, mock_restart
    ):
        self.assertEqual(auto_restart_if_needed.main(), 0)
        mock_defer.assert_called_once_with("system uptime could not be determined", ["cfg"])
        mock_restart.assert_not_called()

    @patch("common.service_tools.auto_restart_if_needed.perform_restart")
    @patch("common.service_tools.auto_restart_if_needed.record_deferral")
    @patch("common.service_tools.auto_restart_if_needed.get_active_sessions", return_value=None)
    @patch("common.service_tools.auto_restart_if_needed.get_uptime_seconds", return_value=3600)
    @patch("common.service_tools.auto_restart_if_needed.can_restart_system", return_value=True)
    @patch("common.service_tools.auto_restart_if_needed.load_restart_policy", return_value={"auto_restart": True, "force_days": 7, "grace": 5})
    @patch("common.service_tools.auto_restart_if_needed.check_restart_required", return_value=True)
    @patch("common.service_tools.auto_restart_if_needed.load_notification_configs_from_state", return_value=["cfg"])
    def test_defers_when_sessions_cannot_be_queried(
        self, _load, _check, _policy, _can_restart, _uptime, _sessions, mock_defer, mock_restart
    ):
        self.assertEqual(auto_restart_if_needed.main(), 0)
        mock_defer.assert_called_once_with("active sessions could not be determined", ["cfg"])
        mock_restart.assert_not_called()

    @patch("common.service_tools.auto_restart_if_needed.save_restart_state")
    @patch("common.service_tools.auto_restart_if_needed.load_restart_state", return_value={})
    @patch("common.service_tools.auto_restart_if_needed.time.time", return_value=100000)
    @patch("common.service_tools.auto_restart_if_needed.send_notification_safe")
    @patch("common.service_tools.auto_restart_if_needed.load_notification_configs_from_state", return_value=["cfg"])
    @patch("common.service_tools.auto_restart_if_needed.get_active_sessions", return_value=["1 user seat0 tty2"])
    @patch("common.service_tools.auto_restart_if_needed.get_uptime_seconds", return_value=3600)
    @patch("common.service_tools.auto_restart_if_needed.can_restart_system", return_value=True)
    @patch("common.service_tools.auto_restart_if_needed.load_restart_policy", return_value={"auto_restart": True, "force_days": 7, "grace": 5})
    @patch("common.service_tools.auto_restart_if_needed.check_restart_required", return_value=True)
    def test_defers_when_sessions_active(
        self, _check, _policy, _can_restart, _uptime, _sessions, _load, mock_notify, _time, _state, mock_save
    ):
        result = auto_restart_if_needed.main()
        self.assertEqual(result, 0)
        mock_notify.assert_called_once()
        self.assertIn("deferred", mock_notify.call_args.kwargs["subject"])
        mock_save.assert_called_once()

    @patch("common.service_tools.auto_restart_if_needed.perform_restart", return_value=0)
    @patch("common.service_tools.auto_restart_if_needed.get_active_sessions", return_value=[])
    @patch("common.service_tools.auto_restart_if_needed.get_uptime_seconds", return_value=3600)
    @patch("common.service_tools.auto_restart_if_needed.can_restart_system", return_value=True)
    @patch("common.service_tools.auto_restart_if_needed.load_restart_policy", return_value={"auto_restart": True, "force_days": 7, "grace": 5})
    @patch("common.service_tools.auto_restart_if_needed.check_restart_required", return_value=True)
    @patch("common.service_tools.auto_restart_if_needed.load_notification_configs_from_state", return_value=["cfg"])
    def test_auto_restart_path(self, _load, _check, _policy, _can_restart, _uptime, _sessions, mock_restart):
        result = auto_restart_if_needed.main()
        self.assertEqual(result, 0)
        mock_restart.assert_called_once_with(["cfg"], 5, forced=False)

    @patch("common.service_tools.auto_restart_if_needed.send_notification_safe")
    @patch("common.service_tools.auto_restart_if_needed.shutil.which", return_value="/sbin/shutdown")
    @patch("common.service_tools.auto_restart_if_needed.subprocess.run", side_effect=subprocess.CalledProcessError(1, "shutdown"))
    def test_perform_restart_failure_notifies(self, _run, _which, mock_notify):
        with self.assertLogs(auto_restart_if_needed.logger, level="ERROR") as logs:
            result = auto_restart_if_needed.perform_restart(["cfg"], 5)
        self.assertEqual(result, 1)
        self.assertEqual(mock_notify.call_count, 2)
        self.assertIn("automatic restart failed", mock_notify.call_args.kwargs["subject"])
        self.assertIn("Failed to initiate restart | error=", "\n".join(logs.output))

    @patch("common.service_tools.auto_restart_if_needed.perform_restart", return_value=0)
    @patch("common.service_tools.auto_restart_if_needed.load_restart_state", return_value={"first_required": 0})
    @patch("common.service_tools.auto_restart_if_needed.time.time", return_value=8 * 24 * 60 * 60)
    @patch("common.service_tools.auto_restart_if_needed.get_active_sessions", return_value=["1 user seat0 tty2"])
    @patch("common.service_tools.auto_restart_if_needed.get_uptime_seconds", return_value=3600)
    @patch("common.service_tools.auto_restart_if_needed.can_restart_system", return_value=True)
    @patch("common.service_tools.auto_restart_if_needed.load_restart_policy", return_value={"auto_restart": False, "force_days": 7, "grace": 5})
    @patch("common.service_tools.auto_restart_if_needed.check_restart_required", return_value=True)
    @patch("common.service_tools.auto_restart_if_needed.load_notification_configs_from_state", return_value=["cfg"])
    def test_force_deadline_restarts_even_when_disabled(
        self, _load, _check, _policy, _can_restart, _uptime, _sessions, _time, _state, mock_restart
    ):
        result = auto_restart_if_needed.main()
        self.assertEqual(result, 0)
        mock_restart.assert_called_once_with(["cfg"], 5, forced=True)

    @patch("common.service_tools.auto_restart_if_needed.save_restart_state")
    @patch("common.service_tools.auto_restart_if_needed.load_restart_state", return_value={})
    @patch("common.service_tools.auto_restart_if_needed.time.time", return_value=100000)
    @patch("common.service_tools.auto_restart_if_needed.send_notification_safe")
    @patch("common.service_tools.auto_restart_if_needed.load_notification_configs_from_state", return_value=["cfg"])
    @patch("common.service_tools.auto_restart_if_needed.get_uptime_seconds", return_value=60)
    @patch("common.service_tools.auto_restart_if_needed.can_restart_system", return_value=True)
    @patch("common.service_tools.auto_restart_if_needed.load_restart_policy", return_value={"auto_restart": True, "force_days": 7, "grace": 5})
    @patch("common.service_tools.auto_restart_if_needed.check_restart_required", return_value=True)
    def test_defers_during_minimum_uptime(
        self, _check, _policy, _can_restart, _uptime, _load, mock_notify, _time, _state, mock_save
    ):
        result = auto_restart_if_needed.main()
        self.assertEqual(result, 0)
        mock_notify.assert_called_once()
        mock_save.assert_called_once()


class TestRestartPolicy(unittest.TestCase):
    @patch("common.service_tools.auto_restart_if_needed.load_setup_config", return_value={"auto_restart": False, "username": "u", "system_type": "server_lite"})
    def test_reads_configured_auto_restart(self, _load):
        policy = auto_restart_if_needed.load_restart_policy()
        self.assertFalse(policy["auto_restart"])

    @patch("common.service_tools.auto_restart_if_needed.load_setup_config", return_value={"no_restart": True, "username": "u", "system_type": "server_lite"})
    def test_maps_legacy_no_restart(self, _load):
        policy = auto_restart_if_needed.load_restart_policy()
        self.assertFalse(policy["auto_restart"])

    @patch("common.service_tools.auto_restart_if_needed.load_setup_config", return_value={"username": "u", "system_type": "server_proxmox"})
    def test_uses_proxmox_defaults(self, _load):
        policy = auto_restart_if_needed.load_restart_policy()
        self.assertFalse(policy["auto_restart"])
        self.assertEqual(policy["force_days"], 0)

    @patch(
        "common.service_tools.auto_restart_if_needed.load_setup_config",
        return_value={
            "username": "u",
            "system_type": "server_lite",
            "auto_restart_force_days": "invalid",
            "auto_restart_grace": -2,
        },
    )
    def test_invalid_persisted_numbers_fall_back_safely(self, _load):
        policy = auto_restart_if_needed.load_restart_policy()
        self.assertEqual(policy["force_days"], 7)
        self.assertEqual(policy["grace"], 0)

    @patch("common.service_tools.auto_restart_if_needed.load_restart_state", return_value={"first_required": "invalid"})
    @patch("common.service_tools.auto_restart_if_needed.time.time", return_value=1000)
    def test_invalid_restart_timestamp_does_not_force(self, _time, _state):
        self.assertFalse(auto_restart_if_needed.force_deadline_reached({"force_days": 7}))


if __name__ == "__main__":
    unittest.main()
