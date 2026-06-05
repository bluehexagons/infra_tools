"""Tests for common.service_tools.auto_update_gogs."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from common.service_tools import auto_update_gogs


class TestAutoUpdateGogs(unittest.TestCase):
    @patch("common.service_tools.auto_update_gogs.send_notification_safe")
    @patch("common.service_tools.auto_update_gogs._run_command")
    @patch("common.service_tools.auto_update_gogs._run_shell_command")
    @patch("common.service_tools.auto_update_gogs.install_or_update_gogs_release", return_value=("v1.2.3", False))
    @patch("common.service_tools.auto_update_gogs.read_gogs_state", return_value={"tag_name": "v1.2.3", "config_path": "/srv/gogs/custom/conf/app.ini"})
    @patch("common.service_tools.auto_update_gogs.os.path.exists", return_value=True)
    @patch("common.service_tools.auto_update_gogs.load_notification_configs_from_state", return_value=[])
    def test_skips_when_gogs_is_current(
        self,
        _configs,
        _exists,
        _state,
        _install,
        mock_shell,
        mock_command,
        mock_notify,
    ):
        with self.assertLogs(auto_update_gogs.logger, level="INFO") as logs:
            result = auto_update_gogs.main()
        self.assertEqual(result, 0)
        mock_shell.assert_not_called()
        mock_command.assert_not_called()
        mock_notify.assert_not_called()
        self.assertIn("Gogs already up to date", "\n".join(logs.output))

    @patch("common.service_tools.auto_update_gogs.send_notification_safe")
    @patch("common.service_tools.auto_update_gogs._run_command")
    @patch("common.service_tools.auto_update_gogs._run_shell_command")
    @patch("common.service_tools.auto_update_gogs.write_gogs_state")
    @patch("common.service_tools.auto_update_gogs.install_or_update_gogs_release", return_value=("v1.2.4", True))
    @patch("common.service_tools.auto_update_gogs.read_gogs_state", return_value={"tag_name": "v1.2.3", "config_path": "/srv/gogs/custom/conf/app.ini"})
    @patch("common.service_tools.auto_update_gogs.os.path.exists", return_value=True)
    @patch("common.service_tools.auto_update_gogs.load_notification_configs_from_state", return_value=[])
    def test_restarts_service_after_update(
        self,
        _configs,
        _exists,
        _state,
        _install,
        mock_write_state,
        mock_shell,
        mock_command,
        mock_notify,
    ):
        mock_shell.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        mock_command.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        result = auto_update_gogs.main()

        self.assertEqual(result, 0)
        self.assertEqual(mock_shell.call_count, 2)
        mock_write_state.assert_called_once_with("v1.2.4", "/srv/gogs", "/srv/gogs/custom/conf/app.ini")
        mock_command.assert_called_once_with(["systemctl", "restart", "gogs"])
        mock_notify.assert_called_once()
        self.assertIn("Success: Gogs updated", mock_notify.call_args.kwargs["subject"])

    @patch("common.service_tools.auto_update_gogs.send_notification_safe")
    @patch("common.service_tools.auto_update_gogs.install_or_update_gogs_release", side_effect=RuntimeError("boom"))
    @patch("common.service_tools.auto_update_gogs.read_gogs_state", return_value={"tag_name": "v1.2.3", "config_path": "/srv/gogs/custom/conf/app.ini"})
    @patch("common.service_tools.auto_update_gogs.os.path.exists", return_value=True)
    @patch("common.service_tools.auto_update_gogs.load_notification_configs_from_state", return_value=["cfg"])
    def test_notifies_when_release_install_fails(
        self,
        _configs,
        _exists,
        _state,
        _install,
        mock_notify,
    ):
        result = auto_update_gogs.main()
        self.assertEqual(result, 1)
        mock_notify.assert_called_once()
        self.assertIn("Gogs update failed", mock_notify.call_args.kwargs["subject"])


if __name__ == "__main__":
    unittest.main()
