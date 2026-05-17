"""Tests for lib/proxmox_hosts.py: registry CRUD."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.proxmox_hosts import (
    ProxmoxHost,
    ProxmoxHostFacts,
    ProxmoxStoragePool,
    add_proxmox_host,
    find_proxmox_host,
    get_proxmox_hosts_path,
    load_proxmox_hosts,
    remove_proxmox_host,
    save_proxmox_hosts,
)


class _WorkspaceFixture(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = self._tmp.name

    def tearDown(self) -> None:
        self._tmp.cleanup()


class TestProxmoxHostRecord(unittest.TestCase):
    def test_to_from_dict_roundtrip(self) -> None:
        host = ProxmoxHost(
            name="pve1", address="10.0.0.10", user="root",
            ssh_key="/key", description="primary",
            default_storage="local-lvm",
            default_template_storage="local",
            default_bridge="vmbr0",
            facts=ProxmoxHostFacts(
                node_name="pve1",
                bridges=["vmbr0", "vmbr1"],
                gateway="10.0.0.1",
                nameservers=["1.1.1.1", "8.8.8.8"],
                storage_pools=[
                    ProxmoxStoragePool(
                        name="local-lvm",
                        type="lvmthin",
                        status="active",
                        content=["images", "rootdir"],
                    ),
                    ProxmoxStoragePool(
                        name="local",
                        type="dir",
                        status="active",
                        content=["vztmpl"],
                    ),
                ],
                default_root_storage="local-lvm",
                default_template_storage="local",
                default_bridge="vmbr0",
            ),
            tags=["prod", "az-east"],
        )
        restored = ProxmoxHost.from_dict(host.to_dict())
        self.assertEqual(restored, host)

    def test_from_dict_requires_name_and_address(self) -> None:
        with self.assertRaises(ValueError):
            ProxmoxHost.from_dict({"name": "pve"})
        with self.assertRaises(ValueError):
            ProxmoxHost.from_dict({"address": "10.0.0.10"})

    def test_from_dict_rejects_bad_tags(self) -> None:
        with self.assertRaises(ValueError):
            ProxmoxHost.from_dict({
                "name": "pve", "address": "10.0.0.10", "tags": "prod"
            })

    def test_from_dict_rejects_bad_facts_lists(self) -> None:
        with self.assertRaises(ValueError):
            ProxmoxHost.from_dict({
                "name": "pve",
                "address": "10.0.0.10",
                "facts": {"bridges": "vmbr0"},
            })


class TestRegistryRoundTrip(_WorkspaceFixture):
    def test_empty_registry_returns_empty_list(self) -> None:
        self.assertEqual(load_proxmox_hosts(self.workspace), [])

    def test_save_and_load_preserves_order_and_fields(self) -> None:
        hosts = [
            ProxmoxHost(name="a", address="10.0.0.1"),
            ProxmoxHost(name="b", address="10.0.0.2", user="admin"),
        ]
        path = save_proxmox_hosts(hosts, self.workspace)
        self.assertEqual(path, get_proxmox_hosts_path(self.workspace))
        loaded = load_proxmox_hosts(self.workspace)
        self.assertEqual(loaded, hosts)

    def test_save_writes_file_with_restrictive_perms(self) -> None:
        save_proxmox_hosts([ProxmoxHost(name="a", address="10.0.0.1")], self.workspace)
        path = get_proxmox_hosts_path(self.workspace)
        mode = os.stat(path).st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_load_rejects_non_array(self) -> None:
        path = get_proxmox_hosts_path(self.workspace)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('{"not": "an array"}')
        with self.assertRaises(ValueError):
            load_proxmox_hosts(self.workspace)


class TestAddProxmoxHost(_WorkspaceFixture):
    def test_add_new_host(self) -> None:
        host = ProxmoxHost(name="pve1", address="10.0.0.10")
        add_proxmox_host(host, self.workspace)
        self.assertEqual(load_proxmox_hosts(self.workspace), [host])

    def test_add_duplicate_without_replace_raises(self) -> None:
        host = ProxmoxHost(name="pve1", address="10.0.0.10")
        add_proxmox_host(host, self.workspace)
        with self.assertRaises(ValueError):
            add_proxmox_host(
                ProxmoxHost(name="PVE1", address="10.0.0.99"),
                self.workspace,
            )

    def test_add_duplicate_with_replace_overwrites(self) -> None:
        add_proxmox_host(
            ProxmoxHost(name="pve1", address="10.0.0.10"), self.workspace
        )
        add_proxmox_host(
            ProxmoxHost(name="pve1", address="10.0.0.11", description="updated"),
            self.workspace, replace=True,
        )
        loaded = load_proxmox_hosts(self.workspace)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].address, "10.0.0.11")
        self.assertEqual(loaded[0].description, "updated")

    def test_add_requires_name_and_address(self) -> None:
        with self.assertRaises(ValueError):
            add_proxmox_host(ProxmoxHost(name="", address="10.0.0.1"), self.workspace)
        with self.assertRaises(ValueError):
            add_proxmox_host(ProxmoxHost(name="pve", address=""), self.workspace)


class TestFindAndRemove(_WorkspaceFixture):
    def setUp(self) -> None:
        super().setUp()
        add_proxmox_host(
            ProxmoxHost(name="pve1", address="10.0.0.10"), self.workspace
        )
        add_proxmox_host(
            ProxmoxHost(name="pve2", address="10.0.0.20"), self.workspace
        )

    def test_find_by_name_case_insensitive(self) -> None:
        host = find_proxmox_host("PVE1", self.workspace)
        self.assertIsNotNone(host)
        assert host is not None
        self.assertEqual(host.address, "10.0.0.10")

    def test_find_by_address(self) -> None:
        host = find_proxmox_host("10.0.0.20", self.workspace)
        self.assertIsNotNone(host)
        assert host is not None
        self.assertEqual(host.name, "pve2")

    def test_find_missing_returns_none(self) -> None:
        self.assertIsNone(find_proxmox_host("nope", self.workspace))

    def test_remove_by_name(self) -> None:
        self.assertTrue(remove_proxmox_host("pve1", self.workspace))
        self.assertEqual(
            [h.name for h in load_proxmox_hosts(self.workspace)], ["pve2"]
        )

    def test_remove_missing_returns_false(self) -> None:
        self.assertFalse(remove_proxmox_host("missing", self.workspace))


if __name__ == "__main__":
    unittest.main()
