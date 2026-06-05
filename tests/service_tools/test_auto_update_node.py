"""Tests for web.service_tools.auto_update_node."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from web.service_tools import auto_update_node
from lib.update_policy import DEPENDENCY_MIN_AGE_DAYS_ENV, ECOSYSTEM_AUTO_UPGRADE_ENV


class TestAutoUpdateNode(unittest.TestCase):
    def test_select_installed_latest_track_from_versions_newer_than_lts(self):
        self.assertEqual(
            auto_update_node.select_installed_latest_track_version(
                ["v20.12.2", "v22.1.0", "v22.2.0"],
                "v20.12.2",
                "v22.3.0",
            ),
            "v22.2.0",
        )

    def test_select_installed_latest_track_when_remote_latest_unknown(self):
        self.assertEqual(
            auto_update_node.select_installed_latest_track_version(
                ["v20.12.2", "v22.1.0"],
                "v20.12.2",
                "",
            ),
            "v22.1.0",
        )

    @patch("web.service_tools.auto_update_node.run_nvm_command")
    def test_get_installed_versions_ignores_alias_targets(self, mock_run_nvm):
        mock_run_nvm.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="""
->     v20.12.2
default -> lts/* (-> v20.12.2)
node -> stable (-> v22.3.0) (default)
stable -> 22.3 (-> v22.3.0) (default)
""",
            stderr="",
        )

        self.assertEqual(auto_update_node.get_installed_versions(), ["v20.12.2"])

    @patch("web.service_tools.auto_update_node.run_nvm_command")
    def test_global_package_updates_skip_by_default(self, mock_run_nvm):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertLogs(auto_update_node.logger, level="INFO") as logs:
                success, details = auto_update_node.update_global_packages()

        self.assertTrue(success)
        self.assertIsNone(details)
        mock_run_nvm.assert_not_called()
        self.assertIn("Node.js global package auto-upgrades disabled by policy", "\n".join(logs.output))

    @patch("web.service_tools.auto_update_node.run_nvm_command")
    def test_global_package_updates_can_be_enabled(self, mock_run_nvm):
        mock_run_nvm.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        with patch.dict(os.environ, {ECOSYSTEM_AUTO_UPGRADE_ENV: "1", DEPENDENCY_MIN_AGE_DAYS_ENV: "2"}):
            success, details = auto_update_node.update_global_packages()

        self.assertTrue(success)
        self.assertIsNone(details)
        self.assertEqual(mock_run_nvm.call_count, 3)
        for call_args in mock_run_nvm.call_args_list:
            self.assertTrue(any(arg.startswith("--before=") for arg in call_args.args[0]))

    @patch("web.service_tools.auto_update_node.subprocess.run")
    @patch("web.service_tools.auto_update_node.get_nvm_dir", return_value="/home/user/.nvm")
    def test_run_nvm_command_uses_bash_argv(self, _nvm_dir, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(args=["/bin/bash"], returncode=0)
        auto_update_node.run_nvm_command(["nvm", "version", "default"])
        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        self.assertEqual(args[0][:2], ["/bin/bash", "-lc"])
        self.assertIn("nvm version default", args[0][2])
        self.assertEqual(kwargs["cwd"], "/home/user")
        self.assertEqual(kwargs["env"]["HOME"], "/home/user")
        self.assertIn("USER", kwargs["env"])
        self.assertIn("LOGNAME", kwargs["env"])
        self.assertNotIn("shell", kwargs)

    @patch("web.service_tools.auto_update_node.cleanup_old_versions", return_value=(True, None))
    @patch("web.service_tools.auto_update_node.send_notification_safe")
    @patch("web.service_tools.auto_update_node.update_global_packages", return_value=(True, ""))
    @patch("web.service_tools.auto_update_node.set_default_lts_alias", return_value=True)
    @patch("web.service_tools.auto_update_node.install_target_version", return_value=(True, None))
    @patch("web.service_tools.auto_update_node.get_installed_versions", return_value=["v20.12.2", "v22.1.0"])
    @patch("web.service_tools.auto_update_node.get_current_version", return_value="v20.12.2")
    @patch("web.service_tools.auto_update_node.get_latest_version", return_value="v22.2.0")
    @patch("web.service_tools.auto_update_node.get_current_lts_version", return_value="v20.12.2")
    @patch("web.service_tools.auto_update_node.load_notification_configs_from_state", return_value=[])
    @patch("web.service_tools.auto_update_node.os.path.exists", return_value=True)
    @patch("web.service_tools.auto_update_node.get_nvm_dir", return_value="/home/user/.nvm")
    def test_main_updates_installed_latest_track_while_defaulting_lts(
        self,
        _nvm_dir,
        _exists,
        _configs,
        _lts,
        _latest,
        _current,
        _installed_versions,
        mock_install,
        mock_set_default,
        mock_update_packages,
        mock_notify,
        _cleanup,
    ):
        result = auto_update_node.main()
        self.assertEqual(result, 0)
        mock_install.assert_called_once_with("latest", "v22.2.0", "v22.1.0")
        mock_set_default.assert_called_once()
        mock_update_packages.assert_called_once()
        mock_notify.assert_called_once()
        self.assertIn("Success", mock_notify.call_args.kwargs["subject"])

    @patch("web.service_tools.auto_update_node.cleanup_old_versions", return_value=(True, None))
    @patch("web.service_tools.auto_update_node.send_notification_safe")
    @patch(
        "web.service_tools.auto_update_node.update_global_packages",
        return_value=(False, "Updated pnpm: permission denied"),
    )
    @patch("web.service_tools.auto_update_node.set_default_lts_alias", return_value=True)
    @patch("web.service_tools.auto_update_node.install_target_version", return_value=(True, None))
    @patch("web.service_tools.auto_update_node.get_installed_versions", return_value=["v20.12.2"])
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
        _installed_versions,
        mock_install,
        _set_default,
        _update_packages,
        mock_notify,
        _cleanup,
    ):
        result = auto_update_node.main()
        self.assertEqual(result, 1)
        mock_install.assert_not_called()
        mock_notify.assert_called_once()
        self.assertIn("Failed to update global Node.js packages", mock_notify.call_args.kwargs["message"])

    @patch("web.service_tools.auto_update_node.cleanup_old_versions", return_value=(True, None))
    @patch("web.service_tools.auto_update_node.send_notification_safe")
    @patch("web.service_tools.auto_update_node.update_global_packages", return_value=(True, ""))
    @patch("web.service_tools.auto_update_node.set_default_lts_alias", return_value=True)
    @patch("web.service_tools.auto_update_node.install_target_version", return_value=(True, None))
    @patch("web.service_tools.auto_update_node.get_installed_versions", return_value=["v20.12.2"])
    @patch("web.service_tools.auto_update_node.get_current_version", return_value="v20.12.2")
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
        _installed_versions,
        mock_install,
        _set_default,
        mock_update_packages,
        mock_notify,
        _cleanup,
    ):
        with self.assertLogs(auto_update_node.logger, level="INFO") as logs:
            result = auto_update_node.main()
        self.assertEqual(result, 0)
        mock_install.assert_not_called()
        mock_update_packages.assert_called_once()
        mock_notify.assert_called_once()
        joined = "\n".join(logs.output)
        self.assertIn("Node.js LTS already up to date |", joined)
        self.assertIn("current_version='v20.12.2'", joined)
        self.assertIn("target_version='v20.12.2'", joined)
        self.assertIn("update_track='LTS'", joined)

    @patch("web.service_tools.auto_update_node.run_nvm_command")
    def test_install_target_reinstalls_packages_with_freshness_cutoff(self, mock_run_nvm):
        def run_command(args):
            if args[:6] == ["nvm", "exec", "v20.12.2", "npm", "list", "-g"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout='{"dependencies":{"pnpm":{},"typescript":{},"npm":{}}}', stderr="")
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

        mock_run_nvm.side_effect = run_command

        with patch.dict(os.environ, {DEPENDENCY_MIN_AGE_DAYS_ENV: "2"}):
            success, details = auto_update_node.install_target_version("lts", "v20.12.3", "v20.12.2")

        self.assertTrue(success)
        self.assertIsNone(details)
        commands = [call_args.args[0] for call_args in mock_run_nvm.call_args_list]
        self.assertIn(["nvm", "alias", "default", "lts/*"], commands)
        reinstall_commands = [command for command in commands if command[:6] == ["nvm", "exec", "v20.12.3", "npm", "install", "-g"]]
        self.assertEqual(len(reinstall_commands), 2)
        self.assertTrue(all(any(arg.startswith("--before=") for arg in command) for command in reinstall_commands))
        self.assertIn("pnpm", reinstall_commands[1])
        self.assertIn("typescript", reinstall_commands[1])

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
