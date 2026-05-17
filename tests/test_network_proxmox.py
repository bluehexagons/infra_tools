"""Tests for importing Proxmox host records into network inventory."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.network_inventory import (
    NetworkHost,
    NetworkProfile,
    find_network_profile,
    save_network_profile,
)
from lib.network_proxmox import (
    import_proxmox_guest_networks,
    import_registered_proxmox_hosts,
)
from lib.proxmox_hosts import ProxmoxHost, add_proxmox_host
from lib.proxmox_manage import ContainerInfo


class TestNetworkProxmoxImport(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = self.tmp.name

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_imports_registered_hosts_as_control_plane(self) -> None:
        add_proxmox_host(
            ProxmoxHost(name="pve1", address="10.0.0.10", tags=["prod"]),
            self.workspace,
        )
        add_proxmox_host(
            ProxmoxHost(name="pve2", address="10.0.0.11", tags=["prod"]),
            self.workspace,
        )

        result = import_registered_proxmox_hosts("homelab", self.workspace)

        self.assertEqual([host.name for host in result.imported_hosts], ["pve1", "pve2"])
        profile = find_network_profile("homelab", self.workspace)
        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual(profile.control_plane, ["10.0.0.10", "10.0.0.11"])
        self.assertEqual(profile.hosts[0].provider, "proxmox")
        self.assertEqual(profile.hosts[0].roles, ["control-plane", "proxmox"])
        self.assertEqual(profile.hosts[0].profile_ref, "proxmox:pve1")

    def test_import_is_idempotent(self) -> None:
        add_proxmox_host(ProxmoxHost(name="pve1", address="10.0.0.10"), self.workspace)

        import_registered_proxmox_hosts("homelab", self.workspace)
        import_registered_proxmox_hosts("homelab", self.workspace)

        profile = find_network_profile("homelab", self.workspace)
        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual(len(profile.hosts), 1)
        self.assertEqual(profile.control_plane, ["10.0.0.10"])

    def test_can_filter_by_tag(self) -> None:
        add_proxmox_host(
            ProxmoxHost(name="pve1", address="10.0.0.10", tags=["prod"]),
            self.workspace,
        )
        add_proxmox_host(
            ProxmoxHost(name="pve2", address="10.0.0.11", tags=["lab"]),
            self.workspace,
        )

        result = import_registered_proxmox_hosts(
            "homelab",
            self.workspace,
            tags=["prod"],
        )

        self.assertEqual([host.name for host in result.imported_hosts], ["pve1"])

    @patch("lib.network_proxmox.get_container_config")
    @patch("lib.network_proxmox.list_containers")
    def test_can_filter_by_target_address_case_insensitively(
        self,
        mock_list,
        mock_config,
    ) -> None:
        add_proxmox_host(
            ProxmoxHost(name="pve1", address="Pve1.Example.com"),
            self.workspace,
        )
        mock_list.return_value = [
            ContainerInfo(vmid=100, status="running", name="web", guest_type="lxc"),
        ]
        mock_config.return_value = {
            "net0": "name=eth0,bridge=vmbr20,ip=10.20.0.50/24,tag=20,type=veth"
        }

        result = import_proxmox_guest_networks(
            "homelab",
            self.workspace,
            targets=["pve1.example.com"],
        )

        self.assertEqual(result.scanned_guests, 1)
        self.assertEqual(result.imported_networks, ["10.20.0.0/24"])

    def test_import_requires_registered_hosts(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "No Proxmox hosts are registered; run 'proxmox add' first",
        ):
            import_registered_proxmox_hosts("homelab", self.workspace)

    def test_skips_conflicting_non_proxmox_host(self) -> None:
        save_network_profile(
            NetworkProfile(
                name="homelab",
                hosts=[
                    NetworkHost(
                        name="pve1",
                        address="10.0.0.10",
                        provider="generic",
                    )
                ],
            ),
            self.workspace,
        )
        add_proxmox_host(ProxmoxHost(name="pve1", address="10.0.0.10"), self.workspace)

        result = import_registered_proxmox_hosts("homelab", self.workspace)

        self.assertEqual(result.imported_hosts, [])
        self.assertEqual(result.skipped_hosts, ["pve1"])
        profile = find_network_profile("homelab", self.workspace)
        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual(profile.hosts[0].provider, "generic")

    def test_skips_address_only_conflict(self) -> None:
        save_network_profile(
            NetworkProfile(
                name="homelab",
                hosts=[
                    NetworkHost(
                        name="printer",
                        address="10.0.0.10",
                        provider="generic",
                    )
                ],
            ),
            self.workspace,
        )
        add_proxmox_host(ProxmoxHost(name="pve1", address="10.0.0.10"), self.workspace)

        result = import_registered_proxmox_hosts("homelab", self.workspace)

        self.assertEqual(result.imported_hosts, [])
        self.assertEqual(result.skipped_hosts, ["pve1"])
        profile = find_network_profile("homelab", self.workspace)
        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual(profile.hosts[0].name, "printer")

    @patch("lib.network_proxmox.get_container_config")
    @patch("lib.network_proxmox.list_containers")
    def test_imports_guest_networks(self, mock_list, mock_config) -> None:
        add_proxmox_host(ProxmoxHost(name="pve1", address="10.0.0.10"), self.workspace)
        mock_list.return_value = [
            ContainerInfo(vmid=100, status="running", name="web", guest_type="lxc"),
            ContainerInfo(vmid=101, status="running", name="db", guest_type="vm"),
        ]
        mock_config.side_effect = [
            {
                "net0": (
                    "name=eth0,bridge=vmbr20,ip=10.20.0.50/24,"
                    "gw=10.20.0.1,tag=20,type=veth"
                )
            },
            {
                "ipconfig0": "ip=10.30.0.60/24,gw=10.30.0.1",
            },
        ]

        result = import_proxmox_guest_networks("homelab", self.workspace)

        self.assertEqual(result.scanned_guests, 2)
        self.assertEqual(result.imported_networks, ["10.20.0.0/24", "10.30.0.0/24"])
        profile = find_network_profile("homelab", self.workspace)
        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual(profile.guest_networks, ["10.20.0.0/24", "10.30.0.0/24"])
        self.assertEqual(profile.subnets[0].zone, "guests")
        self.assertEqual(profile.subnets[0].vlan_id, 20)

    @patch("lib.network_proxmox.get_container_config")
    @patch("lib.network_proxmox.list_containers")
    def test_guest_network_import_skips_failed_config_reads_from_scan_count(
        self,
        mock_list,
        mock_config,
    ) -> None:
        add_proxmox_host(ProxmoxHost(name="pve1", address="10.0.0.10"), self.workspace)
        mock_list.return_value = [
            ContainerInfo(vmid=100, status="running", name="web", guest_type="lxc"),
        ]
        from lib.proxmox_manage import ProxmoxManageError

        mock_config.side_effect = ProxmoxManageError("boom")

        result = import_proxmox_guest_networks("homelab", self.workspace)

        self.assertEqual(result.scanned_guests, 0)
        self.assertEqual(len(result.skipped_guests), 1)

    @patch("lib.network_proxmox.get_container_config")
    @patch("lib.network_proxmox.list_containers")
    def test_guest_network_import_is_idempotent(self, mock_list, mock_config) -> None:
        add_proxmox_host(ProxmoxHost(name="pve1", address="10.0.0.10"), self.workspace)
        mock_list.return_value = [
            ContainerInfo(vmid=100, status="running", name="web", guest_type="lxc"),
        ]
        mock_config.return_value = {
            "net0": "name=eth0,bridge=vmbr20,ip=10.20.0.50/24,tag=20,type=veth"
        }

        import_proxmox_guest_networks("homelab", self.workspace)
        import_proxmox_guest_networks("homelab", self.workspace)

        profile = find_network_profile("homelab", self.workspace)
        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual(profile.guest_networks, ["10.20.0.0/24"])
        self.assertEqual(len(profile.subnets), 1)

    @patch("lib.network_proxmox.get_container_config")
    @patch("lib.network_proxmox.list_containers")
    def test_guest_network_import_ignores_dhcp(self, mock_list, mock_config) -> None:
        add_proxmox_host(ProxmoxHost(name="pve1", address="10.0.0.10"), self.workspace)
        mock_list.return_value = [
            ContainerInfo(vmid=100, status="running", name="web", guest_type="lxc"),
        ]
        mock_config.return_value = {
            "net0": "name=eth0,bridge=vmbr20,ip=dhcp,type=veth"
        }

        result = import_proxmox_guest_networks("homelab", self.workspace)

        self.assertEqual(result.imported_networks, [])
        profile = find_network_profile("homelab", self.workspace)
        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual(profile.guest_networks, [])

    @patch("lib.network_proxmox.get_container_config")
    @patch("lib.network_proxmox.list_containers")
    def test_guest_network_import_rejects_conflicting_vlan_for_same_cidr(
        self,
        mock_list,
        mock_config,
    ) -> None:
        add_proxmox_host(ProxmoxHost(name="pve1", address="10.0.0.10"), self.workspace)
        mock_list.return_value = [
            ContainerInfo(vmid=100, status="running", name="web", guest_type="lxc"),
            ContainerInfo(vmid=101, status="running", name="db", guest_type="vm"),
        ]
        mock_config.side_effect = [
            {"net0": "name=eth0,bridge=vmbr20,ip=10.20.0.50/24,tag=20,type=veth"},
            {"net0": "name=eth0,bridge=vmbr30,ip=10.20.0.60/24,tag=30,type=veth"},
        ]

        with self.assertRaisesRegex(ValueError, "Conflicting subnet definitions"):
            import_proxmox_guest_networks("homelab", self.workspace)


if __name__ == "__main__":
    unittest.main()
