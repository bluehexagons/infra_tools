"""Tests for lib/remote_utils.py: dry-run mode, validation, password generation, file_contains."""

from __future__ import annotations

import os
import string
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.remote_utils import (
    CommandExecutionError,
    set_dry_run,
    is_dry_run,
    generate_password,
    get_user_home,
    run,
    file_contains,
    detect_os,
)
from lib.validators import validate_username


class TestDryRun(unittest.TestCase):
    def setUp(self):
        set_dry_run(False)

    def tearDown(self):
        set_dry_run(False)

    def test_default_not_dry_run(self):
        self.assertFalse(is_dry_run())

    def test_set_dry_run_true(self):
        set_dry_run(True)
        self.assertTrue(is_dry_run())

    def test_set_dry_run_false(self):
        set_dry_run(True)
        set_dry_run(False)
        self.assertFalse(is_dry_run())


class TestRunDryRun(unittest.TestCase):
    def setUp(self):
        set_dry_run(True)

    def tearDown(self):
        set_dry_run(False)

    def test_dry_run_returns_zero(self):
        result = run("echo hello")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_dry_run_type(self):
        result = run("echo hello")
        self.assertIsInstance(result, subprocess.CompletedProcess)


class TestRunCommandDispatch(unittest.TestCase):
    @patch("lib.remote_utils.subprocess.run")
    def test_simple_commands_use_argument_list(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(args=["echo", "hello"], returncode=0)
        run("echo hello")
        mock_run.assert_called_once_with(
            ["echo", "hello"],
            capture_output=False,
            text=True,
            cwd=None,
        )

    @patch("lib.remote_utils.subprocess.run")
    def test_piped_commands_use_explicit_shell_process(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(args=["/bin/bash", "-lc", "echo test | cat"], returncode=0)
        run("echo test | cat")
        mock_run.assert_called_once_with(
            ["/bin/bash", "-lc", "echo test | cat"],
            capture_output=False,
            text=True,
            cwd=None,
        )

    @patch("lib.remote_utils.subprocess.run")
    def test_check_true_raises_for_failed_command(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["false"], returncode=17, stderr="permission denied"
        )

        with self.assertRaises(CommandExecutionError) as raised:
            run("false", display_cmd="false (sanitized)")

        error = raised.exception
        self.assertEqual(error.command, "false (sanitized)")
        self.assertEqual(error.returncode, 17)
        self.assertEqual(error.stderr, "permission denied")
        self.assertIs(error.result, mock_run.return_value)

    @patch("lib.remote_utils.subprocess.run")
    def test_check_false_returns_failed_result(self, mock_run):
        failed = subprocess.CompletedProcess(args=["false"], returncode=17, stderr="failed")
        mock_run.return_value = failed

        result = run("false", check=False)

        self.assertIs(result, failed)

    @patch("lib.remote_utils.subprocess.run")
    def test_failure_diagnostics_redact_secret_values(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["deploy"],
            returncode=1,
            stderr="SECRET_KEY_BASE=stderr-secret --token cli-secret",
        )

        with self.assertRaises(CommandExecutionError) as raised:
            run("deploy SECRET_KEY_BASE=command-secret --password option-secret")

        message = str(raised.exception)
        self.assertNotIn("command-secret", message)
        self.assertNotIn("option-secret", message)
        self.assertNotIn("stderr-secret", message)
        self.assertNotIn("cli-secret", message)
        self.assertIn("SECRET_KEY_BASE=<redacted>", message)


class TestRemoteValidateUsername(unittest.TestCase):
    def test_valid(self):
        self.assertTrue(validate_username('admin'))

    def test_invalid(self):
        self.assertFalse(validate_username('Admin'))


class TestDetectOS(unittest.TestCase):
    @patch("lib.remote_utils.read_os_release", return_value={"ID": "debian"})
    def test_accepts_debian(self, _mock_read):
        self.assertEqual(detect_os(), "Debian")

    @patch("lib.remote_utils.read_os_release", return_value={"ID": "ubuntu"})
    def test_accepts_ubuntu_as_best_effort(self, _mock_read):
        self.assertIn("Ubuntu", detect_os())

    @patch("lib.remote_utils.read_os_release", return_value={"ID": "linuxmint"})
    def test_accepts_linux_mint_as_best_effort(self, _mock_read):
        self.assertIn("Linux Mint", detect_os())

    @patch("lib.remote_utils.read_os_release", return_value={"ID": "fedora"})
    def test_rejects_other_distributions(self, _mock_read):
        with self.assertRaises(SystemExit):
            detect_os()


class TestGeneratePassword(unittest.TestCase):
    def test_default_length(self):
        pwd = generate_password()
        self.assertEqual(len(pwd), 16)

    def test_custom_length(self):
        pwd = generate_password(32)
        self.assertEqual(len(pwd), 32)

    def test_uniqueness(self):
        passwords = {generate_password() for _ in range(10)}
        self.assertEqual(len(passwords), 10)

    def test_uses_allowed_characters(self):
        pwd = generate_password(100)
        allowed = set(string.ascii_letters + string.digits + "!@#$%^&*")
        for c in pwd:
            self.assertIn(c, allowed)


class TestFileContains(unittest.TestCase):
    def test_file_contains_string(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("hello world\nfoo bar\n")
            path = f.name
        try:
            self.assertTrue(file_contains(path, 'hello'))
            self.assertTrue(file_contains(path, 'foo bar'))
            self.assertFalse(file_contains(path, 'missing'))
        finally:
            os.unlink(path)


    def test_file_not_found(self):
        self.assertFalse(file_contains('/nonexistent/file/xyz', 'content'))

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("")
            path = f.name
        try:
            self.assertFalse(file_contains(path, 'anything'))
        finally:
            os.unlink(path)


class TestUserHome(unittest.TestCase):
    @patch("lib.remote_utils.pwd.getpwnam")
    def test_returns_home_recorded_for_account(self, mock_getpwnam):
        mock_getpwnam.return_value = SimpleNamespace(pw_dir="/srv/users/agent")

        self.assertEqual(get_user_home("agent"), "/srv/users/agent")

    @patch("lib.remote_utils.pwd.getpwnam", side_effect=KeyError("agent"))
    def test_rejects_missing_account(self, _mock_getpwnam):
        with self.assertRaisesRegex(RuntimeError, "Target user does not exist"):
            get_user_home("agent")


if __name__ == '__main__':
    unittest.main()
