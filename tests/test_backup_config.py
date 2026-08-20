"""Tests for generic backup declarations and storage-operation composition."""

from __future__ import annotations

import argparse
import unittest

from lib.arg_parser import add_setup_arguments
from lib.config import SetupConfig
from lib.runtime_config import RuntimeConfig
from lib.task_utils import get_all_storage_paths
from lib.validation import validate_backup_specs


class BackupConfigTest(unittest.TestCase):
    def test_backup_flag_round_trips_through_setup_command(self) -> None:
        config = SetupConfig(
            host="target",
            username="agent",
            system_type="server_dev",
            backup_specs=[["/srv/workspace", "/srv/backups/workspace", "daily"]],
        )
        command = " ".join(config.to_setup_command())
        self.assertIn("--backup /srv/workspace /srv/backups/workspace daily", command)
        validate_backup_specs(config.backup_specs)

    def test_runtime_keeps_backup_jobs_separate_but_executes_them_with_sync(self) -> None:
        runtime = RuntimeConfig(
            username="agent",
            sync_specs=[["/srv/git", "/srv/backups/git", "weekly"]],
            scrub_specs=[],
            notify_specs=[],
            backup_specs=[["/srv/workspace", "/srv/backups/workspace", "daily"]],
        )
        self.assertEqual(len(runtime.all_sync_specs()), 2)
        self.assertTrue(runtime.has_storage_ops())
        self.assertEqual(
            get_all_storage_paths(runtime),
            ["/srv/backups/git", "/srv/backups/workspace", "/srv/git", "/srv/workspace"],
        )

    def test_setup_parser_accepts_repeatable_backup_jobs(self) -> None:
        parser = argparse.ArgumentParser()
        add_setup_arguments(parser, include_system_type=True)
        args = parser.parse_args(
            [
                "server_dev",
                "target",
                "agent",
                "--backup",
                "/srv/a",
                "/srv/b",
                "daily",
                "--backup",
                "/srv/c",
                "/srv/d",
                "weekly",
            ]
        )
        self.assertEqual(
            args.backup_specs,
            [["/srv/a", "/srv/b", "daily"], ["/srv/c", "/srv/d", "weekly"]],
        )


if __name__ == "__main__":
    unittest.main()
