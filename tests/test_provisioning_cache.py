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
        "storage_caches": None,
        "vm_image": None,
        "vm_image_storage": None,
        "static_ipv4": None,
        "system_hostname": None,
        "friendly_name": None,
    }
    values.update(overrides)
    return Namespace(**values)


class TestCachedProvisioningMetadata(unittest.TestCase):
    def test_setup_parser_accepts_force_provider_verification(self) -> None:
        parser, _setup_parser, _patch_parser = infra_tools.create_infra_tools_parser()

        args = parser.parse_args(
            [
                "setup",
                "agent_code_vm",
                "10.0.0.50",
                "agent",
                "--provision-on",
                "pve1",
                "--verify-provider",
            ]
        )

        self.assertTrue(args.verify_provider)

    def test_force_provider_verification_requires_provisioning_host(self) -> None:
        args = _args(verify_provider=True)

        with patch("infra_tools.prompt_for_missing_passwords"), \
             patch(
                 "infra_tools.SetupConfig.from_args",
                 return_value=_config(hosted_node=None),
             ), \
             patch("builtins.print") as mock_print:
            result = infra_tools.run_setup_command(args)

        self.assertEqual(result, 1)
        mock_print.assert_called_once_with(
            "Error: --verify-provider requires --provision-on"
        )

    def test_setup_reports_configuration_errors_without_a_traceback(self) -> None:
        args = _args()

        with patch("infra_tools.prompt_for_missing_passwords"), \
             patch(
                 "infra_tools.SetupConfig.from_args",
                 side_effect=ValueError("invalid setup selection"),
             ), \
             patch("builtins.print") as mock_print:
            result = infra_tools.run_setup_command(args)

        self.assertEqual(result, 1)
        mock_print.assert_called_once_with("Error: invalid setup selection")

    def test_patch_reports_configuration_errors_without_a_traceback(self) -> None:
        args = _args()
        cached = _config()

        with patch("infra_tools.validate_host", return_value=True), \
             patch("infra_tools.validate_username", return_value=True), \
             patch("infra_tools.load_setup_command", return_value=cached), \
             patch(
                 "infra_tools.SetupConfig.from_args",
                 side_effect=ValueError("invalid patch selection"),
             ), \
             patch("builtins.print") as mock_print:
            result = infra_tools.run_patch_command(args)

        self.assertEqual(result, 1)
        mock_print.assert_called_once_with("Error: invalid patch selection")

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
            storage_caches=[["agent-data", "agent-cache"]],
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
        self.assertEqual(
            current.storage_caches,
            [["agent-data", "agent-cache"]],
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

    def test_force_provider_verification_bypasses_matching_cache(self) -> None:
        current = _config(container_cores=3)
        cached = _config(
            hosted_node="10.0.0.10",
            container_cores=3,
            static_ipv4="10.0.0.50/24",
            network_gateway4="10.0.0.1",
            network_dns=["1.1.1.1"],
        )

        with patch("infra_tools.load_setup_command", return_value=cached):
            reused = infra_tools._reuse_cached_provisioning_metadata(
                current,
                _args(container_cores=3, verify_provider=True),
            )

        self.assertFalse(reused)
        self.assertEqual(current.hosted_node, "10.0.0.10")

    def test_missing_local_metadata_requires_proxmox(self) -> None:
        with patch("infra_tools.load_setup_command", return_value=None):
            reused = infra_tools._reuse_cached_provisioning_metadata(
                _config(),
                _args(),
            )

        self.assertFalse(reused)

    def test_changed_vm_name_requires_proxmox_reconciliation(self) -> None:
        current = _config(friendly_name="agent-min-2")
        cached = _config(
            friendly_name="agent-min-1",
            static_ipv4="10.0.0.50/24",
            network_gateway4="10.0.0.1",
            network_dns=["1.1.1.1"],
        )

        with patch("infra_tools.load_setup_command", return_value=cached):
            reused = infra_tools._reuse_cached_provisioning_metadata(
                current,
                _args(friendly_name="agent-min-2"),
            )

        self.assertFalse(reused)
        self.assertEqual(current.hosted_node, cached.hosted_node)
        self.assertEqual(current.static_ipv4, "10.0.0.50/24")

    def test_explicit_cached_vm_identity_reuses_metadata(self) -> None:
        current = _config(friendly_name="agent-min-2")
        cached = _config(
            friendly_name="agent-min-2",
            static_ipv4="10.0.0.50/24",
            network_gateway4="10.0.0.1",
            network_dns=["1.1.1.1"],
        )

        with patch("infra_tools.load_setup_command", return_value=cached):
            reused = infra_tools._reuse_cached_provisioning_metadata(
                current,
                _args(friendly_name="agent-min-2"),
            )

        self.assertTrue(reused)

    def test_friendly_label_change_preserves_explicit_system_hostname(self) -> None:
        current = _config(friendly_name="new-label")
        cached = _config(
            friendly_name="old-label",
            system_hostname="stable-vm-name",
            static_ipv4="10.0.0.50/24",
            network_gateway4="10.0.0.1",
            network_dns=["1.1.1.1"],
        )

        with patch("infra_tools.load_setup_command", return_value=cached):
            reused = infra_tools._reuse_cached_provisioning_metadata(
                current,
                _args(friendly_name="new-label"),
            )

        self.assertTrue(reused)
        self.assertEqual(current.friendly_name, "new-label")
        self.assertEqual(current.system_hostname, "stable-vm-name")

    def test_changed_system_hostname_requires_proxmox_reconciliation(self) -> None:
        current = _config(system_hostname="new-host")
        cached = _config(
            system_hostname="old-host",
            static_ipv4="10.0.0.50/24",
            network_gateway4="10.0.0.1",
            network_dns=["1.1.1.1"],
        )

        with patch("infra_tools.load_setup_command", return_value=cached):
            reused = infra_tools._reuse_cached_provisioning_metadata(
                current,
                _args(system_hostname="new-host"),
            )

        self.assertFalse(reused)

    def test_omitted_names_are_preserved_from_cached_metadata(self) -> None:
        current = _config()
        cached = _config(
            friendly_name="agent-min-1",
            system_hostname="agent-host",
            static_ipv4="10.0.0.50/24",
            network_gateway4="10.0.0.1",
            network_dns=["1.1.1.1"],
        )

        with patch("infra_tools.load_setup_command", return_value=cached):
            reused = infra_tools._reuse_cached_provisioning_metadata(
                current,
                _args(),
            )

        self.assertTrue(reused)
        self.assertEqual(current.friendly_name, "agent-min-1")
        self.assertEqual(current.system_hostname, "agent-host")

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

    def test_managed_guest_refresh_requires_the_same_saved_identity(self) -> None:
        cached = _config(
            host="10.0.0.50",
            hosted_node="10.0.0.10",
            machine_type="vm",
        )

        self.assertTrue(
            infra_tools._is_same_cached_provisioned_guest(
                _config(
                    host="10.0.0.50/24",
                    hosted_node="10.0.0.10",
                    machine_type="vm",
                ),
                cached,
            )
        )
        self.assertFalse(
            infra_tools._is_same_cached_provisioned_guest(
                _config(host="10.0.0.51", hosted_node="10.0.0.10"),
                cached,
            )
        )
        self.assertFalse(
            infra_tools._is_same_cached_provisioned_guest(
                _config(host="10.0.0.50", hosted_node="10.0.0.11"),
                cached,
            )
        )
        self.assertFalse(
            infra_tools._is_same_cached_provisioned_guest(
                _config(
                    host="10.0.0.50",
                    hosted_node="10.0.0.10",
                    machine_type="unprivileged",
                ),
                cached,
            )
        )

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
        current = _config(
            friendly_name="agent-min-1",
            system_hostname="agent-host",
        )
        cached = _config(
            hosted_node="10.0.0.10",
            friendly_name="agent-min-1",
            system_hostname="agent-host",
            container_memory="4G",
            container_storage=[["root", "local-lvm", "32G"]],
            static_ipv4="10.0.0.50/24",
            network_gateway4="10.0.0.1",
            network_dns=["1.1.1.1"],
        )
        args = _args(
            friendly_name="agent-min-1",
            system_hostname="agent-host",
        )

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
            "agent",
            current.ssh_key,
            dry_run=False,
        )

    @patch("lib.proxmox_vm.provision_vm")
    @patch("infra_tools.register_proxmox_setup_host")
    @patch("infra_tools.save_setup_command")
    @patch("infra_tools.store_cli_credentials")
    @patch("infra_tools.print_setup_summary")
    @patch("infra_tools.run_remote_setup", return_value=0)
    @patch("infra_tools.validate_host", return_value=True)
    @patch("infra_tools.validate_username", return_value=True)
    def test_home_storage_uses_root_for_initial_network_repair(
        self,
        _mock_username,
        _mock_host,
        _mock_remote,
        _mock_summary,
        _mock_credentials,
        _mock_save,
        _mock_register,
        _mock_provision,
    ) -> None:
        current = _config(
            hosted_node="10.0.0.10",
            container_memory="4G",
            container_storage=[
                ["root", "local-lvm", "32G"],
                ["home-data", "local-lvm", "32G"],
            ],
            storage_mounts=[["home-data", "/home"]],
            static_ipv4="10.0.0.50/24",
            network_gateway4="10.0.0.1",
            network_dns=["1.1.1.1"],
        )

        with patch("infra_tools.SetupConfig.from_args", return_value=current), \
             patch("infra_tools.load_setup_command", return_value=None), \
             patch(
                 "infra_tools._prepare_runtime_config_for_cli",
                 side_effect=lambda config: config,
             ), \
             patch("infra_tools.ensure_guest_ipv4_route") as mock_route:
            result = infra_tools.run_setup_command(_args())

        self.assertEqual(result, 0)
        mock_route.assert_called_once_with(
            "10.0.0.50/24",
            "10.0.0.1",
            "root",
            current.ssh_key,
            dry_run=False,
        )

    def test_existing_cached_vm_refreshes_host_key_after_provisioning_check(
        self,
    ) -> None:
        from lib.proxmox_vm import VMAlreadyExists

        current = _config(
            hosted_node="10.0.0.10",
            hosted_user="root",
            hosted_key="/keys/proxmox",
            container_memory="8G",
            container_storage=[["root", "local-lvm", "32G"]],
            static_ipv4="10.0.0.50/24",
            network_gateway4="10.0.0.1",
            network_dns=["1.1.1.1"],
        )
        cached = _config(
            hosted_node="10.0.0.10",
            hosted_user="root",
            hosted_key="/keys/proxmox",
            container_memory="4G",
            container_storage=[["root", "local-lvm", "32G"]],
            static_ipv4="10.0.0.50/24",
            network_gateway4="10.0.0.1",
            network_dns=["1.1.1.1"],
        )
        args = _args(container_memory="8G")

        with patch("infra_tools.SetupConfig.from_args", return_value=current), \
             patch("infra_tools.load_setup_command", return_value=cached), \
             patch(
                 "infra_tools._prepare_runtime_config_for_cli",
                 side_effect=lambda config: config,
             ), \
             patch("infra_tools.validate_host", return_value=True), \
             patch("infra_tools.validate_username", return_value=True), \
             patch("infra_tools.print_setup_summary"), \
             patch("infra_tools.store_cli_credentials"), \
             patch("infra_tools.save_setup_command"), \
             patch("infra_tools.register_proxmox_setup_host"), \
             patch("infra_tools.run_remote_setup", return_value=0), \
             patch("infra_tools.ensure_guest_ipv4_route"), \
             patch(
                 "lib.proxmox_vm.provision_vm",
                 side_effect=VMAlreadyExists(),
             ), \
             patch(
                 "infra_tools.refresh_managed_guest_host_keys",
             ) as mock_refresh:
            result = infra_tools.run_setup_command(args)

        self.assertEqual(result, 0)
        mock_refresh.assert_called_once_with(
            "10.0.0.50",
            "10.0.0.10",
            "root",
            "/keys/proxmox",
            dry_run=False,
        )

    def test_existing_unsaved_vm_does_not_refresh_host_key(self) -> None:
        from lib.proxmox_vm import VMAlreadyExists

        current = _config(
            hosted_node="10.0.0.10",
            container_memory="4G",
            container_storage=[["root", "local-lvm", "32G"]],
            static_ipv4="10.0.0.50/24",
            network_gateway4="10.0.0.1",
            network_dns=["1.1.1.1"],
        )

        with patch("infra_tools.SetupConfig.from_args", return_value=current), \
             patch("infra_tools.load_setup_command", return_value=None), \
             patch(
                 "infra_tools._prepare_runtime_config_for_cli",
                 side_effect=lambda config: config,
             ), \
             patch("infra_tools.validate_host", return_value=True), \
             patch("infra_tools.validate_username", return_value=True), \
             patch("infra_tools.print_setup_summary"), \
             patch("infra_tools.store_cli_credentials"), \
             patch("infra_tools.save_setup_command"), \
             patch("infra_tools.register_proxmox_setup_host"), \
             patch("infra_tools.run_remote_setup", return_value=0), \
             patch("infra_tools.ensure_guest_ipv4_route"), \
             patch(
                 "lib.proxmox_vm.provision_vm",
                 side_effect=VMAlreadyExists(),
             ), \
             patch(
                 "infra_tools.refresh_managed_guest_host_keys",
             ) as mock_refresh:
            result = infra_tools.run_setup_command(_args())

        self.assertEqual(result, 0)
        mock_refresh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
