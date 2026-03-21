"""Tests for lib/proxmox_node.py: container hostname, bridge detection, template resolution."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.proxmox_node import (
    ProvisionError,
    _build_container_hostname,
    _create_container,
    auto_detect_bridge,
    _get_bridge_prefix_length,
    _resolve_storage_pool,
    _resolve_template_name,
    check_container_exists,
    _ssh_opts,
    _ssh_run,
)


class TestBuildContainerHostname(unittest.TestCase):
    def test_friendly_name(self):
        self.assertEqual(
            _build_container_hostname("10.0.0.50", "My Web Server"),
            "my-web-server"
        )

    def test_friendly_name_sanitized(self):
        self.assertEqual(
            _build_container_hostname("10.0.0.50", "Test_Server@2024!"),
            "test-server-2024"
        )

    def test_friendly_name_consecutive_hyphens(self):
        self.assertEqual(
            _build_container_hostname("10.0.0.50", "a--b---c"),
            "a-b-c"
        )

    def test_friendly_name_empty(self):
        self.assertEqual(
            _build_container_hostname("10.0.0.50", ""),
            "lxc-10-0-0-50"
        )

    def test_friendly_name_none(self):
        self.assertEqual(
            _build_container_hostname("10.0.0.50", None),
            "lxc-10-0-0-50"
        )

    def test_ip_derivation(self):
        self.assertEqual(
            _build_container_hostname("192.168.1.100", None),
            "lxc-192-168-1-100"
        )


class TestSshOpts(unittest.TestCase):
    def test_no_key(self):
        opts = _ssh_opts()
        self.assertIn("StrictHostKeyChecking=accept-new", opts)
        self.assertNotIn("-i", opts)

    def test_with_key(self):
        opts = _ssh_opts("/path/to/key")
        self.assertIn("-i", opts)
        self.assertIn("/path/to/key", opts)


class TestAutoDetectBridge(unittest.TestCase):
    @patch("lib.proxmox_node._ssh_run")
    def test_detects_vmbr0(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="vmbr0\nvmbr1\n", returncode=0
        )
        result = auto_detect_bridge("10.0.0.1", "root", dry_run=False)
        self.assertEqual(result, "vmbr0")

    @patch("lib.proxmox_node._ssh_run")
    def test_prefers_vmbr0(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="vmbr1\nvmbr0\n", returncode=0
        )
        result = auto_detect_bridge("10.0.0.1", "root", dry_run=False)
        self.assertEqual(result, "vmbr0")

    @patch("lib.proxmox_node._ssh_run")
    def test_no_bridge_raises(self, mock_run):
        mock_run.return_value = MagicMock(stdout="", returncode=0)
        with self.assertRaises(Exception):
            auto_detect_bridge("10.0.0.1", "root", dry_run=False)

    def test_dry_run_returns_vmbr0(self):
        result = auto_detect_bridge("10.0.0.1", "root", dry_run=True)
        self.assertEqual(result, "vmbr0")


class TestResolveStoragePool(unittest.TestCase):
    @patch("lib.proxmox_node._ssh_run")
    def test_explicit_pool(self, mock_run):
        mock_run.return_value = MagicMock(stdout="Name Type Status\nlocal-lvm dir active\n", returncode=0)
        result = _resolve_storage_pool("local-lvm", "10.0.0.1", "root", [], "images,rootdir")
        self.assertEqual(result, "local-lvm")

    @patch("lib.proxmox_node._ssh_run")
    def test_explicit_pool_inactive_raises(self, mock_run):
        mock_run.return_value = MagicMock(stdout="Name Type Status\nlocal dir active\n", returncode=0)
        with self.assertRaises(ProvisionError):
            _resolve_storage_pool("local-lvm", "10.0.0.1", "root", [], "images,rootdir")

    @patch("lib.proxmox_node._ssh_run")
    def test_explicit_pool_uses_unfiltered_fallback(self, mock_run):
        filtered = MagicMock(stdout="", stderr="unsupported option", returncode=1)
        unfiltered = MagicMock(
            stdout="Name Type Status\nlocal-lvm lvmthin active\n",
            returncode=0,
        )
        mock_run.side_effect = [filtered, unfiltered]
        result = _resolve_storage_pool("local-lvm", "10.0.0.1", "root", [], "images,rootdir")
        self.assertEqual(result, "local-lvm")

    @patch("lib.proxmox_node._ssh_run")
    def test_auto_selects_active_pool(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="Name         Type    Status  Total    Used    Available  %\n"
                   "local        dir     active  100G     20G     80G        20%\n"
                   "local-lvm    lvmph   active  200G     50G     150G       25%\n",
            returncode=0
        )
        result = _resolve_storage_pool("auto", "10.0.0.1", "root", [], "images,rootdir")
        self.assertEqual(result, "local")

    @patch("lib.proxmox_node._ssh_run")
    def test_auto_no_pools_raises(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="Name  Type  Status\n", returncode=0
        )
        with self.assertRaises(Exception):
            _resolve_storage_pool("auto", "10.0.0.1", "root", [], "images,rootdir")

    @patch("lib.proxmox_node._ssh_run")
    def test_auto_filtered_query_failure_raises(self, mock_run):
        mock_run.return_value = MagicMock(stdout="", stderr="unsupported option", returncode=1)
        with self.assertRaises(ProvisionError):
            _resolve_storage_pool("auto", "10.0.0.1", "root", [], "vztmpl")


class TestBridgePrefixDetection(unittest.TestCase):
    @patch("lib.proxmox_node._ssh_run")
    def test_detects_prefix(self, mock_run):
        mock_run.return_value = MagicMock(stdout="10.0.0.1/23\n", returncode=0)
        result = _get_bridge_prefix_length("10.0.0.1", "root", [], "vmbr0")
        self.assertEqual(result, "23")


class TestCreateContainer(unittest.TestCase):
    @patch("lib.proxmox_node._ssh_run")
    def test_pct_create_failure_raises(self, mock_run):
        mock_run.return_value = MagicMock(stdout="", stderr="boom", returncode=1)
        with self.assertRaises(ProvisionError):
            _create_container(
                vmid=100,
                target_ip="10.0.0.50",
                template_path="/var/lib/vz/template/cache/debian.tar.zst",
                memory="2G",
                cores=1,
                root_pool="local-lvm",
                storage_amount="10G",
                cidr_prefix="24",
                bridge="vmbr0",
                gateway="10.0.0.1",
                nameservers=["8.8.8.8"],
                hostname="lxc-10-0-0-50",
                node_ip="10.0.0.1",
                user="root",
                ssh_opts=[],
                dry_run=False,
            )


class TestResolveTemplateName(unittest.TestCase):
    @patch("lib.proxmox_node._ssh_run")
    def test_debian_resolves_latest(self, mock_run):
        # pveam update, pveam available, pveam download
        pveam_available = MagicMock(
            stdout="system/debian-11-standard_11.7-1_amd64.tar.zst\n"
                   "system/debian-12-standard_12.0-1_amd64.tar.zst\n"
                   "system/ubuntu-22.04-standard_22.04-1_amd64.tar.zst\n",
            returncode=0
        )
        mock_run.return_value = pveam_available
        result = _resolve_template_name("debian", "local", "10.0.0.1", "root", [])
        self.assertIn("debian-12-standard", result)

    @patch("lib.proxmox_node._ssh_run")
    def test_ubuntu_passthrough(self, mock_run):
        pveam_available = MagicMock(
            stdout="system/ubuntu-22.04-standard_22.04-1_amd64.tar.zst\n"
                   "system/ubuntu-24.04-standard_24.04-1_amd64.tar.zst\n",
            returncode=0
        )
        mock_run.return_value = pveam_available
        result = _resolve_template_name("ubuntu", "local", "10.0.0.1", "root", [])
        self.assertIn("ubuntu-24.04", result)

    @patch("lib.proxmox_node._ssh_run")
    def test_no_match_checks_downloaded(self, mock_run):
        # available returns nothing for "alpine"
        available = MagicMock(stdout="NAME\nsystem/debian-12-standard.tar.zst\n", returncode=0)
        # list shows a downloaded alpine template
        local_list = MagicMock(
            stdout="Name                              Size\n"
                   "alpine-3.19-standard_3.19-1_amd64.tar.zst  3M\n",
            returncode=0
        )
        mock_run.side_effect = [MagicMock(returncode=0), available, local_list]
        result = _resolve_template_name("alpine", "local", "10.0.0.1", "root", [])
        self.assertIn("alpine-3.19", result)

    @patch("lib.proxmox_node._ssh_run")
    def test_no_match_raises(self, mock_run):
        available = MagicMock(stdout="NAME\nsystem/debian-12-standard.tar.zst\n", returncode=0)
        local_list = MagicMock(stdout="Name  Size\n", returncode=0)
        mock_run.side_effect = [MagicMock(returncode=0), available, local_list]
        with self.assertRaises(Exception):
            _resolve_template_name("nonexistent-os", "local", "10.0.0.1", "root", [])


class TestCheckContainerExists(unittest.TestCase):
    @patch("lib.proxmox_node._ssh_run")
    def test_no_containers(self, mock_run):
        mock_run.return_value = MagicMock(stdout="", returncode=0)
        result = check_container_exists("10.0.0.1", "10.0.0.50")
        self.assertFalse(result)

    @patch("lib.proxmox_node._ssh_run")
    def test_container_with_matching_ip(self, mock_run):
        list_result = MagicMock(stdout="100\n101\n", returncode=0)
        config_100 = MagicMock(
            stdout="net0: name=eth0,bridge=vmbr0,ip=10.0.0.50/24,gw=10.0.0.1,type=veth\n",
            returncode=0
        )
        mock_run.side_effect = [list_result, config_100]
        result = check_container_exists("10.0.0.1", "10.0.0.50")
        self.assertTrue(result)

    @patch("lib.proxmox_node._ssh_run")
    def test_container_without_matching_ip(self, mock_run):
        list_result = MagicMock(stdout="100\n", returncode=0)
        config_100 = MagicMock(
            stdout="net0: name=eth0,bridge=vmbr0,ip=10.0.0.99/24,gw=10.0.0.1,type=veth\n",
            returncode=0
        )
        mock_run.side_effect = [list_result, config_100]
        result = check_container_exists("10.0.0.1", "10.0.0.50")
        self.assertFalse(result)


if __name__ == '__main__':
    unittest.main()
