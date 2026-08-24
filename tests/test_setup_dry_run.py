"""Dry-run isolation tests for the setup transport boundary."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from lib.config import SetupConfig
from lib import setup_common


def _config(host: str, **kwargs: object) -> SetupConfig:
    values: dict[str, object] = {
        "host": host,
        "username": "admin",
        "system_type": "server_web",
        "dry_run": True,
    }
    values.update(kwargs)
    return SetupConfig(**values)


class TestSetupDryRunIsolation(unittest.TestCase):
    def test_remote_dry_run_does_not_probe_sudo_over_ssh(self) -> None:
        config = _config(
            "192.168.1.50",
            hosted_node="pve1",
            machine_type="vm",
            ssh_key="/keys/id_ed25519",
        )
        with (
            patch.object(setup_common, "copy_project_files"),
            patch.object(setup_common, "ensure_remote_sudo") as ensure_sudo,
        ):
            result = setup_common.run_remote_setup(config)

        self.assertEqual(result, 0)
        ensure_sudo.assert_not_called()

    def test_local_dry_run_does_not_require_root(self) -> None:
        config = _config("localhost")
        with (
            patch.object(setup_common.os, "geteuid", return_value=1000),
            patch.object(setup_common, "copy_project_files"),
        ):
            result = setup_common.run_remote_setup(config)

        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
