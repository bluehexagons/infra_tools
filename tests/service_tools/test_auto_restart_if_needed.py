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
    @patch("common.service_tools.auto_restart_if_needed.check_restart_required", return_value=True)
    def test_manual_restart_notification_when_users_logged_in(
        self, _check, _users, _load, mock_notify
    ):
        result = auto_restart_if_needed.main()
        self.assertEqual(result, 0)
        mock_notify.assert_called_once()
        self.assertIn("manual restart needed", mock_notify.call_args.kwargs["subject"])

    @patch("common.service_tools.auto_restart_if_needed.perform_restart", return_value=0)
    @patch("common.service_tools.auto_restart_if_needed.check_rdp_sessions", return_value=False)
    @patch("common.service_tools.auto_restart_if_needed.check_desktop_sessions", return_value=False)
    @patch("common.service_tools.auto_restart_if_needed.get_logged_in_users", return_value=[])
    @patch("common.service_tools.auto_restart_if_needed.load_notification_configs_from_state", return_value=["cfg"])
    @patch("common.service_tools.auto_restart_if_needed.check_restart_required", return_value=True)
    def test_auto_restart_path(
        self, _check, _load, _users, _desktop, _rdp, mock_restart
    ):
        result = auto_restart_if_needed.main()
        self.assertEqual(result, 0)
        mock_restart.assert_called_once_with(["cfg"])

    @patch("common.service_tools.auto_restart_if_needed.send_notification_safe")
    @patch("common.service_tools.auto_restart_if_needed.subprocess.run", side_effect=subprocess.CalledProcessError(1, "shutdown"))
    def test_perform_restart_failure_notifies(self, _run, mock_notify):
        result = auto_restart_if_needed.perform_restart(["cfg"])
        self.assertEqual(result, 1)
        self.assertEqual(mock_notify.call_count, 2)
        self.assertIn("automatic restart failed", mock_notify.call_args.kwargs["subject"])


if __name__ == "__main__":
    unittest.main()
