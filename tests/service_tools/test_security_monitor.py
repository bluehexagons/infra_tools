"""Tests for security.service_tools.security_monitor."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from security.service_tools import security_monitor


class TestSecurityMonitor(unittest.TestCase):
    @patch("security.service_tools.security_monitor._save_state")
    @patch("security.service_tools.security_monitor.send_notification_safe")
    @patch("security.service_tools.security_monitor._check_ssh_failures", return_value=(0, None))
    @patch("security.service_tools.security_monitor._check_auditd", return_value=([], False, []))
    @patch("security.service_tools.security_monitor._check_fail2ban")
    @patch("security.service_tools.security_monitor._load_state")
    @patch("security.service_tools.security_monitor.load_notification_configs_from_state", return_value=["cfg"])
    def test_future_cursor_is_clamped_to_recent_window(
        self, _configs, mock_state, mock_fail2ban, _audit, _ssh, mock_notify, mock_save
    ):
        mock_state.return_value = {"last_run": (datetime.now() + timedelta(days=1)).isoformat()}
        mock_fail2ban.return_value = ([], [], None)

        self.assertEqual(security_monitor.main(), 0)

        since = mock_fail2ban.call_args.args[0]
        self.assertLess(since, datetime.now())
        self.assertGreater(since, datetime.now() - timedelta(minutes=16))
        mock_notify.assert_not_called()
        mock_save.assert_called_once()

    @patch("security.service_tools.security_monitor._save_state")
    @patch("security.service_tools.security_monitor.send_notification_safe")
    @patch("security.service_tools.security_monitor._check_ssh_failures", return_value=(0, "SSH journal: denied"))
    @patch("security.service_tools.security_monitor._check_auditd", return_value=([], False, []))
    @patch("security.service_tools.security_monitor._check_fail2ban", return_value=([], [], None))
    @patch("security.service_tools.security_monitor._load_state", return_value={})
    @patch("security.service_tools.security_monitor.load_notification_configs_from_state", return_value=["cfg"])
    def test_collection_failure_retains_cursor_and_returns_failure(
        self, _configs, _state, _fail2ban, _audit, _ssh, mock_notify, mock_save
    ):
        self.assertEqual(security_monitor.main(), 1)

        mock_save.assert_not_called()
        self.assertEqual(mock_notify.call_args.kwargs["status"], "error")
        self.assertIn("SSH journal: denied", mock_notify.call_args.kwargs["details"])

    @patch("security.service_tools.security_monitor.subprocess.run")
    def test_ausearch_no_matches_is_not_a_collection_error(self, mock_run):
        mock_run.return_value = SimpleNamespace(returncode=1, stdout="", stderr="")

        has_events, error = security_monitor._ausearch_has_events("identity", datetime.now())

        self.assertFalse(has_events)
        self.assertIsNone(error)

    def test_state_roundtrip_uses_atomic_writer(self):
        with tempfile.TemporaryDirectory() as state_dir:
            state_path = os.path.join(state_dir, "security-monitor.json")
            with patch("security.service_tools.security_monitor._STATE_FILE", state_path):
                security_monitor._save_state({"last_run": "2026-08-04T00:00:00"})
                self.assertEqual(
                    security_monitor._load_state(),
                    {"last_run": "2026-08-04T00:00:00"},
                )
                self.assertEqual(os.stat(state_path).st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
