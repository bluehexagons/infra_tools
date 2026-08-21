"""Tests for the T3-scoped GitHub CLI discovery compatibility shim."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from common.service_tools import t3code_gh_shim


class T3CodeGitHubShimTest(unittest.TestCase):
    def _binary(self, directory: str) -> str:
        path = os.path.join(directory, "gh")
        with open(path, "w", encoding="utf-8") as file_obj:
            file_obj.write("#!/bin/sh\nexit 0\n")
        os.chmod(path, 0o755)
        return path

    def test_discovery_removes_only_null_error_fields(self) -> None:
        payload = {
            "hosts": {
                "github.com": [
                    {
                        "active": True,
                        "error": None,
                        "host": "github.com",
                        "login": "agent",
                        "state": "success",
                    }
                ]
            }
        }
        with tempfile.TemporaryDirectory() as temporary:
            binary = self._binary(temporary)
            with (
                patch.object(
                    t3code_gh_shim.subprocess,
                    "run",
                    return_value=SimpleNamespace(
                        returncode=0,
                        stdout=json.dumps(payload) + "\n",
                        stderr="",
                    ),
                ) as run_command,
                redirect_stdout(io.StringIO()) as stdout,
                redirect_stderr(io.StringIO()),
            ):
                result = t3code_gh_shim.run(
                    binary,
                    ["auth", "status", "--json", "hosts"],
                )

        self.assertEqual(result, 0)
        account = json.loads(stdout.getvalue())["hosts"]["github.com"][0]
        self.assertNotIn("error", account)
        self.assertEqual(account["state"], "success")
        run_command.assert_called_once_with(
            [binary, "auth", "status", "--json", "hosts"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_non_discovery_commands_exec_the_real_binary_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            binary = self._binary(temporary)
            with patch.object(t3code_gh_shim.os, "execv") as exec_command:
                with self.assertRaisesRegex(RuntimeError, "unexpectedly returned"):
                    t3code_gh_shim.run(binary, ["pr", "list", "--limit", "10"])

        exec_command.assert_called_once_with(
            binary,
            [binary, "pr", "list", "--limit", "10"],
        )

    def test_cli_preserves_leading_github_options(self) -> None:
        with patch.object(
            t3code_gh_shim.sys,
            "argv",
            ["t3code_gh_shim.py", "--gh-binary", "/usr/bin/gh", "--version"],
        ), patch.object(t3code_gh_shim, "run", return_value=0) as run_command:
            result = t3code_gh_shim.main()

        self.assertEqual(result, 0)
        run_command.assert_called_once_with("/usr/bin/gh", ["--version"])

    def test_malformed_discovery_output_is_preserved(self) -> None:
        self.assertEqual(
            t3code_gh_shim._sanitize_discovery_output("not-json\n"),
            "not-json\n",
        )


if __name__ == "__main__":
    unittest.main()
