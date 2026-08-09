"""Tests for setup-time hostname and static network configuration."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from common import network_steps
from infra_tools import create_infra_tools_parser
from lib.config import SetupConfig
from lib.validation import validate_network_setup_settings, validate_system_hostname


def _config(**overrides: object) -> SetupConfig:
    values: dict[str, object] = {
        "host": "192.168.10.20",
        "username": "admin",
        "system_type": "server_lite",
    }
    values.update(overrides)
    return SetupConfig(**values)  # type: ignore[arg-type]


class TestNetworkSetupCLI(unittest.TestCase):
    def test_parses_and_serializes_network_and_hostname_options(self):
        parser, _setup_parser, _patch_parser = create_infra_tools_parser()
        args = parser.parse_args(
            [
                "setup",
                "server_lite",
                "192.168.10.20",
                "admin",
                "--hostname",
                "app-01.example.test",
                "--ip",
                "192.168.10.20/24",
                "--ipv6",
                "2001:db8:10::20/64",
                "--gateway",
                "192.168.10.1",
                "--gateway6",
                "2001:db8:10::1",
                "--dns",
                "1.1.1.1",
                "--dns",
                "2606:4700:4700::1111",
                "--network-interface",
                "enp1s0",
            ]
        )
        config = SetupConfig.from_args(args, args.system_type)
        validate_network_setup_settings(config)

        self.assertEqual(config.system_hostname, "app-01.example.test")
        self.assertEqual(config.static_ipv4, "192.168.10.20/24")
        self.assertEqual(config.static_ipv6, "2001:db8:10::20/64")
        self.assertEqual(config.network_dns, ["1.1.1.1", "2606:4700:4700::1111"])
        self.assertIn("--hostname app-01.example.test", config.to_remote_args())
        self.assertIn("--ip 192.168.10.20/24", config.to_setup_command())
        self.assertEqual(config.to_dict()["network_interface"], "enp1s0")


class TestNetworkSetupValidation(unittest.TestCase):
    def test_accepts_dual_stack_settings(self):
        validate_network_setup_settings(
            _config(
                system_hostname="app-01",
                static_ipv4="192.168.10.20/24",
                static_ipv6="2001:db8:10::20/64",
                network_gateway4="192.168.10.1",
                network_gateway6="fe80::1",
                network_dns=["192.168.10.53", "2001:4860:4860::8888"],
                network_interface="eth0",
            )
        )

    def test_requires_prefix_and_address_dependencies(self):
        with self.assertRaisesRegex(ValueError, "CIDR notation"):
            validate_network_setup_settings(_config(static_ipv4="192.168.10.20"))
        with self.assertRaisesRegex(ValueError, "requires --ip"):
            validate_network_setup_settings(_config(network_gateway4="192.168.10.1"))
        with self.assertRaisesRegex(ValueError, "requires --ip or --ipv6"):
            validate_network_setup_settings(_config(network_dns=["1.1.1.1"]))

    def test_rejects_wrong_families_duplicates_and_unsafe_hostnames(self):
        with self.assertRaisesRegex(ValueError, "requires an IPv4"):
            validate_network_setup_settings(_config(static_ipv4="2001:db8::2/64"))
        with self.assertRaisesRegex(ValueError, "Duplicate DNS"):
            validate_network_setup_settings(
                _config(static_ipv4="192.168.10.20/24", network_dns=["1.1.1.1", "1.1.1.1"])
            )
        with self.assertRaises(ValueError):
            validate_system_hostname("bad_name")
        with self.assertRaises(ValueError):
            validate_system_hostname("a" * 64)

    def test_rejects_generic_proxmox_node_network_changes(self):
        with self.assertRaisesRegex(ValueError, "not supported for server_proxmox"):
            validate_network_setup_settings(
                _config(system_type="server_proxmox", system_hostname="pve-new")
            )

    def test_hosted_literal_host_must_match_static_address(self):
        with self.assertRaisesRegex(ValueError, "must match"):
            validate_network_setup_settings(
                _config(
                    hosted_node="192.168.10.2",
                    static_ipv4="192.168.10.21/24",
                )
            )


class TestNetworkConfigRendering(unittest.TestCase):
    def test_networkd_dual_stack_render(self):
        rendered = network_steps._render_networkd_config(
            _config(
                static_ipv4="192.168.10.20/24",
                static_ipv6="2001:db8:10::20/64",
                network_gateway4="192.168.10.1",
                network_gateway6="fe80::1",
                network_dns=["1.1.1.1", "2606:4700:4700::1111"],
            ),
            "enp1s0",
        )
        self.assertIn("Name=enp1s0", rendered)
        self.assertIn("DHCP=no", rendered)
        self.assertIn("Address=192.168.10.20/24", rendered)
        self.assertIn("Address=2001:db8:10::20/64", rendered)
        self.assertIn("Gateway=fe80::1", rendered)
        self.assertIn("DNS=2606:4700:4700::1111", rendered)

    def test_ifupdown_replaces_stanzas_and_keeps_original_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            network_dir = os.path.join(temp_dir, "network")
            interfaces_dir = os.path.join(network_dir, "interfaces.d")
            os.makedirs(interfaces_dir)
            main_path = os.path.join(network_dir, "interfaces")
            managed_path = os.path.join(interfaces_dir, "infra_tools_static")
            original = (
                "auto lo\niface lo inet loopback\n\n"
                "auto eth0\niface eth0 inet dhcp\n    metric 10\n\n"
                f"source {interfaces_dir}/*\n"
            )
            with open(main_path, "w", encoding="utf-8") as file_obj:
                file_obj.write(original)

            with patch.multiple(
                network_steps,
                IFUPDOWN_MAIN_CONFIG_PATH=main_path,
                IFUPDOWN_CONFIG_DIR=interfaces_dir,
                IFUPDOWN_CONFIG_PATH=managed_path,
            ):
                config = _config(
                    static_ipv4="192.168.10.20/24",
                    network_gateway4="192.168.10.1",
                    network_dns=["1.1.1.1"],
                )
                network_steps._configure_ifupdown(config, "eth0")
                network_steps._configure_ifupdown(config, "eth0")

            with open(main_path, "r", encoding="utf-8") as file_obj:
                self.assertNotIn("iface eth0 inet dhcp", file_obj.read())
            with open(f"{main_path}.infra-tools.bak", "r", encoding="utf-8") as file_obj:
                self.assertEqual(file_obj.read(), original)
            with open(managed_path, "r", encoding="utf-8") as file_obj:
                managed = file_obj.read()
            self.assertIn("iface eth0 inet static", managed)
            self.assertIn("address 192.168.10.20/24", managed)
            self.assertIn("dns-nameservers 1.1.1.1", managed)

    @patch("common.network_steps.run")
    def test_networkmanager_configuration_is_persistent_but_not_activated(self, mock_run):
        mock_run.side_effect = [
            subprocess.CompletedProcess([], 0, "Wired connection 1\n", ""),
            subprocess.CompletedProcess([], 0, "", ""),
            subprocess.CompletedProcess([], 0, "", ""),
        ]
        network_steps._configure_networkmanager(
            _config(
                static_ipv4="192.168.10.20/24",
                network_gateway4="192.168.10.1",
                network_dns=["1.1.1.1"],
            ),
            "eth0",
        )
        commands = [call.args[0] for call in mock_run.call_args_list]
        self.assertTrue(any("ipv4.method manual" in command for command in commands))
        self.assertTrue(any("ipv4.dns 1.1.1.1" in command for command in commands))
        self.assertFalse(any("connection up" in command for command in commands))


class TestHostnameStep(unittest.TestCase):
    @patch("common.network_steps.write_text_atomic")
    @patch("common.network_steps.os.path.isdir", return_value=True)
    @patch("common.network_steps.is_dry_run", return_value=False)
    @patch("common.network_steps.run")
    def test_sets_hostname_and_prevents_cloud_init_reset(
        self,
        mock_run: MagicMock,
        _mock_dry_run: MagicMock,
        _mock_isdir: MagicMock,
        mock_write: MagicMock,
    ):
        network_steps.configure_system_hostname(_config(system_hostname="app-01"))
        mock_run.assert_called_once_with("hostnamectl set-hostname app-01")
        mock_write.assert_called_once()


if __name__ == "__main__":
    unittest.main()
