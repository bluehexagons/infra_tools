"""Tests for Python tooling setup flag and local installer wiring."""

from __future__ import annotations

import argparse
import os
import sys
import unittest
from unittest.mock import call, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.arg_parser import create_setup_argument_parser
from lib.config import SetupConfig
from lib.system_types import get_steps_for_system_type
import common.common_steps as common_steps
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
        self.assertIn("Installing Python tooling (aliases + uv)", step_names)
        self.assertIn("Configuring uv auto-update", step_names)

    @patch("common.common_steps.install_or_update_uv", return_value=True)
    @patch("common.common_steps.shutil.which", side_effect=["/usr/bin/python3", "/usr/bin/python"])
    @patch("common.common_steps._find_setup_completions_script", return_value="/opt/infra_tools/setup_completions.py")
    @patch("common.common_steps.run")
    def test_remote_install_python_skips_completion(self, mock_run, _find, _which, _install_uv):
        config = SetupConfig(host="host", username="user", system_type="server_dev", install_python=True)
        common_steps.install_python(config)
        commands = [args[0] for args, _ in mock_run.call_args_list]
        self.assertFalse(any("setup_completions.py" in cmd for cmd in commands))


class TestSetupAdminPython(unittest.TestCase):
    @patch("setup_admin_python.os.path.expanduser", return_value="/tmp/testuser")
    @patch("setup_admin_python.subprocess.run")
    @patch("setup_admin_python.install_or_update_uv", return_value=True)
    @patch("setup_admin_python.validate_username", return_value=True)
    @patch("setup_admin_python.parse_args", return_value=argparse.Namespace(shell="bash"))
    @patch("setup_admin_python.get_current_username", return_value="admin")
    @patch("setup_admin_python.shutil.which", side_effect=["/usr/bin/python3"])
    def test_main_runs_shared_setup_steps(
        self,
        _which,
        _current_username,
        _parse_args,
        _validate_username,
        mock_install_or_update_uv,
        mock_subprocess_run,
        _expanduser,
    ):
        mock_subprocess_run.return_value = argparse.Namespace(returncode=0, stdout="", stderr="")
        with patch("setup_admin_python.os.path.exists", side_effect=lambda p: str(p).endswith("setup_completions.py")):
            result = setup_admin_python.main()
        self.assertEqual(result, 0)
        mock_install_or_update_uv.assert_called_once()
        _which.assert_has_calls([call("python3")])

    @patch("setup_admin_python.validate_username", return_value=False)
    @patch("setup_admin_python.parse_args", return_value=argparse.Namespace(shell="bash"))
    @patch("setup_admin_python.get_current_username", return_value="invalid user")
    def test_main_rejects_invalid_username(self, _current_username, _parse_args, _validate_username):
        result = setup_admin_python.main()
        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
