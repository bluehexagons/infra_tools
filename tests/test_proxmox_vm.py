"""Tests for lib/proxmox_vm.py: parsers and check_vm_exists."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.proxmox_vm import (
    ProvisionError,
    _create_vm,
    _needs_graphical_console,
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
        self.assertIn("packages:", out)
        self.assertIn("qemu-guest-agent", out)
        self.assertIn("virtio_balloon", out)
        self.assertIn("infra-tools-virtio-balloon.conf", out)
        self.assertIn("systemctl enable --now qemu-guest-agent", out)

    def test_creates_non_root_user(self):
        out = _render_user_data(username="alice", pubkey_contents="ssh-ed25519 KEY")
        self.assertIn("- name: alice", out)
        self.assertIn("NOPASSWD:ALL", out)
        # SSH key is added under both root and alice.
        self.assertEqual(out.count("ssh-ed25519 KEY"), 2)

    def test_no_pubkey(self):
        out = _render_user_data(username="root", pubkey_contents=None)
        self.assertNotIn("ssh_authorized_keys", out)
        self.assertIn("qemu-guest-agent", out)


class TestVMHardwareProfile(unittest.TestCase):
    def test_desktop_and_rdp_profiles_need_graphical_console(self):
        desktop = MagicMock(include_desktop=True, enable_rdp=False)
        rdp = MagicMock(include_desktop=False, enable_rdp=True)
        server = MagicMock(include_desktop=False, enable_rdp=False)

        self.assertTrue(_needs_graphical_console(desktop))
        self.assertTrue(_needs_graphical_console(rdp))
        self.assertFalse(_needs_graphical_console(server))

    @patch("lib.proxmox_vm._ssh_run")
    def test_graphical_vm_uses_virtio_gpu_and_disk_iothread(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        _create_vm(
            vmid=101,
            target_ip="10.0.0.50",
            image_remote_path="/var/lib/vz/template/iso/debian.qcow2",
            storage_ref=None,
            memory_mb=8192,
            balloon_min_mb=4096,
            cores=4,
            root_pool="local-lvm",
            disk_size_gib=40,
            cidr_prefix="24",
            bridge="vmbr0",
            gateway="10.0.0.1",
            nameservers=["10.0.0.1"],
            hostname="agent-vm",
            user_data_path=None,
            user_data_ref="nfs-store:snippets/infra_tools-agent-vm.yaml",
            graphical_console=True,
            node_ip="10.0.0.10",
            user="root",
            ssh_opts=[],
            ipv6_cidr="2001:db8::50/64",
            gateway6="2001:db8::1",
        )

        commands = [call.args[3] for call in mock_run.call_args_list]
        self.assertIn("--serial0 socket", commands[0])
        self.assertIn("--vga virtio", commands[0])
        self.assertIn("--agent enabled=1,freeze-fs=1", commands[0])
        self.assertIn("--rng0 source=/dev/urandom", commands[0])
        self.assertIn(
            "--cicustom user=nfs-store:snippets/infra_tools-agent-vm.yaml",
            commands[0],
        )
        self.assertIn("--scsihw virtio-scsi-single", commands[0])
        self.assertIn("--memory 8192 --balloon 4096", commands[0])
        self.assertEqual(
            commands[1],
            "qm disk import 101 /var/lib/vz/template/iso/debian.qcow2 local-lvm",
        )
        self.assertIn("ip6=2001:db8::50/64", commands[0])
        self.assertIn("gw6=2001:db8::1", commands[0])
        self.assertIn("--scsi0 local-lvm:vm-101-disk-0,iothread=1", commands[2])

    @patch("lib.proxmox_vm._ssh_run")
    def test_partial_vm_is_destroyed_when_import_fails(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(returncode=1, stdout="", stderr="import failed"),
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),
        ]
        with self.assertRaises(ProvisionError):
            _create_vm(
                vmid=101,
                target_ip="10.0.0.50",
                image_remote_path="/var/lib/vz/template/iso/debian.qcow2",
                storage_ref=None,
                memory_mb=2048,
                balloon_min_mb=2048,
                cores=2,
                root_pool="local-lvm",
                disk_size_gib=20,
                cidr_prefix="24",
                bridge="vmbr0",
                gateway="10.0.0.1",
                nameservers=["10.0.0.1"],
                hostname="agent-vm",
                user_data_path=None,
                user_data_ref=None,
                graphical_console=False,
                node_ip="10.0.0.10",
                user="root",
                ssh_opts=[],
            )
        commands = [call.args[3] for call in mock_run.call_args_list]
        self.assertEqual(commands[-2:], [
            "qm stop 101 --skiplock 1",
            "qm destroy 101 --purge 1 --skiplock 1",
        ])

    @patch("lib.proxmox_vm._ssh_run")
    def test_resize_failure_destroys_partial_vm(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(returncode=1, stdout="", stderr="cannot shrink disk"),
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),
        ]
        with self.assertRaisesRegex(ProvisionError, "cannot shrink disk"):
            _create_vm(
                vmid=101,
                target_ip="10.0.0.50",
                image_remote_path="/var/lib/vz/template/iso/debian.qcow2",
                storage_ref=None,
                memory_mb=2048,
                balloon_min_mb=2048,
                cores=2,
                root_pool="local-lvm",
                disk_size_gib=1,
                cidr_prefix="24",
                bridge="vmbr0",
                gateway="10.0.0.1",
                nameservers=["10.0.0.1"],
                hostname="agent-vm",
                user_data_path=None,
                user_data_ref=None,
                graphical_console=False,
                node_ip="10.0.0.10",
                user="root",
                ssh_opts=[],
            )
        commands = [call.args[3] for call in mock_run.call_args_list]
        self.assertEqual(commands[-2:], [
            "qm stop 101 --skiplock 1",
            "qm destroy 101 --purge 1 --skiplock 1",
        ])


class TestCheckVMExists(unittest.TestCase):
    @patch("lib.proxmox_vm._ssh_run")
    def test_finds_match(self, mock_run):
        # First call: qm list. Second call: qm config 100 (no match).
        # Third call: qm config 101 (match).
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="VMID NAME STATUS\n100 a running\n101 b running\n"),
            MagicMock(returncode=0, stdout="net0: virtio,bridge=vmbr0\nipconfig0: ip=10.0.0.1/24,gw=10.0.0.254\n"),
            MagicMock(returncode=0, stdout="ipconfig0: ip=10.0.0.50/24,gw=10.0.0.254\n"),
            MagicMock(returncode=0, stdout="status: running\n"),
            MagicMock(returncode=0, stdout="READY\n"),
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
    def test_unreachable_match_is_not_silently_reused(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="VMID NAME STATUS\n101 b running\n"),
            MagicMock(returncode=0, stdout="ipconfig0: ip=10.0.0.50/24,gw=10.0.0.254\n"),
            MagicMock(returncode=0, stdout="status: stopped\n"),
            MagicMock(returncode=1, stdout=""),
        ]
        with self.assertRaisesRegex(ProvisionError, "not reachable"):
            check_vm_exists("10.0.0.1", "10.0.0.50", "root", [])

    @patch("lib.proxmox_vm._ssh_run")
    def test_dry_run_returns_false_without_calls(self, mock_run):
        self.assertFalse(check_vm_exists("10.0.0.1", "10.0.0.50", "root", [], dry_run=True))
        mock_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
