"""Tests for web.service_tools.auto_update_node."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from web.service_tools import auto_update_node


class TestAutoUpdateNode(unittest.TestCase):
    def test_determine_update_track_from_lts_alias(self):
        self.assertEqual(
            auto_update_node.determine_update_track("default -> lts/* (-> v20.12.2)"),
            "lts",
        )

    def test_determine_update_track_from_latest_alias(self):
        self.assertEqual(
            auto_update_node.determine_update_track("default -> node (-> v22.1.0)"),
            "latest",
        )

    @patch("web.service_tools.auto_update_node.subprocess.run")
    @patch("web.service_tools.auto_update_node.get_nvm_dir", return_value="/home/user/.nvm")
    def test_run_nvm_command_uses_bash_argv(self, _nvm_dir, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(args=["/bin/bash"], returncode=0)
        auto_update_node.run_nvm_command(["nvm", "version", "default"])
        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        self.assertEqual(args[0][:2], ["/bin/bash", "-lc"])
        self.assertIn("nvm version default", args[0][2])
        self.assertNotIn("shell", kwargs)

    @patch("web.service_tools.auto_update_node.send_notification_safe")
    @patch("web.service_tools.auto_update_node.update_global_packages", return_value=(True, ""))
    @patch("web.service_tools.auto_update_node.install_target_version")
    @patch("web.service_tools.auto_update_node.get_default_alias", return_value="default -> node (-> v22.1.0)")
    @patch("web.service_tools.auto_update_node.get_current_version", return_value="v22.1.0")
    @patch("web.service_tools.auto_update_node.get_latest_version", return_value="v22.1.0")
    @patch("web.service_tools.auto_update_node.get_current_lts_version", return_value="v20.12.2")
    @patch("web.service_tools.auto_update_node.load_notification_configs_from_state", return_value=[])
    @patch("web.service_tools.auto_update_node.os.path.exists", return_value=True)
    @patch("web.service_tools.auto_update_node.get_nvm_dir", return_value="/home/user/.nvm")
    def test_main_updates_global_packages_when_current_node_is_latest(
        self,
        _nvm_dir,
        _exists,
        _configs,
        _lts,
        _latest,
        _current,
        _alias,
        mock_install,
        mock_update_packages,
        mock_notify,
    ):
        result = auto_update_node.main()
        self.assertEqual(result, 0)
        mock_install.assert_not_called()
        mock_update_packages.assert_called_once()
        mock_notify.assert_called_once()
        self.assertIn("Success", mock_notify.call_args.kwargs["subject"])

    @patch("web.service_tools.auto_update_node.send_notification_safe")
    @patch(
        "web.service_tools.auto_update_node.update_global_packages",
        return_value=(False, "Updated pnpm: permission denied"),
    )
    @patch("web.service_tools.auto_update_node.install_target_version")
    @patch("web.service_tools.auto_update_node.get_default_alias", return_value="default -> lts/* (-> v20.12.2)")
    @patch("web.service_tools.auto_update_node.get_current_version", return_value="v20.12.2")
    @patch("web.service_tools.auto_update_node.get_latest_version", return_value="v22.1.0")
    @patch("web.service_tools.auto_update_node.get_current_lts_version", return_value="v20.12.2")
    @patch("web.service_tools.auto_update_node.load_notification_configs_from_state", return_value=["cfg"])
    @patch("web.service_tools.auto_update_node.os.path.exists", return_value=True)
    @patch("web.service_tools.auto_update_node.get_nvm_dir", return_value="/home/user/.nvm")
    def test_main_notifies_on_global_package_failure(
        self,
        _nvm_dir,
        _exists,
        _configs,
        _lts,
        _latest,
        _current,
        _alias,
        mock_install,
        _update_packages,
        mock_notify,
    ):
        result = auto_update_node.main()
        self.assertEqual(result, 1)
        mock_install.assert_not_called()
        mock_notify.assert_called_once()
        self.assertIn("Failed to update global Node.js packages", mock_notify.call_args.kwargs["message"])

    @patch("web.service_tools.auto_update_node.send_notification_safe")
    @patch("web.service_tools.auto_update_node.update_global_packages", return_value=(True, ""))
    @patch("web.service_tools.auto_update_node.install_target_version")
    @patch("web.service_tools.auto_update_node.get_default_alias", return_value="default -> node (-> v22.1.0)")
    @patch("web.service_tools.auto_update_node.get_current_version", return_value="v22.1.0")
    @patch("web.service_tools.auto_update_node.get_latest_version", return_value="v22.1.0")
    @patch("web.service_tools.auto_update_node.get_current_lts_version", return_value="v20.12.2")
    @patch("web.service_tools.auto_update_node.load_notification_configs_from_state", return_value=[])
    @patch("web.service_tools.auto_update_node.os.path.exists", return_value=True)
    @patch("web.service_tools.auto_update_node.get_nvm_dir", return_value="/home/user/.nvm")
    def test_main_logs_structured_up_to_date_message(
        self,
        _nvm_dir,
        _exists,
        _configs,
        _lts,
        _latest,
        _current,
        _alias,
        mock_install,
        mock_update_packages,
        mock_notify,
    ):
        with self.assertLogs(auto_update_node.logger, level="INFO") as logs:
            result = auto_update_node.main()
        self.assertEqual(result, 0)
        mock_install.assert_not_called()
        mock_update_packages.assert_called_once()
        mock_notify.assert_called_once()
        joined = "\n".join(logs.output)
        self.assertIn("Node.js already up to date |", joined)
        self.assertIn("current_version='v22.1.0'", joined)
        self.assertIn("target_version='v22.1.0'", joined)
        self.assertIn("update_track='latest'", joined)

    @patch("web.service_tools.auto_update_node.send_notification_safe")
    @patch("web.service_tools.auto_update_node.load_notification_configs_from_state", return_value=[])
    @patch("web.service_tools.auto_update_node.os.path.exists", return_value=False)
    @patch("web.service_tools.auto_update_node.get_nvm_dir", return_value="/home/user/.nvm")
    def test_main_logs_structured_nvm_missing_error(
        self,
        _nvm_dir,
        _exists,
        _configs,
        mock_notify,
    ):
        with self.assertLogs(auto_update_node.logger, level="ERROR") as logs:
            result = auto_update_node.main()
        self.assertEqual(result, 1)
        mock_notify.assert_called_once()
        self.assertIn("nvm directory not found | nvm_dir='/home/user/.nvm'", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
