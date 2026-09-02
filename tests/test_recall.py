"""Tests for remote configuration recall and reconstruction."""

from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import MagicMock, patch

from lib import recall
from lib.config import SetupConfig


def completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["ssh"], returncode, stdout, stderr)


class TestRetrieveStoredConfig(unittest.TestCase):
    def test_retrieves_and_decodes_stored_config(self) -> None:
        stored = {"username": "remote", "friendly_name": "production", "tags": "web,prod"}
        with patch.object(recall, "build_ssh_command", return_value=["ssh"]), patch.object(recall.subprocess, "run", return_value=completed(stdout=json.dumps(stored))) as run:
            config = recall.retrieve_stored_config("server", "remote", "/tmp/key")

        self.assertIsNotNone(config)
        self.assertEqual(config.host, "server")
        self.assertEqual(config.username, "remote")
        self.assertEqual(config.tags, ["web", "prod"])
        self.assertEqual(run.call_args.kwargs["timeout"], 30)
        self.assertIn("cat /opt/infra_tools/state/setup.json", run.call_args.args[0][-1])

    def test_retrieve_returns_none_for_empty_or_invalid_remote_data(self) -> None:
        for result in (completed(stdout=""), completed(stdout="not json")):
            with self.subTest(stdout=result.stdout), patch.object(recall, "build_ssh_command", return_value=["ssh"]), patch.object(recall.subprocess, "run", return_value=result):
                self.assertIsNone(recall.retrieve_stored_config("server", "remote"))

    def test_retrieve_handles_timeout_and_missing_ssh(self) -> None:
        stderr = io.StringIO()
        with patch.object(recall, "build_ssh_command", return_value=["ssh"]), patch.object(recall.subprocess, "run", side_effect=subprocess.TimeoutExpired(["ssh"], 30)):
            with redirect_stderr(stderr):
                self.assertIsNone(recall.retrieve_stored_config("server", "remote"))
        self.assertIn("Timeout retrieving stored config", stderr.getvalue())

        stderr = io.StringIO()
        with patch.object(recall, "build_ssh_command", return_value=["ssh"]), patch.object(recall.subprocess, "run", side_effect=FileNotFoundError):
            with redirect_stderr(stderr):
                self.assertIsNone(recall.retrieve_stored_config("server", "remote"))
        self.assertIn("SSH command not available", stderr.getvalue())


class TestReconstructRemoteConfig(unittest.TestCase):
    def test_reconstructs_existing_remote_install_and_preserves_extras(self) -> None:
        reconstructed = {
            "install_go": True,
            "install_node": False,
            "deploy": [["example.com", "https://example.com/repo.git"]],
            "samba_shares": ["public"],
        }
        with patch.object(recall, "build_ssh_command", return_value=["ssh"]), patch.object(recall.subprocess, "run", side_effect=[completed(), completed(stdout=json.dumps(reconstructed))]) as run:
            result = recall.reconstruct_remote_config("server", "remote", "/tmp/key")

        self.assertIsNotNone(result)
        config, extras = result
        self.assertEqual(config.system_type, "server_web")
        self.assertTrue(config.install_go)
        self.assertEqual(extras, {"samba_shares": ["public"], "deploy": [["example.com", "https://example.com/repo.git"]]})
        self.assertEqual(run.call_count, 2)
        self.assertIn("test -f /opt/infra_tools/infra_tools.py", run.call_args_list[0].args[0][-1])
        self.assertIn("reconstruct --compact", run.call_args_list[1].args[0][-1])

    def test_reconstruct_installs_missing_remote_tool_from_temporary_archive(self) -> None:
        process = MagicMock()
        process.returncode = 0
        reconstructed = {"install_python": True}
        with tempfile.TemporaryDirectory() as temp_root, patch.object(recall.tempfile, "mkdtemp", return_value=os.path.join(temp_root, "build")), patch.object(recall, "copy_project_files") as copy_files, patch.object(recall, "create_tar_from_dir", return_value=b"tar data") as create_tar, patch.object(recall, "build_ssh_command", return_value=["ssh"]), patch.object(recall.subprocess, "run", side_effect=[completed(1), completed(stdout=json.dumps(reconstructed))]), patch.object(recall.subprocess, "Popen", return_value=process) as popen:
            os.mkdir(os.path.join(temp_root, "build"))
            result = recall.reconstruct_remote_config("server", "remote")

        self.assertIsNotNone(result)
        self.assertTrue(result[0].install_python)
        copy_files.assert_called_once_with(os.path.join(temp_root, "build"))
        create_tar.assert_called_once_with(os.path.join(temp_root, "build"))
        popen.assert_called_once()
        process.communicate.assert_called_once_with(input=b"tar data", timeout=60)
        self.assertFalse(os.path.exists(os.path.join(temp_root, "build")))

    def test_reconstruct_returns_none_when_remote_install_fails(self) -> None:
        process = MagicMock()
        process.returncode = 1
        with tempfile.TemporaryDirectory() as temp_root, patch.object(recall.tempfile, "mkdtemp", return_value=os.path.join(temp_root, "build")), patch.object(recall, "copy_project_files"), patch.object(recall, "create_tar_from_dir", return_value=b"tar data"), patch.object(recall, "build_ssh_command", return_value=["ssh"]), patch.object(recall.subprocess, "run", return_value=completed(1)), patch.object(recall.subprocess, "Popen", return_value=process):
            os.mkdir(os.path.join(temp_root, "build"))
            self.assertIsNone(recall.reconstruct_remote_config("server", "remote"))


class TestRecallCommand(unittest.TestCase):
    def test_recall_uses_stored_configuration_without_reconstruction(self) -> None:
        config = SetupConfig(host="server", username="remote", system_type="server_dev")
        stdout = io.StringIO()
        with patch.object(recall, "retrieve_stored_config", return_value=config) as retrieve, patch.object(recall, "reconstruct_remote_config") as reconstruct:
            with redirect_stdout(stdout):
                result = recall.run_recall_command("server", "remote", None)

        self.assertEqual(result, 0)
        retrieve.assert_called_once_with("server", "remote", None)
        reconstruct.assert_not_called()
        self.assertIn("Stored configuration file", stdout.getvalue())
        self.assertIn("infra-tools setup server_dev", stdout.getvalue())
        self.assertIn("  remote", stdout.getvalue())

    def test_recall_reports_reconstruction_failure(self) -> None:
        stderr = io.StringIO()
        with patch.object(recall, "retrieve_stored_config", return_value=None), patch.object(recall, "reconstruct_remote_config", return_value=None), redirect_stderr(stderr):
            result = recall.run_recall_command("server", "remote", None)
        self.assertEqual(result, 1)
        self.assertIn("Failed to retrieve or reconstruct", stderr.getvalue())

    def test_recall_prints_reconstructed_feature_notes(self) -> None:
        config = SetupConfig(host="server", username="remote", system_type="server_web")
        extras = {
            "samba_shares": ["public"],
            "deploy": [["example.com", "repo"]],
            "sync": [["/a", "/b"]],
            "scrub": [["/data", "/db"]],
            "mount_smb": ["//nas/share /mnt/share"],
        }
        stdout = io.StringIO()
        with patch.object(recall, "retrieve_stored_config", return_value=None), patch.object(recall, "reconstruct_remote_config", return_value=(config, extras)), patch.object(recall.os, "getenv", return_value="other-user"):
            with redirect_stdout(stdout):
                result = recall.run_recall_command("server", "remote", None)

        self.assertEqual(result, 0)
        output = stdout.getvalue()
        self.assertIn("Detected 1 Samba share(s)", output)
        self.assertIn("Detected 1 deployment(s)", output)
        self.assertIn("Detected 1 sync operation(s)", output)
        self.assertIn("Detected 1 scrub operation(s)", output)
        self.assertIn("Detected 1 SMB mount(s)", output)
        self.assertIn("  remote", output)


if __name__ == "__main__":
    unittest.main()
