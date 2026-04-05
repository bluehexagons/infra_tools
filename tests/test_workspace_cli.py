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
