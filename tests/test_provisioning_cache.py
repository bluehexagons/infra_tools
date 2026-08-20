"""Tests for cache-aware Proxmox provisioning dispatch."""

from __future__ import annotations

from argparse import Namespace
import unittest
from unittest.mock import patch

import infra_tools
from lib.config import SetupConfig


def _config(**overrides: object) -> SetupConfig:
    values: dict[str, object] = {
        "host": "10.0.0.50",
        "username": "agent",
        "system_type": "workstation_dev",
        "machine_type": "vm",
        "hosted_node": "pve1",
    }
    values.update(overrides)
    return SetupConfig(**values)


def _args(**overrides: object) -> Namespace:
    values: dict[str, object] = {
        "host": "10.0.0.50",
        "username": "agent",
        "system_type": "workstation_dev",
        "hosted_node": "pve1",
        "machine_type": None,
        "hosted_bridge": None,
        "container_memory": None,
        "vm_balloon_min": None,
        "container_storage": None,
        "storage_mounts": None,
        "vm_image": None,
        "vm_image_storage": None,
        "static_ipv4": None,
    }
    values.update(overrides)
    return Namespace(**values)


class TestCachedProvisioningMetadata(unittest.TestCase):
    def test_reuses_saved_guest_shape_when_no_changes_are_requested(self) -> None:
        current = _config()
        cached = _config(
            hosted_node="10.0.0.10",
            hosted_bridge="vmbr0",
            container_memory="4G",
            vm_balloon_min="1G",
            container_storage=[
                ["root", "local-lvm", "32G"],
                ["agent-data", "bulk-lvm", "128G"],
            ],
            storage_mounts=[["agent-data", "/srv/agent-workspace"]],
            container_cores=4,
            static_ipv4="10.0.0.50/24",
            network_gateway4="10.0.0.1",
            network_dns=["1.1.1.1"],
            ssh_key="/keys/agent",
        )

        with patch("infra_tools.load_setup_command", return_value=cached):
            reused = infra_tools._reuse_cached_provisioning_metadata(current, _args())

        self.assertTrue(reused)
        self.assertEqual(current.hosted_node, "10.0.0.10")
        self.assertEqual(current.container_memory, "4G")
        self.assertEqual(current.container_cores, 4)
        self.assertEqual(
            current.container_storage,
            [
                ["root", "local-lvm", "32G"],
                ["agent-data", "bulk-lvm", "128G"],
            ],
        )
        self.assertEqual(
            current.storage_mounts,
            [["agent-data", "/srv/agent-workspace"]],
        )
        self.assertEqual(current.static_ipv4, "10.0.0.50/24")
        self.assertEqual(current.network_gateway4, "10.0.0.1")
        self.assertEqual(current.network_dns, ["1.1.1.1"])
        self.assertEqual(current.ssh_key, "/keys/agent")

    def test_explicit_guest_shape_change_requires_proxmox(self) -> None:
        current = _config(container_memory="8G")
        cached = _config(container_memory="4G")

        with patch("infra_tools.load_setup_command", return_value=cached) as mock_load:
            reused = infra_tools._reuse_cached_provisioning_metadata(
                current,
                _args(container_memory="8G"),
            )

        self.assertFalse(reused)
        mock_load.assert_called_once_with("10.0.0.50")

        self.assertTrue(
            infra_tools._provisioning_changes_requested(
                _config(container_cores=2),
                _config(container_cores=1),
                _args(container_cores=2),
            )
        )
        self.assertTrue(
            infra_tools._provisioning_changes_requested(
                _config(storage_mounts=[["data", "/srv/new"]]),
                _config(storage_mounts=[["data", "/srv/old"]]),
                _args(storage_mounts=[["data", "/srv/new"]]),
            )
        )
        self.assertTrue(
            infra_tools._provisioning_changes_requested(
                _config(container_base="ubuntu"),
                _config(container_base="debian"),
                _args(container_base="ubuntu"),
            )
        )

    def test_reuses_metadata_when_explicit_guest_shape_matches(self) -> None:
        current = _config(
            container_memory="4G",
            container_storage=[["root", "local-lvm", "32G"]],
            container_cores=4,
            container_base="debian",
        )
        cached = _config(
            hosted_node="10.0.0.10",
            container_memory="4G",
            container_storage=[["root", "local-lvm", "32G"]],
            container_cores=4,
            container_base="debian",
        )
        args = _args(
            container_memory="4G",
            container_storage=[["root", "local-lvm", "32G"]],
            container_cores=4,
            container_base="debian",
        )

        with patch("infra_tools.load_setup_command", return_value=cached):
            reused = infra_tools._reuse_cached_provisioning_metadata(current, args)

        self.assertTrue(reused)
        self.assertEqual(current.hosted_node, "10.0.0.10")

    def test_missing_local_metadata_requires_proxmox(self) -> None:
        with patch("infra_tools.load_setup_command", return_value=None):
            reused = infra_tools._reuse_cached_provisioning_metadata(
                _config(),
                _args(),
            )

        self.assertFalse(reused)

    def test_legacy_cache_without_network_defaults_requires_refresh(self) -> None:
        cached = _config(static_ipv4="10.0.0.50/24")

        with patch("infra_tools.load_setup_command", return_value=cached):
            reused = infra_tools._reuse_cached_provisioning_metadata(
                _config(),
                _args(),
            )

        self.assertFalse(reused)

    def test_cidr_target_looks_up_metadata_by_guest_address(self) -> None:
        current = _config(host="10.0.0.50/20")
        cached = _config(
            static_ipv4="10.0.0.50/20",
            network_gateway4="10.0.0.1",
            network_dns=["1.1.1.1"],
        )

        with patch(
            "infra_tools.load_setup_command",
            return_value=cached,
        ) as mock_load:
            reused = infra_tools._reuse_cached_provisioning_metadata(current, _args())

        self.assertTrue(reused)
        mock_load.assert_called_once_with("10.0.0.50")

    @patch("lib.proxmox_vm.provision_vm")
    @patch("infra_tools.register_proxmox_setup_host")
    @patch("infra_tools.save_setup_command")
    @patch("infra_tools.store_cli_credentials")
    @patch("infra_tools.print_setup_summary")
    @patch("infra_tools.run_remote_setup", return_value=0)
    @patch("infra_tools.validate_host", return_value=True)
    @patch("infra_tools.validate_username", return_value=True)
    def test_setup_skips_proxmox_for_cached_guest_without_shape_changes(
        self,
        _mock_username,
        _mock_host,
        _mock_remote,
        _mock_summary,
        _mock_credentials,
        _mock_save,
        _mock_register,
        mock_provision,
    ) -> None:
        current = _config()
        cached = _config(
            hosted_node="10.0.0.10",
            container_memory="4G",
            container_storage=[["root", "local-lvm", "32G"]],
            static_ipv4="10.0.0.50/24",
            network_gateway4="10.0.0.1",
            network_dns=["1.1.1.1"],
        )
        args = _args()

        with patch("infra_tools.SetupConfig.from_args", return_value=current), \
             patch("infra_tools.load_setup_command", return_value=cached), \
             patch(
                 "infra_tools._prepare_runtime_config_for_cli",
                 side_effect=lambda config: config,
             ) as mock_prepare:
            with patch("infra_tools.ensure_guest_ipv4_route") as mock_route:
                result = infra_tools.run_setup_command(args)

        self.assertEqual(result, 0)
        mock_provision.assert_not_called()
        mock_prepare.assert_called_once_with(current)
        mock_route.assert_called_once_with(
            "10.0.0.50/24",
            "10.0.0.1",
            current.ssh_key,
            dry_run=False,
        )


if __name__ == "__main__":
    unittest.main()
