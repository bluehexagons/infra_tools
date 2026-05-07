"""Tests for lib/proxmox_vm.py: parsers and check_vm_exists."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.proxmox_vm import (
    ProvisionError,
    _parse_disk_size_gib,
    _parse_memory_mb,
    _render_user_data,
    check_vm_exists,
)


class TestParseMemory(unittest.TestCase):
    def test_gigabytes(self):
        self.assertEqual(_parse_memory_mb("2G"), 2048)

    def test_megabytes(self):
        self.assertEqual(_parse_memory_mb("512M"), 512)

    def test_terabytes(self):
        self.assertEqual(_parse_memory_mb("1T"), 1024 * 1024)

    def test_bare_number_is_mib(self):
        self.assertEqual(_parse_memory_mb("4096"), 4096)

    def test_invalid_raises(self):
        with self.assertRaises(ProvisionError):
            _parse_memory_mb("")
        with self.assertRaises(ProvisionError):
            _parse_memory_mb("abc")
        with self.assertRaises(ProvisionError):
            _parse_memory_mb("0G")


class TestParseDiskSize(unittest.TestCase):
    def test_gigabytes(self):
        self.assertEqual(_parse_disk_size_gib("32G"), 32)

    def test_terabytes(self):
        self.assertEqual(_parse_disk_size_gib("2T"), 2048)

    def test_megabytes_rounded(self):
        self.assertEqual(_parse_disk_size_gib("8192M"), 8)

    def test_too_small_raises(self):
        with self.assertRaises(ProvisionError):
            _parse_disk_size_gib("100M")
        with self.assertRaises(ProvisionError):
            _parse_disk_size_gib("0G")


class TestRenderUserData(unittest.TestCase):
    def test_includes_root_key(self):
        out = _render_user_data(username="root", pubkey_contents="ssh-ed25519 AAAA test")
        self.assertIn("- name: root", out)
        self.assertIn("ssh-ed25519 AAAA test", out)

    def test_creates_non_root_user(self):
        out = _render_user_data(username="alice", pubkey_contents="ssh-ed25519 KEY")
        self.assertIn("- name: alice", out)
        self.assertIn("NOPASSWD:ALL", out)
        # SSH key is added under both root and alice.
        self.assertEqual(out.count("ssh-ed25519 KEY"), 2)

    def test_no_pubkey(self):
        out = _render_user_data(username="root", pubkey_contents=None)
        self.assertNotIn("ssh_authorized_keys", out)


class TestCheckVMExists(unittest.TestCase):
    @patch("lib.proxmox_vm._ssh_run")
    def test_finds_match(self, mock_run):
        # First call: qm list. Second call: qm config 100 (no match).
        # Third call: qm config 101 (match).
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="VMID NAME STATUS\n100 a running\n101 b running\n"),
            MagicMock(returncode=0, stdout="net0: virtio,bridge=vmbr0\nipconfig0: ip=10.0.0.1/24,gw=10.0.0.254\n"),
            MagicMock(returncode=0, stdout="ipconfig0: ip=10.0.0.50/24,gw=10.0.0.254\n"),
        ]
        self.assertTrue(check_vm_exists("10.0.0.1", "10.0.0.50", "root", []))

    @patch("lib.proxmox_vm._ssh_run")
    def test_no_match(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="VMID NAME STATUS\n100 a running\n"),
            MagicMock(returncode=0, stdout="ipconfig0: ip=10.0.0.99/24,gw=10.0.0.254\n"),
        ]
        self.assertFalse(check_vm_exists("10.0.0.1", "10.0.0.50", "root", []))

    @patch("lib.proxmox_vm._ssh_run")
    def test_dry_run_returns_false_without_calls(self, mock_run):
        self.assertFalse(check_vm_exists("10.0.0.1", "10.0.0.50", "root", [], dry_run=True))
        mock_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
