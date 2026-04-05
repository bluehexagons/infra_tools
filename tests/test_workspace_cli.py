"""Tests for workspace-aware CLI parsing and user setup behavior."""

from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import common.common_steps as common_steps
import infra_tools
from lib.arg_parser import create_setup_argument_parser
from lib.config import SetupConfig
from argparse import Namespace


class TestWorkspaceCli(unittest.TestCase):
    def test_setup_parser_accepts_workspace(self):
        parser = create_setup_argument_parser("test")
        args = parser.parse_args(["example.com", "--workspace", "/tmp/workspace"])
        self.assertEqual(args.workspace, "/tmp/workspace")

    def test_infra_tools_parser_accepts_credentials_command(self):
        parser, _setup_parser, _patch_parser = infra_tools.create_infra_tools_parser()
        args = parser.parse_args(["credentials", "--workspace", "/tmp/workspace", "list"])
        self.assertEqual(args.command, "credentials")
        self.assertEqual(args.workspace, "/tmp/workspace")
        self.assertEqual(args.credentials_command, "list")

    @patch("builtins.print")
    @patch("infra_tools.set_workspace_credential", side_effect=ValueError("Credential username must not contain ':'"))
    def test_infra_tools_credentials_set_rejects_invalid_username(
        self,
        _mock_set_credential,
        mock_print,
    ):
        parser = unittest.mock.MagicMock()
        setup_parser = unittest.mock.MagicMock()
        patch_parser = unittest.mock.MagicMock()
        args = unittest.mock.MagicMock()
        args.command = "credentials"
        args.credentials_command = "set"
        args.username = "bad:user"
        args.password = "secret"
        args.workspace = None
        parser.parse_args.return_value = args

        with patch(
            "infra_tools.create_infra_tools_parser",
            return_value=(parser, setup_parser, patch_parser),
        ):
            result = infra_tools.main()

        self.assertEqual(result, 1)
        mock_print.assert_called_with("Error: Credential username must not contain ':'")

    @patch("builtins.print")
    @patch("infra_tools.validate_workspace_dir", side_effect=ValueError("bad workspace"))
    @patch("infra_tools.set_workspace_dir")
    def test_infra_tools_main_rejects_invalid_workspace(
        self,
        mock_set_workspace,
        _mock_validate_workspace,
        mock_print,
    ):
        parser = unittest.mock.MagicMock()
        setup_parser = unittest.mock.MagicMock()
        patch_parser = unittest.mock.MagicMock()
        args = unittest.mock.MagicMock()
        args.workspace = "/bad/workspace"
        parser.parse_args.return_value = args

        with patch(
            "infra_tools.create_infra_tools_parser",
            return_value=(parser, setup_parser, patch_parser),
        ):
            result = infra_tools.main()

        self.assertEqual(result, 1)
        mock_set_workspace.assert_not_called()
        mock_print.assert_called_with("Error: bad workspace")

    @patch("builtins.print")
    @patch("infra_tools.validate_samba_share_credentials")
    @patch("infra_tools.prepare_runtime_config")
    @patch("infra_tools.validate_username", return_value=True)
    @patch("infra_tools.validate_host", return_value=True)
    def test_run_setup_command_rejects_invalid_notify_specs(
        self,
        _mock_validate_host,
        _mock_validate_username,
        mock_prepare_runtime_config,
        _mock_validate_samba,
        mock_print,
    ):
        config = SetupConfig(
            host="example.com",
            username="testuser",
            system_type="server_lite",
            notify_specs=[["webhook", "not-a-url"]],
        )
        mock_prepare_runtime_config.return_value = config
        args = Namespace(host="example.com", username="testuser", system_type="server_lite")

        with patch("infra_tools.SetupConfig.from_args", return_value=config), \
             patch("infra_tools.run_remote_setup") as mock_run_remote:
            result = infra_tools.run_setup_command(args)

        self.assertEqual(result, 1)
        mock_run_remote.assert_not_called()
        mock_print.assert_called_with("Error: Invalid webhook URL: not-a-url")

    @patch("builtins.print")
    @patch("infra_tools.validate_samba_share_credentials")
    @patch("infra_tools.prepare_runtime_config")
    @patch("infra_tools.validate_username", return_value=True)
    @patch("infra_tools.validate_host", return_value=True)
    def test_run_setup_command_rejects_invalid_deploy_target(
        self,
        _mock_validate_host,
        _mock_validate_username,
        mock_prepare_runtime_config,
        _mock_validate_samba,
        mock_print,
    ):
        config = SetupConfig(
            host="example.com",
            username="testuser",
            system_type="server_lite",
            deploy_targets=["bad target"],
        )
        mock_prepare_runtime_config.return_value = config
        args = Namespace(host="example.com", username="testuser", system_type="server_lite")

        with patch("infra_tools.SetupConfig.from_args", return_value=config), \
             patch("infra_tools.run_remote_setup") as mock_run_remote:
            result = infra_tools.run_setup_command(args)

        self.assertEqual(result, 1)
        mock_run_remote.assert_not_called()
        mock_print.assert_called_with("Error: Invalid deploy target host: bad target")

    @patch("builtins.print")
    @patch("infra_tools.validate_samba_share_credentials")
    @patch("infra_tools.prepare_runtime_config")
    @patch("infra_tools.validate_username", return_value=True)
    @patch("infra_tools.validate_host", return_value=True)
    def test_run_setup_command_rejects_invalid_deploy_spec(
        self,
        _mock_validate_host,
        _mock_validate_username,
        mock_prepare_runtime_config,
        _mock_validate_samba,
        mock_print,
    ):
        config = SetupConfig(
            host="example.com",
            username="testuser",
            system_type="server_lite",
            deploy_specs=[["bad domain", "https://github.com/user/repo.git"]],
        )
        mock_prepare_runtime_config.return_value = config
        args = Namespace(host="example.com", username="testuser", system_type="server_lite")

        with patch("infra_tools.SetupConfig.from_args", return_value=config), \
             patch("infra_tools.run_remote_setup") as mock_run_remote:
            result = infra_tools.run_setup_command(args)

        self.assertEqual(result, 1)
        mock_run_remote.assert_not_called()
        mock_print.assert_called_with("Error: Invalid deploy domain: bad domain")

    @patch("builtins.print")
    @patch("infra_tools.validate_samba_share_credentials")
    @patch("infra_tools.prepare_runtime_config")
    @patch("infra_tools.validate_username", return_value=True)
    @patch("infra_tools.validate_host", return_value=True)
    def test_run_setup_command_rejects_invalid_hosted_node(
        self,
        _mock_validate_host,
        _mock_validate_username,
        mock_prepare_runtime_config,
        _mock_validate_samba,
        mock_print,
    ):
        config = SetupConfig(
            host="example.com",
            username="testuser",
            system_type="server_lite",
            hosted_node="bad host",
            container_memory="2G",
            container_storage=[["root", "auto", "10G"]],
        )
        mock_prepare_runtime_config.return_value = config
        args = Namespace(host="example.com", username="testuser", system_type="server_lite")

        with patch("infra_tools.SetupConfig.from_args", return_value=config), \
             patch("infra_tools.run_remote_setup") as mock_run_remote:
            result = infra_tools.run_setup_command(args)

        self.assertEqual(result, 1)
        mock_run_remote.assert_not_called()
        mock_print.assert_called_with("Error: Invalid hosted node host: bad host")

    @patch("builtins.print")
    @patch("infra_tools.validate_samba_share_credentials")
    @patch("infra_tools.prepare_runtime_config")
    @patch("infra_tools.load_setup_command")
    @patch("infra_tools.validate_username", return_value=True)
    @patch("infra_tools.validate_host", return_value=True)
    def test_run_patch_command_rejects_invalid_notify_specs(
        self,
        _mock_validate_host,
        _mock_validate_username,
        mock_load_setup_command,
        mock_prepare_runtime_config,
        _mock_validate_samba,
        mock_print,
    ):
        cached = SetupConfig(host="example.com", username="testuser", system_type="server_lite")
        merged = SetupConfig(
            host="example.com",
            username="testuser",
            system_type="server_lite",
            notify_specs=[["mailbox", "bad-email"]],
        )
        mock_load_setup_command.return_value = cached
        mock_prepare_runtime_config.return_value = merged
        args = Namespace(host="example.com", username="testuser")

        with patch("infra_tools.SetupConfig.from_args", return_value=merged), \
             patch("infra_tools.merge_setup_configs", return_value=merged), \
             patch("infra_tools.run_remote_setup") as mock_run_remote:
            result = infra_tools.run_patch_command(args)

        self.assertEqual(result, 1)
        mock_run_remote.assert_not_called()
        mock_print.assert_called_with("Error: Invalid mailbox address: bad-email")

    @patch("builtins.print")
    @patch("infra_tools.validate_samba_share_credentials")
    @patch("infra_tools.prepare_runtime_config")
    @patch("infra_tools.load_setup_command")
    @patch("infra_tools.validate_username", return_value=True)
    @patch("infra_tools.validate_host", return_value=True)
    def test_run_patch_command_rejects_invalid_deploy_target(
        self,
        _mock_validate_host,
        _mock_validate_username,
        mock_load_setup_command,
        mock_prepare_runtime_config,
        _mock_validate_samba,
        mock_print,
    ):
        cached = SetupConfig(host="example.com", username="testuser", system_type="server_lite")
        merged = SetupConfig(
            host="example.com",
            username="testuser",
            system_type="server_lite",
            deploy_targets=["bad target"],
        )
        mock_load_setup_command.return_value = cached
        mock_prepare_runtime_config.return_value = merged
        args = Namespace(host="example.com", username="testuser")

        with patch("infra_tools.SetupConfig.from_args", return_value=merged), \
             patch("infra_tools.merge_setup_configs", return_value=merged), \
             patch("infra_tools.run_remote_setup") as mock_run_remote:
            result = infra_tools.run_patch_command(args)

        self.assertEqual(result, 1)
        mock_run_remote.assert_not_called()
        mock_print.assert_called_with("Error: Invalid deploy target host: bad target")

    @patch("builtins.print")
    @patch("infra_tools.validate_samba_share_credentials")
    @patch("infra_tools.prepare_runtime_config")
    @patch("infra_tools.load_setup_command")
    @patch("infra_tools.validate_username", return_value=True)
    @patch("infra_tools.validate_host", return_value=True)
    def test_run_patch_command_rejects_invalid_deploy_spec(
        self,
        _mock_validate_host,
        _mock_validate_username,
        mock_load_setup_command,
        mock_prepare_runtime_config,
        _mock_validate_samba,
        mock_print,
    ):
        cached = SetupConfig(host="example.com", username="testuser", system_type="server_lite")
        merged = SetupConfig(
            host="example.com",
            username="testuser",
            system_type="server_lite",
            deploy_specs=[["bad domain", "https://github.com/user/repo.git"]],
        )
        mock_load_setup_command.return_value = cached
        mock_prepare_runtime_config.return_value = merged
        args = Namespace(host="example.com", username="testuser")

        with patch("infra_tools.SetupConfig.from_args", return_value=merged), \
             patch("infra_tools.merge_setup_configs", return_value=merged), \
             patch("infra_tools.run_remote_setup") as mock_run_remote:
            result = infra_tools.run_patch_command(args)

        self.assertEqual(result, 1)
        mock_run_remote.assert_not_called()
        mock_print.assert_called_with("Error: Invalid deploy domain: bad domain")

    @patch("builtins.print")
    @patch("infra_tools.validate_samba_share_credentials")
    @patch("infra_tools.prepare_runtime_config")
    @patch("infra_tools.load_setup_command")
    @patch("infra_tools.validate_username", return_value=True)
    @patch("infra_tools.validate_host", return_value=True)
    def test_run_patch_command_rejects_invalid_hosted_node(
        self,
        _mock_validate_host,
        _mock_validate_username,
        mock_load_setup_command,
        mock_prepare_runtime_config,
        _mock_validate_samba,
        mock_print,
    ):
        cached = SetupConfig(host="example.com", username="testuser", system_type="server_lite")
        merged = SetupConfig(
            host="example.com",
            username="testuser",
            system_type="server_lite",
            hosted_node="bad host",
            container_memory="2G",
            container_storage=[["root", "auto", "10G"]],
        )
        mock_load_setup_command.return_value = cached
        mock_prepare_runtime_config.return_value = merged
        args = Namespace(host="example.com", username="testuser")

        with patch("infra_tools.SetupConfig.from_args", return_value=merged), \
             patch("infra_tools.merge_setup_configs", return_value=merged), \
             patch("infra_tools.run_remote_setup") as mock_run_remote:
            result = infra_tools.run_patch_command(args)

        self.assertEqual(result, 1)
        mock_run_remote.assert_not_called()
        mock_print.assert_called_with("Error: Invalid hosted node host: bad host")


class TestSetupUserPasswordless(unittest.TestCase):
    @patch("builtins.print")
    @patch("common.common_steps.set_user_password")
    @patch("common.common_steps.run")
    def test_new_user_without_password_skips_password_generation(self, mock_run, mock_set_password, mock_print):
        mock_run.side_effect = lambda *args, **kwargs: SimpleNamespace(returncode=1)
        config = SetupConfig(host="host", username="user", system_type="server_lite")

        common_steps.setup_user(config)

        mock_set_password.assert_not_called()
        commands = [call_args.args[0] for call_args in mock_run.call_args_list]
        self.assertTrue(any(command.startswith("useradd -m -s /bin/bash") for command in commands))
        mock_print.assert_any_call("  No password configured; relying on SSH key authentication")


if __name__ == "__main__":
    unittest.main()
