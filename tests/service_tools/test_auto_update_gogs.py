"""Tests for common.service_tools.auto_update_gogs."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from common.service_tools import auto_update_gogs


class TestAutoUpdateGogs(unittest.TestCase):
    def setUp(self):
        self.record_update_function = auto_update_gogs._record_update_result
        self.record_update_patcher = patch(
            "common.service_tools.auto_update_gogs._record_update_result"
        )
        self.record_update = self.record_update_patcher.start()
        self.addCleanup(self.record_update_patcher.stop)

    @patch("common.service_tools.auto_update_gogs.send_notification_safe")
    @patch("common.service_tools.auto_update_gogs._run_command")
    @patch("common.service_tools.auto_update_gogs._run_shell_command")
    @patch("common.service_tools.auto_update_gogs.install_or_update_gogs_release", return_value=("v1.2.3", False, "a" * 64))
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
        self.record_update.assert_called_once_with(0)
        mock_shell.assert_not_called()
        mock_command.assert_not_called()
        mock_notify.assert_not_called()
        self.assertIn("Gogs already up to date", "\n".join(logs.output))

    @patch("common.service_tools.auto_update_gogs.send_notification_safe")
    @patch("common.service_tools.auto_update_gogs._run_command")
    @patch("common.service_tools.auto_update_gogs._run_shell_command")
    @patch("common.service_tools.auto_update_gogs.write_gogs_state")
    @patch("common.service_tools.auto_update_gogs.install_or_update_gogs_release", return_value=("v1.2.4", True, "a" * 64))
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
        self.record_update.assert_called_once_with(0)
        self.assertEqual(mock_shell.call_count, 2)
        mock_write_state.assert_called_once_with(
            "v1.2.4",
            "/srv/gogs",
            "/srv/gogs/custom/conf/app.ini",
            "a" * 64,
        )
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
        self.record_update.assert_called_once_with(1)
        mock_notify.assert_called_once()
        self.assertIn("Gogs update failed", mock_notify.call_args.kwargs["subject"])

    @patch("common.service_tools.auto_update_gogs.send_notification_safe")
    @patch("common.service_tools.auto_update_gogs._rollback_gogs_release", return_value=True)
    @patch("common.service_tools.auto_update_gogs._current_release_path", return_value="/opt/gogs/releases/v1.2.3")
    @patch("common.service_tools.auto_update_gogs._run_command")
    @patch("common.service_tools.auto_update_gogs._run_shell_command")
    @patch("common.service_tools.auto_update_gogs.install_or_update_gogs_release", return_value=("v1.2.4", True, "a" * 64))
    @patch(
        "common.service_tools.auto_update_gogs.read_gogs_state",
        return_value={"tag_name": "v1.2.3", "config_path": "/srv/gogs/custom/conf/app.ini"},
    )
    @patch("common.service_tools.auto_update_gogs.os.path.exists", return_value=True)
    @patch("common.service_tools.auto_update_gogs.load_notification_configs_from_state", return_value=["cfg"])
    def test_rolls_back_when_post_update_command_fails(
        self,
        _configs,
        _exists,
        _state,
        _install,
        mock_shell,
        mock_command,
        _previous_release,
        mock_rollback,
        mock_notify,
    ):
        mock_shell.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="incompatible command"
        )

        result = auto_update_gogs.main()

        self.assertEqual(result, 1)
        self.record_update.assert_called_once_with(1)
        mock_command.assert_not_called()
        mock_rollback.assert_called_once_with("/opt/gogs/releases/v1.2.3")
        self.assertIn("Previous release restored", mock_notify.call_args.kwargs["details"])

    @patch("common.service_tools.auto_update_gogs._run_command")
    @patch("common.service_tools.auto_update_gogs.os.path.exists", return_value=True)
    def test_rollback_relinks_and_restarts_previous_release(self, _exists, mock_command):
        mock_command.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        rolled_back = auto_update_gogs._rollback_gogs_release("/opt/gogs/releases/v1.2.3")

        self.assertTrue(rolled_back)
        self.assertEqual(
            [call.args[0] for call in mock_command.call_args_list],
            [
                ["ln", "-sfn", "/opt/gogs/releases/v1.2.3", "/opt/gogs/current"],
                ["systemctl", "restart", "gogs"],
            ],
        )

    def test_records_root_owned_update_health_state(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = os.path.join(directory, "gogs_update.json")
            with patch.object(
                auto_update_gogs,
                "GOGS_UPDATE_STATE_FILE",
                state_path,
            ):
                self.record_update_function(1)

            with open(state_path, encoding="utf-8") as source:
                state = json.load(source)

        self.assertEqual(state["schema_version"], 1)
        self.assertEqual(state["exit_code"], 1)
        self.assertFalse(state["successful"])
        self.assertTrue(state["checked_at"].endswith("+00:00"))


if __name__ == "__main__":
    unittest.main()
