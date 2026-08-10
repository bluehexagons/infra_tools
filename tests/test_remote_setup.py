"""Tests for remote_setup.py argument-file handling."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, mock_open, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import remote_setup
from lib.config import SetupConfig
from lib.remote_utils import set_dry_run


class TestRemoteSetupArgsFile(unittest.TestCase):
    def test_dry_run_prints_plan_without_invoking_setup_steps(self):
        self.addCleanup(lambda: set_dry_run(False))
        args = SimpleNamespace(
            deploy_latest=False,
            dry_run=True,
            custom_steps=None,
            system_type="server_lite",
        )
        config = SetupConfig(
            host="localhost",
            username="root",
            system_type="server_lite",
            dry_run=True,
        )
        step = MagicMock()

        with patch.object(
            remote_setup, "create_setup_argument_parser"
        ) as create_parser, patch.object(
            remote_setup, "config_from_remote_args", return_value=config
        ), patch.object(
            remote_setup, "detect_os", return_value="Debian"
        ), patch.object(
            remote_setup, "print_setup_summary"
        ), patch.object(
            remote_setup, "cleanup_all_infra_services"
        ) as cleanup, patch.object(
            remote_setup,
            "get_steps_for_system_type",
            return_value=[("Mutating step", step)],
        ):
            create_parser.return_value.parse_args.return_value = args
            self.assertEqual(remote_setup._run_main(), 0)

        step.assert_not_called()
        cleanup.assert_called_once_with(dry_run=True)

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

    def test_remote_config_resolves_auto_machine_type(self):
        args = SimpleNamespace(custom_steps=None, system_type='server_lite')
        config = SetupConfig(
            host='localhost',
            username='root',
            system_type='server_lite',
            machine_type='auto',
        )
        with patch.object(remote_setup.SetupConfig, 'from_args', return_value=config), \
             patch.object(remote_setup, 'resolve_machine_type', return_value='unprivileged') as resolve:
            resolved = remote_setup.config_from_remote_args(args)

        self.assertIs(resolved, config)
        self.assertEqual(config.machine_type, 'unprivileged')
        resolve.assert_called_once_with('auto')

    def test_remote_config_validates_samba_share_paths(self):
        args = SimpleNamespace(custom_steps=None, system_type='server_lite')
        config = SetupConfig(
            host='localhost',
            username='root',
            system_type='server_lite',
            samba_shares=[['read', 'docs', '/srv/docs,/srv/media', 'shareuser:secret']],
        )
        with patch.object(remote_setup.SetupConfig, 'from_args', return_value=config), \
             patch.object(remote_setup, 'resolve_machine_type', return_value='hardware'):
            with self.assertRaisesRegex(ValueError, 'exactly one path'):
                remote_setup.config_from_remote_args(args)

    def test_load_args_file_rejects_non_list_payload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            args_path = os.path.join(tmpdir, "args.json")
            with open(args_path, "w", encoding="utf-8") as file_obj:
                file_obj.write('{"bad": "payload"}\n')

            with self.assertRaisesRegex(ValueError, "JSON list"):
                remote_setup._load_args_file(args_path)


class TestRepositorySourcePath(unittest.TestCase):
    def test_default_mode_uses_uploaded_repository_without_remote_clone(self):
        git_url = "git@github.com:owner/private-repo.git"
        repo_path = "/opt/infra_tools/deployments/private-repo"

        def exists(path: str) -> bool:
            return path == repo_path

        with patch.object(remote_setup.os.path, "exists", side_effect=exists):
            result = remote_setup.get_repository_source_path(git_url, "default")

        self.assertEqual(result, (repo_path, ""))

    def test_full_mode_uses_uploaded_repository_commit(self):
        git_url = "https://github.com/owner/app.git"
        repo_path = "/opt/infra_tools/deployments/app"
        commit_path = f"{repo_path}.commit"

        def exists(path: str) -> bool:
            return path in {repo_path, commit_path}

        with patch.object(remote_setup.os.path, "exists", side_effect=exists), \
             patch("builtins.open", mock_open(read_data="abc123\n")):
            result = remote_setup.get_repository_source_path(git_url, "full")

        self.assertEqual(result, (repo_path, "abc123"))

    def test_missing_uploaded_repository_skips_without_clone(self):
        with patch.object(remote_setup.os.path, "exists", return_value=False):
            result = remote_setup.get_repository_source_path(
                "https://github.com/owner/app.git",
                "default",
            )

        self.assertIsNone(result)


class TestAgentPayloadCleanup(unittest.TestCase):
    def test_main_removes_agent_payload_after_setup_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            payload_dir = os.path.join(directory, "agent_payload")
            os.makedirs(payload_dir)
            with patch.object(remote_setup, "REMOTE_AGENT_PAYLOAD_DIR", payload_dir), \
                 patch.object(remote_setup, "_run_main", side_effect=RuntimeError("failed")):
                with self.assertRaisesRegex(RuntimeError, "failed"):
                    remote_setup.main()

            self.assertFalse(os.path.exists(payload_dir))


if __name__ == "__main__":
    unittest.main()
