"""Tests for remote_setup.py argument-file handling."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import remote_setup


class TestRemoteSetupArgsFile(unittest.TestCase):
    def test_resolve_cli_args_loads_and_removes_args_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            args_path = os.path.join(tmpdir, "args.json")
            with open(args_path, "w", encoding="utf-8") as file_obj:
                file_obj.write('["--system-type", "server_lite", "--credential", "mediauser", "supersecret"]\n')

            resolved = remote_setup._resolve_cli_args(["--args-file", args_path, "--dry-run"])

            self.assertEqual(
                resolved,
                ["--system-type", "server_lite", "--credential", "mediauser", "supersecret", "--dry-run"],
            )
            self.assertFalse(os.path.exists(args_path))

    def test_load_args_file_rejects_non_list_payload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            args_path = os.path.join(tmpdir, "args.json")
            with open(args_path, "w", encoding="utf-8") as file_obj:
                file_obj.write('{"bad": "payload"}\n')

            with self.assertRaisesRegex(ValueError, "JSON list"):
                remote_setup._load_args_file(args_path)


if __name__ == "__main__":
    unittest.main()
