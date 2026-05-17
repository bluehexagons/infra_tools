"""Tests for common.service_tools.auto_update_uv."""

from __future__ import annotations

import os
import pwd
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from common.service_tools import auto_update_uv
from lib.update_policy import ECOSYSTEM_AUTO_UPGRADE_ENV


class TestAutoUpdateUv(unittest.TestCase):
    @patch("common.service_tools.auto_update_uv.send_notification_safe")
    @patch("common.service_tools.auto_update_uv.load_notification_configs_from_state", return_value=[])
    @patch("common.service_tools.auto_update_uv.subprocess.run")
    @patch("common.service_tools.auto_update_uv.os.path.exists", return_value=True)
    @patch("common.service_tools.auto_update_uv.pwd.getpwuid")
    def test_updates_uv_and_tools(
        self,
        mock_getpwuid,
        _exists,
        mock_run,
        _configs,
        mock_notify,
    ):
        mock_getpwuid.return_value = pwd.struct_passwd(("user", "x", 1000, 1000, "", "/home/user", "/bin/bash"))
        mock_run.side_effect = [
            subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
        ]

        with patch.dict(os.environ, {ECOSYSTEM_AUTO_UPGRADE_ENV: "1"}):
            with self.assertLogs(auto_update_uv.logger, level="INFO") as logs:
                result = auto_update_uv.main()

        self.assertEqual(result, 0)
        self.assertEqual(mock_run.call_args_list[0].args[0], ["/home/user/.local/bin/uv", "self", "update"])
        self.assertEqual(mock_run.call_args_list[1].args[0], ["/home/user/.local/bin/uv", "tool", "upgrade", "--all"])
        mock_notify.assert_not_called()
        self.assertIn("uv and uv-managed tools updated successfully", "\n".join(logs.output))

    @patch("common.service_tools.auto_update_uv.send_notification_safe")
    @patch("common.service_tools.auto_update_uv.load_notification_configs_from_state", return_value=[])
    @patch("common.service_tools.auto_update_uv.subprocess.run")
    @patch("common.service_tools.auto_update_uv.os.path.exists", return_value=True)
    @patch("common.service_tools.auto_update_uv.pwd.getpwuid")
    def test_skips_tool_upgrades_by_default(
        self,
        mock_getpwuid,
        _exists,
        mock_run,
        _configs,
        mock_notify,
    ):
        mock_getpwuid.return_value = pwd.struct_passwd(("user", "x", 1000, 1000, "", "/home/user", "/bin/bash"))
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        with patch.dict(os.environ, {}, clear=True):
            with self.assertLogs(auto_update_uv.logger, level="INFO") as logs:
                result = auto_update_uv.main()

        self.assertEqual(result, 0)
        self.assertEqual(mock_run.call_count, 1)
        self.assertEqual(mock_run.call_args.args[0], ["/home/user/.local/bin/uv", "self", "update"])
        mock_notify.assert_not_called()
        self.assertIn("uv-managed tool auto-upgrades disabled by policy", "\n".join(logs.output))

    @patch("common.service_tools.auto_update_uv.send_notification_safe")
    @patch("common.service_tools.auto_update_uv.load_notification_configs_from_state", return_value=["cfg"])
    @patch("common.service_tools.auto_update_uv.subprocess.run")
    @patch("common.service_tools.auto_update_uv.os.path.exists", return_value=True)
    @patch("common.service_tools.auto_update_uv.pwd.getpwuid")
    def test_notifies_when_self_update_fails(
        self,
        mock_getpwuid,
        _exists,
        mock_run,
        _configs,
        mock_notify,
    ):
        mock_getpwuid.return_value = pwd.struct_passwd(("user", "x", 1000, 1000, "", "/home/user", "/bin/bash"))
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="boom")

        result = auto_update_uv.main()

        self.assertEqual(result, 1)
        mock_notify.assert_called_once()
        self.assertIn("uv update failed", mock_notify.call_args.kwargs["subject"])

    @patch("common.service_tools.auto_update_uv.load_notification_configs_from_state", return_value=[])
    @patch("common.service_tools.auto_update_uv.os.path.exists", return_value=False)
    @patch("common.service_tools.auto_update_uv.pwd.getpwuid")
    def test_logs_when_uv_missing(
        self,
        mock_getpwuid,
        _exists,
        _configs,
    ):
        mock_getpwuid.return_value = pwd.struct_passwd(("user", "x", 1000, 1000, "", "/home/user", "/bin/bash"))

        with self.assertLogs(auto_update_uv.logger, level="INFO") as logs:
            result = auto_update_uv.main()

        self.assertEqual(result, 0)
        self.assertIn("uv not found, skipping update", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
