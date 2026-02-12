"""Tests for lib/remote_utils.py: dry-run mode, validation, password generation, file_contains."""

from __future__ import annotations

import os
import string
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.remote_utils import (
    set_dry_run,
    is_dry_run,
    validate_username,
    generate_password,
    run,
    file_contains,
)


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


class TestRemoteValidateUsername(unittest.TestCase):
    def test_valid(self):
        self.assertTrue(validate_username('admin'))

    def test_invalid(self):
        self.assertFalse(validate_username('Admin'))


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


if __name__ == '__main__':
    unittest.main()
