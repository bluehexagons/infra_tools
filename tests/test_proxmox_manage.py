"""Tests for lib/proxmox_manage.py: container CRUD and health checks (mocked)."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from typing import Optional
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.proxmox_hosts import ProxmoxHost
from lib.proxmox_manage import (
    ContainerInfo,
    HealthReport,
    ProxmoxManageError,
    _parse_pct_list,
    destroy_container,
    get_container_ip,
    get_container_status,
    health_check,
    list_containers,
    start_container,
    stop_container,
)


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["ssh"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _host(**overrides) -> ProxmoxHost:
    base = {"name": "pve1", "address": "10.0.0.10", "user": "root"}
    base.update(overrides)
    return ProxmoxHost(**base)


class TestParsePctList(unittest.TestCase):
    def test_parses_standard_header(self) -> None:
        out = (
            "VMID       Status     Lock         Name\n"
            "100        running                 web\n"
            "101        stopped    backup       db\n"
        )
        rows = _parse_pct_list(out)
        self.assertEqual(rows, [
            ContainerInfo(vmid=100, status="running", name="web", lock=None),
            ContainerInfo(vmid=101, status="stopped", name="db", lock="backup"),
        ])

    def test_handles_no_header(self) -> None:
        rows = _parse_pct_list("100 running web\n")
        self.assertEqual(rows, [
            ContainerInfo(vmid=100, status="running", name="web", lock=None)
        ])

    def test_skips_empty_and_invalid_lines(self) -> None:
        out = (
            "VMID       Status     Name\n"
            "\n"
            "notanumber stopped foo\n"
            "200 running api\n"
        )
        rows = _parse_pct_list(out)
        self.assertEqual([r.vmid for r in rows], [200])

    def test_handles_two_column_rows(self) -> None:
        rows = _parse_pct_list("VMID Status\n100 running\n")
        self.assertEqual(rows, [
            ContainerInfo(vmid=100, status="running", name="", lock=None)
        ])


class TestListContainers(unittest.TestCase):
    @patch("lib.proxmox_manage._ssh_run")
    def test_list_containers_sorts_by_vmid(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed(
            "VMID Status Name\n200 running b\n100 stopped a\n"
        )
        rows = list_containers(_host())
        self.assertEqual([r.vmid for r in rows], [100, 200])

    @patch("lib.proxmox_manage._ssh_run")
    def test_list_containers_raises_on_failure(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed(stderr="boom", returncode=1)
        with self.assertRaises(ProxmoxManageError):
            list_containers(_host())

    def test_list_containers_dry_run_returns_empty(self) -> None:
        with patch("lib.proxmox_manage._ssh_run") as mock_run:
            self.assertEqual(list_containers(_host(), dry_run=True), [])
            mock_run.assert_not_called()


class TestContainerIp(unittest.TestCase):
    @patch("lib.proxmox_manage._ssh_run")
    def test_extracts_ip_from_net0(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed(
            "arch: amd64\n"
            "net0: name=eth0,bridge=vmbr0,ip=10.0.0.50/24,gw=10.0.0.1,type=veth\n"
        )
        self.assertEqual(get_container_ip(_host(), 100), "10.0.0.50")

    @patch("lib.proxmox_manage._ssh_run")
    def test_returns_none_when_no_net0(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed("arch: amd64\n")
        self.assertIsNone(get_container_ip(_host(), 100))

    @patch("lib.proxmox_manage._ssh_run")
    def test_returns_none_on_command_failure(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed(returncode=2)
        self.assertIsNone(get_container_ip(_host(), 100))


class TestStatus(unittest.TestCase):
    @patch("lib.proxmox_manage._ssh_run")
    def test_returns_status_after_colon(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed("status: running\n")
        self.assertEqual(get_container_status(_host(), 100), "running")

    @patch("lib.proxmox_manage._ssh_run")
    def test_raises_on_failure(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed(stderr="not found", returncode=2)
        with self.assertRaises(ProxmoxManageError):
            get_container_status(_host(), 100)


class TestStartStop(unittest.TestCase):
    @patch("lib.proxmox_manage._ssh_run")
    def test_start_skips_when_already_running(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed("status: running\n")
        start_container(_host(), 100)
        # Only the status query, no pct start.
        self.assertEqual(mock_run.call_count, 1)
        self.assertIn("pct status", mock_run.call_args_list[0][0][3])

    @patch("lib.proxmox_manage._ssh_run")
    def test_start_runs_pct_start_when_stopped(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            _completed("status: stopped\n"),
            _completed(""),
        ]
        start_container(_host(), 100)
        self.assertEqual(mock_run.call_count, 2)
        self.assertIn("pct start 100", mock_run.call_args_list[1][0][3])

    @patch("lib.proxmox_manage._ssh_run")
    def test_start_raises_on_failure(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            _completed("status: stopped\n"),
            _completed(stderr="boom", returncode=1),
        ]
        with self.assertRaises(ProxmoxManageError):
            start_container(_host(), 100)

    @patch("lib.proxmox_manage._ssh_run")
    def test_stop_uses_shutdown_by_default(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            _completed("status: running\n"),
            _completed(""),
        ]
        stop_container(_host(), 100)
        self.assertIn("pct shutdown 100", mock_run.call_args_list[1][0][3])

    @patch("lib.proxmox_manage._ssh_run")
    def test_stop_force_uses_pct_stop(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            _completed("status: running\n"),
            _completed(""),
        ]
        stop_container(_host(), 100, force=True)
        self.assertIn("pct stop 100", mock_run.call_args_list[1][0][3])

    @patch("lib.proxmox_manage._ssh_run")
    def test_stop_skips_when_already_stopped(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed("status: stopped\n")
        stop_container(_host(), 100)
        self.assertEqual(mock_run.call_count, 1)


class TestDestroy(unittest.TestCase):
    @patch("lib.proxmox_manage._ssh_run")
    def test_destroy_stops_running_container_first(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            _completed("status: running\n"),  # initial status
            _completed("status: running\n"),  # status before stop
            _completed(""),                    # shutdown
            _completed(""),                    # destroy
        ]
        destroy_container(_host(), 100)
        executed = [call.args[3] for call in mock_run.call_args_list]
        self.assertIn("pct shutdown 100", executed)
        self.assertEqual(executed[-1], "pct destroy 100 --purge")

    @patch("lib.proxmox_manage._ssh_run")
    def test_destroy_no_purge_omits_flag(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            _completed("status: stopped\n"),
            _completed(""),
        ]
        destroy_container(_host(), 100, purge=False)
        self.assertEqual(mock_run.call_args_list[-1].args[3], "pct destroy 100")

    @patch("lib.proxmox_manage._ssh_run")
    def test_destroy_force_adds_force_flag(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            _completed("status: stopped\n"),
            _completed(""),
        ]
        destroy_container(_host(), 100, force=True)
        last = mock_run.call_args_list[-1].args[3]
        self.assertIn("--force", last)
        self.assertIn("--purge", last)

    @patch("lib.proxmox_manage._ssh_run")
    def test_destroy_raises_on_pct_failure(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            _completed("status: stopped\n"),
            _completed(stderr="locked", returncode=1),
        ]
        with self.assertRaises(ProxmoxManageError):
            destroy_container(_host(), 100)


class TestHealthCheck(unittest.TestCase):
    @patch("lib.proxmox_manage._ssh_run")
    def test_running_container_with_passing_probes_is_healthy(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            _completed("status: running\n"),
            _completed("net0: name=eth0,bridge=vmbr0,ip=10.0.0.50/24,gw=10.0.0.1\n"),
            _completed("OK\n"),
            _completed("OK\n"),
        ]
        report = health_check(_host(), 100)
        self.assertEqual(report.status, "running")
        self.assertEqual(report.ip, "10.0.0.50")
        self.assertTrue(report.pingable)
        self.assertTrue(report.ssh_open)
        self.assertTrue(report.healthy)

    @patch("lib.proxmox_manage._ssh_run")
    def test_failed_ping_is_unhealthy(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            _completed("status: running\n"),
            _completed("net0: name=eth0,bridge=vmbr0,ip=10.0.0.50/24\n"),
            _completed("FAIL\n"),
            _completed("OK\n"),
        ]
        report = health_check(_host(), 100)
        self.assertFalse(report.pingable)
        self.assertFalse(report.healthy)

    @patch("lib.proxmox_manage._ssh_run")
    def test_stopped_container_is_unhealthy(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            _completed("status: stopped\n"),
            _completed("net0: name=eth0,bridge=vmbr0,ip=10.0.0.50/24\n"),
        ]
        report = health_check(_host(), 100)
        self.assertEqual(report.status, "stopped")
        self.assertFalse(report.healthy)
        self.assertTrue(any("not running" in n for n in report.notes))

    @patch("lib.proxmox_manage._ssh_run")
    def test_no_ip_short_circuits(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            _completed("status: running\n"),
            _completed(""),  # no net0
        ]
        report = health_check(_host(), 100)
        self.assertIsNone(report.ip)
        self.assertFalse(report.healthy)
        self.assertTrue(any("No IPv4" in n for n in report.notes))

    @patch("lib.proxmox_manage._ssh_run")
    def test_status_failure_short_circuits(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed(stderr="bad vmid", returncode=2)
        report = health_check(_host(), 100)
        self.assertEqual(report.status, "unknown")
        self.assertFalse(report.healthy)
        self.assertTrue(report.notes)

    @patch("lib.proxmox_manage._ssh_run")
    def test_skip_ssh_probe(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            _completed("status: running\n"),
            _completed("net0: name=eth0,bridge=vmbr0,ip=10.0.0.50/24\n"),
            _completed("OK\n"),
        ]
        report = health_check(_host(), 100, probe_ssh=False)
        self.assertIsNone(report.ssh_open)
        self.assertTrue(report.healthy)


if __name__ == "__main__":
    unittest.main()
