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

    def test_repository_lookup_normalizes_output_and_honors_https(self) -> None:
        repository = {
            "nameWithOwner": "bluehexagons/infra_tools",
            "sshUrl": "git@github.com:bluehexagons/infra_tools.git",
            "url": "https://github.com/bluehexagons/infra_tools",
        }
        responses = [
            SimpleNamespace(
                returncode=0,
                stdout=json.dumps(repository, indent=2) + "\n",
                stderr="",
            ),
            SimpleNamespace(returncode=0, stdout="https\n", stderr=""),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            binary = self._binary(temporary)
            with (
                patch.object(
                    t3code_gh_shim.subprocess,
                    "run",
                    side_effect=responses,
                ) as run_command,
                redirect_stdout(io.StringIO()) as stdout,
                redirect_stderr(io.StringIO()) as stderr,
            ):
                result = t3code_gh_shim.run(
                    binary,
                    [
                        "repo",
                        "view",
                        "bluehexagons/infra_tools",
                        "--json",
                        "nameWithOwner,url,sshUrl",
                    ],
                )

        self.assertEqual(result, 0)
        self.assertEqual(stderr.getvalue(), "")
        normalized = json.loads(stdout.getvalue())
        self.assertEqual(normalized["nameWithOwner"], "bluehexagons/infra_tools")
        self.assertEqual(
            normalized["sshUrl"],
            "https://github.com/bluehexagons/infra_tools",
        )
        self.assertEqual(
            run_command.call_args_list[1].args[0],
            [binary, "config", "get", "git_protocol", "--host", "github.com"],
        )

    def test_repository_lookup_falls_back_to_safe_canonical_urls(self) -> None:
        responses = [
            SimpleNamespace(returncode=1, stdout="", stderr="lookup failed\n"),
            SimpleNamespace(returncode=0, stdout="ssh\n", stderr=""),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            binary = self._binary(temporary)
            with (
                patch.object(
                    t3code_gh_shim.subprocess,
                    "run",
                    side_effect=responses,
                ),
                redirect_stdout(io.StringIO()) as stdout,
                redirect_stderr(io.StringIO()) as stderr,
            ):
                result = t3code_gh_shim.run(
                    binary,
                    [
                        "repo",
                        "view",
                        "bluehexagons/beast_cards",
                        "--json",
                        "nameWithOwner,url,sshUrl",
                    ],
                )

        self.assertEqual(result, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {
                "nameWithOwner": "bluehexagons/beast_cards",
                "url": "https://github.com/bluehexagons/beast_cards",
                "sshUrl": "git@github.com:bluehexagons/beast_cards.git",
            },
        )

    def test_repository_lookup_preserves_failure_for_unsafe_name(self) -> None:
        response = SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="invalid repository\n",
        )
        with tempfile.TemporaryDirectory() as temporary:
            binary = self._binary(temporary)
            with (
                patch.object(
                    t3code_gh_shim.subprocess,
                    "run",
                    return_value=response,
                ),
                redirect_stdout(io.StringIO()) as stdout,
                redirect_stderr(io.StringIO()) as stderr,
            ):
                result = t3code_gh_shim.run(
                    binary,
                    [
                        "repo",
                        "view",
                        "../unsafe",
                        "--json",
                        "nameWithOwner,url,sshUrl",
                    ],
                )

        self.assertEqual(result, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "invalid repository\n")

    def test_discovery_resolves_login_for_authenticated_token_only_entry(self) -> None:
        payload = {
            "hosts": {
                "github.com": [
                    {
                        "active": True,
                        "error": None,
                        "host": "github.com",
                        "login": "",
                        "state": "success",
                    }
                ]
            }
        }
        with tempfile.TemporaryDirectory() as temporary:
            binary = self._binary(temporary)
            responses = [
                SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps(payload) + "\n",
                    stderr="",
                ),
                SimpleNamespace(
                    returncode=0,
                    stdout="bluehexagons\n",
                    stderr="",
                ),
            ]
            with (
                patch.object(
                    t3code_gh_shim.subprocess,
                    "run",
                    side_effect=responses,
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
        self.assertEqual(account["login"], "bluehexagons")
        self.assertNotIn("error", account)
        self.assertEqual(
            run_command.call_args_list[1].args[0],
            [
                binary,
                "api",
                "user",
                "--hostname",
                "github.com",
                "--jq",
                ".login",
            ],
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
