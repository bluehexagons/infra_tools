"""Tests for importing Proxmox host records into network inventory."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.network_inventory import (
    NetworkHost,
    NetworkProfile,
    find_network_profile,
    save_network_profile,
)
from lib.network_proxmox import import_registered_proxmox_hosts
from lib.proxmox_hosts import ProxmoxHost, add_proxmox_host


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


if __name__ == "__main__":
    unittest.main()
