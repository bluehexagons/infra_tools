"""Tests for patch_setup CLI help output."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import patch_setup


class TestPatchSetupHelp(unittest.TestCase):
    def test_help_lists_special_patch_commands(self):
        help_text = patch_setup.create_patch_argument_parser().format_help()

        self.assertIn("Special commands:", help_text)
        self.assertIn("patch_setup.py list [pattern]", help_text)
        self.assertIn("patch_setup.py info [pattern]", help_text)
        self.assertIn("patch_setup.py rm [pattern]", help_text)
        self.assertIn("patch_setup.py deploy [pattern]", help_text)


class TestPatchSetupWorkspaceValidation(unittest.TestCase):
    def test_process_workspace_args_rejects_invalid_workspace(self):
        with unittest.mock.patch("patch_setup.validate_workspace_dir", side_effect=ValueError("bad workspace")):
            with self.assertRaisesRegex(ValueError, "bad workspace"):
                patch_setup._process_workspace_args(["--workspace", "/bad/workspace", "list"])


class TestPatchSetupDeployTargetValidation(unittest.TestCase):
    @patch("builtins.print")
    @patch("patch_setup.prepare_runtime_config")
    @patch("patch_setup.os.path.exists", return_value=True)
    @patch("patch_setup.validate_username", return_value=True)
    def test_execute_patch_rejects_invalid_deploy_target(
        self,
        _mock_validate_username,
        _mock_exists,
        mock_prepare_runtime_config,
        mock_print,
    ):
        config = patch_setup.SetupConfig(
            host="example.com",
            username="testuser",
            system_type="server_lite",
            deploy_targets=["bad target"],
        )
        mock_prepare_runtime_config.return_value = config

        result = patch_setup.execute_patch(config)

        self.assertEqual(result, 1)
        mock_print.assert_called_with("Error: Invalid deploy target host: bad target")

    @patch("builtins.print")
    @patch("patch_setup.prepare_runtime_config")
    @patch("patch_setup.os.path.exists", return_value=True)
    @patch("patch_setup.validate_username", return_value=True)
    def test_execute_patch_rejects_invalid_deploy_spec(
        self,
        _mock_validate_username,
        _mock_exists,
        mock_prepare_runtime_config,
        mock_print,
    ):
        config = patch_setup.SetupConfig(
            host="example.com",
            username="testuser",
            system_type="server_lite",
            deploy_specs=[["bad domain", "https://github.com/user/repo.git"]],
        )
        mock_prepare_runtime_config.return_value = config

        result = patch_setup.execute_patch(config)

        self.assertEqual(result, 1)
        mock_print.assert_called_with("Error: Invalid deploy domain: bad domain")

    @patch("builtins.print")
    @patch("patch_setup.prepare_runtime_config")
    @patch("patch_setup.os.path.exists", return_value=True)
    @patch("patch_setup.validate_username", return_value=True)
    def test_execute_patch_rejects_invalid_sync_spec(
        self,
        _mock_validate_username,
        _mock_exists,
        mock_prepare_runtime_config,
        mock_print,
    ):
        config = patch_setup.SetupConfig(
            host="example.com",
            username="testuser",
            system_type="server_lite",
            sync_specs=[["relative", "/dst", "daily"]],
        )
        mock_prepare_runtime_config.return_value = config

        result = patch_setup.execute_patch(config)

        self.assertEqual(result, 1)
        mock_print.assert_called_with("Error: Source path must be absolute: relative")

    @patch("builtins.print")
    @patch("patch_setup.prepare_runtime_config")
    @patch("patch_setup.os.path.exists", return_value=True)
    @patch("patch_setup.validate_username", return_value=True)
    def test_execute_patch_rejects_invalid_scrub_spec(
        self,
        _mock_validate_username,
        _mock_exists,
        mock_prepare_runtime_config,
        mock_print,
    ):
        config = patch_setup.SetupConfig(
            host="example.com",
            username="testuser",
            system_type="server_lite",
            scrub_specs=[["/data", ".pardatabase", "0%", "weekly"]],
        )
        mock_prepare_runtime_config.return_value = config

        result = patch_setup.execute_patch(config)

        self.assertEqual(result, 1)
        mock_print.assert_called_with("Error: Redundancy percentage must be between 1 and 100: 0%")

    @patch("builtins.print")
    @patch("patch_setup.prepare_runtime_config")
    @patch("patch_setup.os.path.exists", return_value=True)
    @patch("patch_setup.validate_username", return_value=True)
    def test_execute_patch_rejects_invalid_smb_mount_spec(
        self,
        _mock_validate_username,
        _mock_exists,
        mock_prepare_runtime_config,
        mock_print,
    ):
        config = patch_setup.SetupConfig(
            host="example.com",
            username="testuser",
            system_type="server_lite",
            smb_mounts=[["/mnt/share", "bad host", "user:pass", "docs", "/sub"]],
        )
        mock_prepare_runtime_config.return_value = config

        result = patch_setup.execute_patch(config)

        self.assertEqual(result, 1)
        mock_print.assert_called_with("Error: Invalid SMB mount host: bad host")

    @patch("builtins.print")
    @patch("patch_setup.prepare_runtime_config")
    @patch("patch_setup.os.path.exists", return_value=True)
    @patch("patch_setup.validate_username", return_value=True)
    def test_execute_patch_rejects_invalid_samba_share_spec(
        self,
        _mock_validate_username,
        _mock_exists,
        mock_prepare_runtime_config,
        mock_print,
    ):
        config = patch_setup.SetupConfig(
            host="example.com",
            username="testuser",
            system_type="server_lite",
            samba_shares=[["read", "bad/share", "/mnt/docs", "shareuser:secret"]],
        )
        mock_prepare_runtime_config.return_value = config

        result = patch_setup.execute_patch(config)

        self.assertEqual(result, 1)
        mock_print.assert_called_with("Error: Invalid Samba share name (cannot contain /, \\, or spaces): bad/share")


if __name__ == "__main__":
    unittest.main()
