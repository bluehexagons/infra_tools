"""Tests for Python tooling setup flag and local installer wiring."""

from __future__ import annotations

import argparse
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.arg_parser import create_setup_argument_parser
from lib.config import SetupConfig
from lib.system_types import get_steps_for_system_type
import setup_admin_python


class TestPythonFlag(unittest.TestCase):
    def test_parser_accepts_python_flag(self):
        parser = create_setup_argument_parser("test")
        args = parser.parse_args(["example.com", "--python"])
        self.assertTrue(args.install_python)

    def test_python_steps_added_when_enabled(self):
        config = SetupConfig(
            host="host",
            username="user",
            system_type="server_dev",
            install_python=True,
        )
        step_names = [name for name, _ in get_steps_for_system_type(config)]
        self.assertIn("Installing Python tooling (aliases + uv + completion)", step_names)
        self.assertIn("Configuring uv auto-update", step_names)


class TestSetupAdminPython(unittest.TestCase):
    @patch("setup_admin_python.configure_auto_update_uv")
    @patch("setup_admin_python.install_python")
    @patch("setup_admin_python.validate_username", return_value=True)
    @patch("setup_admin_python.parse_args", return_value=argparse.Namespace(username="admin"))
    @patch("setup_admin_python.os.geteuid", return_value=0)
    def test_main_runs_shared_setup_steps(
        self,
        _geteuid,
        _parse_args,
        _validate_username,
        mock_install_python,
        mock_configure_auto_update_uv,
    ):
        result = setup_admin_python.main()
        self.assertEqual(result, 0)
        mock_install_python.assert_called_once()
        mock_configure_auto_update_uv.assert_called_once()


if __name__ == "__main__":
    unittest.main()
