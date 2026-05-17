"""Tests for shared Proxmox guest helpers."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.proxmox_guest import (
    _build_guest_hostname,
    _parse_corosync_config,
    _wait_for_guest_ssh,
    probe_proxmox_cluster,
    probe_proxmox_host,
)


class TestBuildGuestHostname(unittest.TestCase):
    def test_friendly_name_passthrough(self) -> None:
        self.assertEqual(
            _build_guest_hostname("10.0.0.50", "My Web Server", default_prefix="vm"),
            "my-web-server",
        )

    def test_default_prefix_rewrites_legacy_lxc_prefix(self) -> None:
        self.assertEqual(
            _build_guest_hostname("10.0.0.50", None, default_prefix="vm"),
            "vm-10-0-0-50",
        )
        self.assertEqual(
            _build_guest_hostname("10.0.0.50", None),
            "guest-10-0-0-50",
        )


class TestWaitForGuestSsh(unittest.TestCase):
    @patch("lib.proxmox_guest._ssh_run")
    def test_returns_when_probe_succeeds(self, mock_run) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="READY\n", stderr="")

        _wait_for_guest_ssh("10.0.0.50", "10.0.0.1", "root", [], timeout=3)

        mock_run.assert_called_once()

    @patch("lib.proxmox_guest._ssh_run")
    def test_dry_run_skips_probe(self, mock_run) -> None:
        _wait_for_guest_ssh("10.0.0.50", "10.0.0.1", "root", [], dry_run=True)
        mock_run.assert_not_called()


class TestProbeProxmoxHost(unittest.TestCase):
    @patch("lib.proxmox_guest._ssh_run")
    def test_discovers_defaults_and_storage_content(self, mock_run) -> None:
        mock_run.side_effect = [
            MagicMock(stdout="vmbr1\nvmbr0\n", returncode=0, stderr=""),
            MagicMock(
                stdout=(
                    "Name         Type     Status\n"
                    "local        dir      active\n"
                    "local-lvm    lvmthin  active\n"
                    "backup       dir      disabled\n"
                ),
                returncode=0,
                stderr="",
            ),
            MagicMock(stdout="Name Type Status\nlocal-lvm lvmthin active\n", returncode=0, stderr=""),
            MagicMock(stdout="Name Type Status\nlocal-lvm lvmthin active\n", returncode=0, stderr=""),
            MagicMock(stdout="Name Type Status\nlocal dir active\n", returncode=0, stderr=""),
            MagicMock(stdout="pve1\n", returncode=0, stderr=""),
            MagicMock(stdout="10.0.0.1\n", returncode=0, stderr=""),
            MagicMock(stdout="1.1.1.1\n8.8.8.8\n", returncode=0, stderr=""),
        ]

        facts = probe_proxmox_host("10.0.0.10", "root")

        self.assertEqual(facts.node_name, "pve1")
        self.assertEqual(facts.default_bridge, "vmbr0")
        self.assertEqual(facts.default_root_storage, "local-lvm")
        self.assertEqual(facts.default_template_storage, "local")
        self.assertEqual(facts.gateway, "10.0.0.1")
        self.assertEqual(facts.nameservers, ["1.1.1.1", "8.8.8.8"])
        self.assertEqual(facts.bridges, ["vmbr0", "vmbr1"])
        self.assertEqual(
            {pool.name: pool.content for pool in facts.storage_pools},
            {
                "local": ["vztmpl"],
                "local-lvm": ["images", "rootdir"],
                "backup": [],
            },
        )

    def test_dry_run_returns_sample_defaults(self) -> None:
        facts = probe_proxmox_host("10.0.0.10", "root", dry_run=True)

        self.assertEqual(facts.default_bridge, "vmbr0")
        self.assertEqual(facts.default_root_storage, "local-lvm")
        self.assertEqual(facts.default_template_storage, "local")


class TestProbeProxmoxCluster(unittest.TestCase):
    def test_parse_corosync_config_extracts_nodes(self) -> None:
        cluster_name, members = _parse_corosync_config(
            """
            totem {
              cluster_name: homelab
            }
            nodelist {
              node {
                name: pve1
                ring0_addr: 10.0.0.10
              }
              node {
                name: pve2
                ring0_addr: 10.0.0.11
              }
            }
            """
        )

        self.assertEqual(cluster_name, "homelab")
        self.assertEqual(
            members,
            [("pve1", "10.0.0.10"), ("pve2", "10.0.0.11")],
        )

    @patch("lib.proxmox_guest.probe_proxmox_host")
    @patch("lib.proxmox_guest._get_corosync_config")
    def test_cluster_probe_discovers_each_node(self, mock_corosync, mock_probe_host) -> None:
        mock_corosync.return_value = """
        nodelist {
          node {
            name: pve1
            ring0_addr: 10.0.0.10
          }
          node {
            name: pve2
            ring0_addr: 10.0.0.11
          }
        }
        """
        mock_probe_host.side_effect = [
            MagicMock(
                node_name="pve1",
                default_root_storage="local-lvm",
                default_template_storage="local",
                default_bridge="vmbr0",
            ),
            MagicMock(
                node_name="pve2",
                default_root_storage="shared-lvm",
                default_template_storage="local",
                default_bridge="vmbr1",
            ),
        ]

        hosts = probe_proxmox_cluster(
            "10.0.0.10",
            user="root",
            hosted_key="/keys/proxmox",
            tags=["prod"],
        )

        self.assertEqual([host.name for host in hosts], ["pve1", "pve2"])
        self.assertEqual([host.address for host in hosts], ["10.0.0.10", "10.0.0.11"])
        self.assertEqual(hosts[0].tags, ["prod"])
        self.assertEqual(hosts[1].default_storage, "shared-lvm")


if __name__ == "__main__":
    unittest.main()
