"""Tests for the standalone agent credential pull utility."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import agent_auth_pull


class AgentAuthPullTests(unittest.TestCase):
    def test_parser_requires_an_explicit_output_directory(self) -> None:
        parser = agent_auth_pull.create_parser()
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["vm.example", "agent"])

    def test_ssh_command_uses_only_validated_fixed_remote_path(self) -> None:
        command = agent_auth_pull._ssh_command(
            "vm.example", "agent", 2222, "/tmp/id", ".codex/auth.json"
        )
        self.assertEqual(command[:7], ["ssh", "-T", "-p", "2222", "-i", "/tmp/id", "--"])
        self.assertEqual(command[7], "agent@vm.example")
        self.assertIn(".codex/auth.json", command[8])

    def test_remote_reader_accepts_a_private_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            credential_dir = home / ".codex"
            credential_dir.mkdir(mode=0o700)
            credential = credential_dir / "auth.json"
            credential.write_bytes(b'{"fixture": true}\n')
            credential.chmod(0o600)
            result = subprocess.run(
                [
                    "python3",
                    "-c",
                    agent_auth_pull._REMOTE_READ_SCRIPT,
                    ".codex/auth.json",
                    str(agent_auth_pull.MAX_CREDENTIAL_BYTES),
                ],
                check=False,
                capture_output=True,
                env={**os.environ, "HOME": directory},
            )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b'{"fixture": true}\n')

    def test_remote_reader_rejects_a_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            credential_dir = home / ".codex"
            credential_dir.mkdir(mode=0o700)
            source = home / "source.json"
            source.write_bytes(b'{"fixture": true}\n')
            (credential_dir / "auth.json").symlink_to(source)
            result = subprocess.run(
                [
                    "python3",
                    "-c",
                    agent_auth_pull._REMOTE_READ_SCRIPT,
                    ".codex/auth.json",
                    str(agent_auth_pull.MAX_CREDENTIAL_BYTES),
                ],
                check=False,
                capture_output=True,
                env={**os.environ, "HOME": directory},
            )
        self.assertEqual(result.returncode, 4)
        self.assertIn(b"symbolic link", result.stderr)

    def test_pull_writes_private_files_and_skips_absent_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "credentials"

            def read_remote(_host, _username, _port, _key, path):
                if path == ".codex/auth.json":
                    return b'{"fixture": true}\n'
                return None

            with (
                redirect_stdout(io.StringIO()),
                patch.object(agent_auth_pull.shutil, "which", return_value="/usr/bin/ssh"),
                patch.object(agent_auth_pull, "_read_remote_credential", side_effect=read_remote),
            ):
                result = agent_auth_pull.pull_credentials(
                    host="vm.example",
                    username="agent",
                    output_dir=str(output),
                )

            self.assertEqual(result, 0)
            destination = output / "codex-auth.json"
            self.assertEqual(destination.read_bytes(), b'{"fixture": true}\n')
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)

    def test_remote_timeout_has_a_bounded_error(self) -> None:
        with patch.object(
            agent_auth_pull.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["ssh"], 60),
        ):
            with self.assertRaisesRegex(RuntimeError, "transfer timed out"):
                agent_auth_pull._read_remote_credential(
                    "vm.example", "agent", 22, None, ".codex/auth.json"
                )

    def test_explicit_missing_credential_fails(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
            patch.object(agent_auth_pull.shutil, "which", return_value="/usr/bin/ssh"),
            patch.object(agent_auth_pull, "_read_remote_credential", return_value=None),
        ):
            result = agent_auth_pull.pull_credentials(
                host="vm.example",
                username="agent",
                output_dir=os.path.join(directory, "credentials"),
                tools=["codex"],
            )
        self.assertEqual(result, 1)

    def test_existing_destination_requires_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "credentials"
            output.mkdir(mode=0o700)
            destination = output / "codex-auth.json"
            destination.write_bytes(b"old")
            destination.chmod(0o600)
            with (
                redirect_stdout(io.StringIO()),
                redirect_stderr(io.StringIO()),
                patch.object(agent_auth_pull.shutil, "which", return_value="/usr/bin/ssh"),
                patch.object(agent_auth_pull, "_read_remote_credential", return_value=b"new"),
            ):
                result = agent_auth_pull.pull_credentials(
                    host="vm.example",
                    username="agent",
                    output_dir=str(output),
                    tools=["codex"],
                )
                overwritten = agent_auth_pull.pull_credentials(
                    host="vm.example",
                    username="agent",
                    output_dir=str(output),
                    tools=["codex"],
                    overwrite=True,
                )
            self.assertEqual(result, 1)
            self.assertEqual(overwritten, 0)
            self.assertEqual(destination.read_bytes(), b"new")

    def test_rejects_unsafe_identity_and_output_directory(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid SSH host"):
            agent_auth_pull._validate_connection("bad host", "agent", 22)
        with self.assertRaisesRegex(ValueError, "invalid SSH username"):
            agent_auth_pull._validate_connection("vm.example", "Bad User", 22)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "credentials"
            output.mkdir(mode=0o755)
            with self.assertRaisesRegex(ValueError, "must not be accessible"):
                agent_auth_pull._private_output_directory(str(output))


if __name__ == "__main__":
    unittest.main()
