"""Tests for read-only Proxmox maintenance preflight reporting."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.proxmox_hosts import ProxmoxHost
from lib.proxmox_maintenance import (
    ProxmoxMaintenanceReport,
    collect_maintenance_report,
    format_maintenance_report,
)


def _result(
    stdout: str = "",
    returncode: int = 0,
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def _active_services() -> str:
    return "active\nactive\nactive\nactive\nactive\n"


class TestCollectMaintenanceReport(unittest.TestCase):
    def setUp(self) -> None:
        self.host = ProxmoxHost(name="pve1", address="10.0.0.10")

    @patch("lib.proxmox_maintenance._run")
    def test_collects_healthy_standalone_node(self, mock_run) -> None:
        mock_run.side_effect = [
            _result("pve1\n"),
            _result(_active_services()),
            _result(returncode=1),
            _result("[]\n"),
            _result("VMID Status Name\n"),
            _result("VMID NAME STATUS\n"),
            _result("Name Type Status Total Used Available %\nlocal dir active 1 1 1 1%\n"),
            _result("5000000\n"),
            _result(returncode=1),
        ]

        report = collect_maintenance_report(self.host)

        self.assertTrue(report.healthy)
        self.assertTrue(report.reboot_safe)
        self.assertFalse(report.clustered)
        self.assertEqual(report.storage_states, {"local": "active"})
        self.assertFalse(report.reboot_required)

    @patch("lib.proxmox_maintenance._run")
    def test_reports_cluster_quorum_and_running_guests(self, mock_run) -> None:
        mock_run.side_effect = [
            _result("pve1\n"),
            _result(_active_services()),
            _result(),
            _result("Cluster information\nQuorate: Yes\n"),
            _result("[]\n"),
            _result("VMID Status Name\n100 running web\n"),
            _result("VMID NAME STATUS\n200 db stopped\n"),
            _result("Name Type Status\nlocal dir active\n"),
            _result("5000000\n"),
            _result(),
        ]

        report = collect_maintenance_report(self.host)

        self.assertTrue(report.healthy)
        self.assertTrue(report.clustered)
        self.assertTrue(report.quorate)
        self.assertFalse(report.reboot_safe)
        self.assertEqual([guest.vmid for guest in report.running_guests], [100])
        self.assertTrue(report.reboot_required)

    @patch("lib.proxmox_maintenance._run")
    def test_fails_for_active_tasks_locks_storage_and_low_space(self, mock_run) -> None:
        tasks = json.dumps([{"type": "vzdump", "id": "100", "user": "root@pam"}])
        mock_run.side_effect = [
            _result("pve1\n"),
            _result("active\nactive\nfailed\nactive\nactive\n", returncode=3),
            _result(returncode=1),
            _result(tasks),
            _result("VMID Status Lock Name\n100 running backup web\n"),
            _result("VMID NAME STATUS\n"),
            _result("Name Type Status\nbackup nfs inactive\n"),
            _result("1000\n"),
            _result(returncode=1),
        ]

        report = collect_maintenance_report(self.host)

        self.assertFalse(report.healthy)
        self.assertFalse(report.reboot_safe)
        self.assertIn("vzdump:100 (root@pam)", report.active_tasks)
        self.assertTrue(any("pveproxy" in error for error in report.errors))
        self.assertTrue(any("locked guest" in error for error in report.errors))
        self.assertTrue(any("Storage backup" in error for error in report.errors))
        self.assertTrue(any("less than 4 GiB" in error for error in report.errors))

    @patch("lib.proxmox_maintenance._run")
    def test_ssh_failure_stops_further_probes(self, mock_run) -> None:
        mock_run.return_value = _result(returncode=255, stderr="connection refused")

        report = collect_maintenance_report(self.host)

        self.assertFalse(report.healthy)
        self.assertIn("connection refused", report.errors[0])
        mock_run.assert_called_once()


class TestFormatMaintenanceReport(unittest.TestCase):
    def test_formats_operator_summary(self) -> None:
        report = ProxmoxMaintenanceReport(
            host_name="pve1",
            address="10.0.0.10",
            node_name="pve1",
            clustered=False,
            root_free_bytes=8 * 1024 ** 3,
            reboot_required=False,
        )

        output = format_maintenance_report(report)

        self.assertIn("HEALTHY", output)
        self.assertIn("READY", output)
        self.assertIn("standalone", output)
        self.assertIn("8.0 GiB", output)


if __name__ == "__main__":
    unittest.main()
