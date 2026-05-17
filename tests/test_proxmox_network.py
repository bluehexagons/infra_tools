"""Tests for lib/proxmox_network.py."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.proxmox_hosts import ProxmoxHost, ProxmoxHostFacts
from lib.proxmox_network import suggest_free_ips


def _host(bridge: str | None = None) -> ProxmoxHost:
    facts = ProxmoxHostFacts(default_bridge=bridge) if bridge else None
    return ProxmoxHost(name="pve1", address="10.0.0.10", facts=facts)


def _ok(stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], 0, stdout, "")


def _fail() -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], 1, "", "error")


class TestSuggestFreeIps(unittest.TestCase):
    @patch("lib.proxmox_network._ssh_run")
    def test_suggests_unassigned_ips(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            _ok("10.0.0.1/24\n"),            # bridge CIDR
            _ok("10.0.0.50\n10.0.0.51\n"),  # assigned guest IPs
            _ok("10.0.0.50\n"),              # ARP table
            _ok("10.0.0.1\n"),               # gateway
        ]
        ips = suggest_free_ips(_host(bridge="vmbr0"), count=3)
        self.assertEqual(len(ips), 3)
        self.assertNotIn("10.0.0.1", ips)   # gateway excluded
        self.assertNotIn("10.0.0.50", ips)  # in use
        self.assertNotIn("10.0.0.51", ips)  # assigned to guest

    @patch("lib.proxmox_network._ssh_run")
    def test_returns_empty_when_cidr_unavailable(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _ok("")  # no CIDR output
        ips = suggest_free_ips(_host())
        self.assertEqual(ips, [])

    @patch("lib.proxmox_network._ssh_run")
    def test_returns_empty_on_invalid_cidr(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            _ok("not-a-cidr\n"),
            _ok(""),
            _ok(""),
            _ok(""),
        ]
        ips = suggest_free_ips(_host())
        self.assertEqual(ips, [])

    @patch("lib.proxmox_network._ssh_run")
    def test_respects_count(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            _ok("192.168.1.1/24\n"),
            _ok(""),   # no assigned IPs
            _ok(""),   # empty ARP
            _ok("192.168.1.1\n"),
        ]
        ips = suggest_free_ips(_host(), count=2)
        self.assertEqual(len(ips), 2)

    @patch("lib.proxmox_network._ssh_run")
    def test_uses_bridge_from_facts(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            _ok("10.1.0.1/24\n"),
            _ok(""),
            _ok(""),
            _ok("10.1.0.1\n"),
        ]
        suggest_free_ips(_host(bridge="vmbr1"), count=1)
        cidr_call = mock_run.call_args_list[0]
        self.assertIn("vmbr1", cidr_call[0][3])

    @patch("lib.proxmox_network._ssh_run")
    def test_does_not_suggest_network_or_broadcast(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            _ok("10.0.0.1/30\n"),  # /30 — only .1 and .2 are hosts
            _ok(""),
            _ok(""),
            _ok(""),
        ]
        ips = suggest_free_ips(_host(), count=10)
        self.assertNotIn("10.0.0.0", ips)   # network address
        self.assertNotIn("10.0.0.3", ips)   # broadcast


if __name__ == "__main__":
    unittest.main()
