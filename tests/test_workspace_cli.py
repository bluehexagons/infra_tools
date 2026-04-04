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


class TestSetupUserPasswordless(unittest.TestCase):
    @patch("builtins.print")
    @patch("common.common_steps.set_user_password")
    @patch("common.common_steps.run")
    def test_new_user_without_password_skips_password_generation(self, mock_run, mock_set_password, mock_print):
        mock_run.side_effect = lambda *args, **kwargs: SimpleNamespace(returncode=1)
        config = SetupConfig(host="host", username="user", system_type="server_lite")

        common_steps.setup_user(config)

        mock_set_password.assert_not_called()
        mock_print.assert_any_call("  No password configured; relying on SSH key authentication")


if __name__ == "__main__":
    unittest.main()
