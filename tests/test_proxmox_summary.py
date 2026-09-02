"""Tests for lib/proxmox_summary.py."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.proxmox_hosts import ProxmoxHost
from lib.proxmox_summary import (
    NodeSummary,
    ProxmoxSummaryError,
    _bar,
    _fmt_bytes,
    format_node_summary,
    get_node_summary,
)


def _host(**kw) -> ProxmoxHost:
    return ProxmoxHost(name="pve1", address="10.0.0.10", **kw)


def _ok(stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], 0, stdout, "")


def _fail() -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], 1, "", "error")


_SUMMARY_JSON = json.dumps({
    "name": "pve1",
    "cpu": 0.15,
    "cpuinfo": {"cpus": 8},
    "memory": {"used": 4 * 1024 ** 3, "total": 16 * 1024 ** 3},
    "swap": {"used": 0, "total": 4 * 1024 ** 3},
    "rootfs": {"used": 20 * 1024 ** 3, "total": 100 * 1024 ** 3},
    "loadavg": ["0.50", "0.40", "0.30"],
    "uptime": 3661,
})

_PCT_LIST = "VMID Status Name\n100 running web\n101 stopped db\n"
_QM_LIST = "VMID NAME STATUS\n200 myvm running\n"


class TestGetNodeSummary(unittest.TestCase):
    @patch("lib.proxmox_summary._ssh_run")
    def test_parses_summary_fields(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            _ok(_SUMMARY_JSON),
            _ok(_PCT_LIST),
            _ok(_QM_LIST),
        ]
        summary = get_node_summary(_host())
        self.assertEqual(summary.node_name, "pve1")
        self.assertAlmostEqual(summary.cpu_usage, 0.15)
        self.assertEqual(summary.cpu_count, 8)
        self.assertEqual(summary.memory_total, 16 * 1024 ** 3)
        self.assertEqual(summary.guests_running, 2)  # 1 pct + 1 qm
        self.assertEqual(summary.guests_stopped, 1)
        self.assertEqual(
            mock_run.call_args_list[0].args[3],
            "pvesh get /nodes/$(hostname -s)/status --output-format json",
        )

    @patch("lib.proxmox_summary._ssh_run")
    def test_load_avg_parsed(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [_ok(_SUMMARY_JSON), _ok(""), _ok("")]
        summary = get_node_summary(_host())
        self.assertEqual(summary.load_avg, [0.50, 0.40, 0.30])

    @patch("lib.proxmox_summary._ssh_run")
    def test_raises_on_pvesh_failure(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _fail()
        with self.assertRaises(ProxmoxSummaryError):
            get_node_summary(_host())

    @patch("lib.proxmox_summary._ssh_run")
    def test_raises_on_invalid_json(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _ok("not json")
        with self.assertRaises(ProxmoxSummaryError):
            get_node_summary(_host())

    @patch("lib.proxmox_summary._ssh_run")
    def test_uptime_parsed(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [_ok(_SUMMARY_JSON), _ok(""), _ok("")]
        summary = get_node_summary(_host())
        self.assertEqual(summary.uptime_seconds, 3661)


class TestFormatNodeSummary(unittest.TestCase):
    def _summary(self, **kw) -> NodeSummary:
        defaults = dict(
            node_name="pve1",
            cpu_usage=0.15,
            cpu_count=8,
            memory_used=4 * 1024 ** 3,
            memory_total=16 * 1024 ** 3,
            swap_used=0,
            swap_total=0,
            disk_used=20 * 1024 ** 3,
            disk_total=100 * 1024 ** 3,
            uptime_seconds=3661,
            guests_running=2,
            guests_stopped=1,
            load_avg=[0.5, 0.4, 0.3],
        )
        defaults.update(kw)
        return NodeSummary(**defaults)

    def test_contains_node_name(self) -> None:
        out = format_node_summary(self._summary())
        self.assertIn("pve1", out)

    def test_contains_cpu_percentage(self) -> None:
        out = format_node_summary(self._summary())
        self.assertIn("15.0%", out)

    def test_contains_guest_counts(self) -> None:
        out = format_node_summary(self._summary())
        self.assertIn("2 running", out)
        self.assertIn("1 stopped", out)

    def test_hides_swap_when_zero(self) -> None:
        out = format_node_summary(self._summary(swap_total=0))
        self.assertNotIn("Swap", out)

    def test_shows_swap_when_present(self) -> None:
        out = format_node_summary(self._summary(swap_total=4 * 1024 ** 3))
        self.assertIn("Swap", out)

    def test_bar_full(self) -> None:
        self.assertEqual(_bar(1.0, width=4), "[####]")

    def test_bar_empty(self) -> None:
        self.assertEqual(_bar(0.0, width=4), "[....]")

    def test_bar_half(self) -> None:
        self.assertEqual(_bar(0.5, width=4), "[##..]")

    def test_fmt_bytes_gib(self) -> None:
        self.assertIn("GiB", _fmt_bytes(2 * 1024 ** 3))

    def test_fmt_bytes_mib(self) -> None:
        self.assertIn("MiB", _fmt_bytes(512 * 1024 ** 2))


if __name__ == "__main__":
    unittest.main()
