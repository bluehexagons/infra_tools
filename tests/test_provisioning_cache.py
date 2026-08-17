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
            container_storage=[["root", "local-lvm", "32G"]],
            container_cores=4,
            static_ipv4="10.0.0.50/24",
            ssh_key="/keys/agent",
        )

        with patch("infra_tools.load_setup_command", return_value=cached):
            reused = infra_tools._reuse_cached_provisioning_metadata(current, _args())

        self.assertTrue(reused)
        self.assertEqual(current.hosted_node, "10.0.0.10")
        self.assertEqual(current.container_memory, "4G")
        self.assertEqual(current.container_cores, 4)
        self.assertEqual(current.container_storage, [["root", "local-lvm", "32G"]])
        self.assertEqual(current.static_ipv4, "10.0.0.50/24")
        self.assertEqual(current.ssh_key, "/keys/agent")

    def test_explicit_guest_shape_change_requires_proxmox(self) -> None:
        current = _config(container_memory="8G")

        with patch("infra_tools.load_setup_command") as mock_load:
            reused = infra_tools._reuse_cached_provisioning_metadata(
                current,
                _args(container_memory="8G"),
            )

        self.assertFalse(reused)
        mock_load.assert_not_called()

        self.assertTrue(
            infra_tools._provisioning_changes_requested(_args(container_cores=1))
        )
        self.assertTrue(
            infra_tools._provisioning_changes_requested(_args(container_base="debian"))
        )

    def test_missing_local_metadata_requires_proxmox(self) -> None:
        with patch("infra_tools.load_setup_command", return_value=None):
            reused = infra_tools._reuse_cached_provisioning_metadata(
                _config(),
                _args(),
            )

        self.assertFalse(reused)

    def test_cidr_target_looks_up_metadata_by_guest_address(self) -> None:
        current = _config(host="10.0.0.50/20")
        cached = _config(static_ipv4="10.0.0.50/20")

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
        )
        args = _args()

        with patch("infra_tools.SetupConfig.from_args", return_value=current), \
             patch("infra_tools.load_setup_command", return_value=cached), \
             patch(
                 "infra_tools._prepare_runtime_config_for_cli",
                 side_effect=lambda config: config,
             ) as mock_prepare:
            result = infra_tools.run_setup_command(args)

        self.assertEqual(result, 0)
        mock_provision.assert_not_called()
        mock_prepare.assert_called_once_with(current)


if __name__ == "__main__":
    unittest.main()
