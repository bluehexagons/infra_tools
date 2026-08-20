"""Tests for the provider-neutral VM command surface."""

from __future__ import annotations

import argparse
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from lib.proxmox_backup import BackupInfo
from lib.proxmox_hosts import ProxmoxHost, add_proxmox_host
from lib.proxmox_manage import ContainerInfo, HealthReport, SnapshotInfo
from lib.vm_cli import add_vm_subparser, run_vm_command


class VMCLITest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = self.temp_dir.name
        add_proxmox_host(
            ProxmoxHost(name="pve1", address="10.0.0.10"), self.workspace
        )
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        add_vm_subparser(subparsers)
        self.parser = parser

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _run(self, *argv: str) -> tuple[int, str]:
        args = self.parser.parse_args(["vm", "--workspace", self.workspace, *argv])
        output = io.StringIO()
        with redirect_stdout(output):
            result = run_vm_command(args)
        return result, output.getvalue()

    @patch("lib.vm_cli.list_containers")
    def test_list_uses_neutral_json_envelope(self, mock_list) -> None:
        mock_list.return_value = [
            ContainerInfo(vmid=100, status="running", name="web", guest_type="lxc"),
            ContainerInfo(vmid=101, status="stopped", name="build", guest_type="vm"),
        ]
        result, output = self._run("list", "pve1", "--json")
        self.assertEqual(result, 0)
        payload = json.loads(output)
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["provider"], "proxmox")
        self.assertEqual(payload["operation"], "list")
        self.assertEqual(payload["resources"][1]["kind"], "vm")

    @patch("lib.vm_cli.get_container_config", return_value={"cores": "2"})
    @patch("lib.vm_cli.get_container_status", return_value="running")
    @patch("lib.vm_cli.list_containers")
    def test_show_includes_provider_config(
        self, mock_list, _mock_status, _mock_config
    ) -> None:
        mock_list.return_value = [
            ContainerInfo(vmid=100, status="running", name="web", guest_type="lxc")
        ]
        result, output = self._run("show", "pve1", "100", "--json")
        self.assertEqual(result, 0)
        payload = json.loads(output)
        self.assertEqual(payload["resources"][0]["config"], {"cores": "2"})

    @patch("lib.vm_cli.health_check")
    def test_unhealthy_health_check_returns_failure(self, mock_health) -> None:
        mock_health.return_value = HealthReport(
            vmid=100,
            status="stopped",
            guest_type="lxc",
            notes=["Guest is not running (status=stopped)"],
        )
        result, output = self._run("health", "pve1", "100", "--json")
        self.assertEqual(result, 1)
        self.assertFalse(json.loads(output)["resources"][0]["healthy"])

    @patch("lib.vm_cli.list_snapshots")
    def test_snapshot_list(self, mock_snapshots) -> None:
        mock_snapshots.return_value = [SnapshotInfo("before", "initial")]
        result, output = self._run("snapshot", "list", "pve1", "100", "--json")
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output)["resources"][0]["name"], "before")

    @patch("lib.vm_cli.list_backups")
    def test_backup_list(self, mock_backups) -> None:
        mock_backups.return_value = [
            BackupInfo("local:backup/vzdump-qemu-100.vma.zst", 100, 123)
        ]
        result, output = self._run("backup", "list", "pve1", "100", "--json")
        self.assertEqual(result, 0)
        self.assertEqual(
            json.loads(output)["resources"][0]["storage"],
            "local",
        )

    def test_invalid_id_is_rejected_by_argparse(self) -> None:
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["vm", "show", "pve1", "0"])


if __name__ == "__main__":
    unittest.main()
