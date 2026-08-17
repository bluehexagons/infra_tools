"""Tests for Proxmox guest metadata updates during network handoffs."""

from __future__ import annotations

import subprocess
import unittest
from unittest.mock import MagicMock, patch

from lib.config import SetupConfig
from lib.proxmox_network_transition import (
    apply_proxmox_network_plan,
    prepare_proxmox_network_plan,
    rollback_proxmox_network_plan,
)


def _config(**overrides: object) -> SetupConfig:
    values: dict[str, object] = {
        "host": "10.0.0.50",
        "username": "admin",
        "system_type": "server_lite",
        "machine_type": "unprivileged",
        "hosted_node": "10.0.0.10",
        "hosted_user": "root",
        "static_ipv4": "10.0.0.60/24",
        "network_gateway4": "10.0.0.1",
    }
    values.update(overrides)
    return SetupConfig(**values)  # type: ignore[arg-type]


def _result(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout, "")


class TestPrepareProxmoxNetworkPlan(unittest.TestCase):
    @patch("lib.proxmox_network_transition._ssh_run")
    def test_lxc_update_preserves_bridge_firewall_mac_and_type(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            _result("VMID Status Name\n101 running app\n"),
            _result(
                "hostname: app\n"
                "net0: name=eth0,bridge=vmbr0,firewall=1,hwaddr=AA:BB:CC:DD:EE:FF,"
                "ip=10.0.0.50/24,gw=10.0.0.1,type=veth\n"
            ),
        ]

        plan = prepare_proxmox_network_plan(_config(), "10.0.0.50")

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.guest_kind, "LXC")
        self.assertEqual(plan.vmid, 101)
        self.assertIn("name=eth0", plan.requested_value)
        self.assertIn("bridge=vmbr0", plan.requested_value)
        self.assertIn("firewall=1", plan.requested_value)
        self.assertIn("hwaddr=AA:BB:CC:DD:EE:FF", plan.requested_value)
        self.assertIn("type=veth", plan.requested_value)
        self.assertIn("ip=10.0.0.60/24", plan.requested_value)
        self.assertNotIn("ip=10.0.0.50/24", plan.requested_value)

    @patch("lib.proxmox_network_transition._ssh_run")
    def test_vm_update_preserves_unmodified_ipv6_assignment(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            _result("VMID NAME STATUS\n201 app running\n"),
            _result(
                "name: app\n"
                "ipconfig0: ip=10.0.0.50/24,gw=10.0.0.1,"
                "ip6=2001:db8::50/64,gw6=2001:db8::1\n"
            ),
        ]

        plan = prepare_proxmox_network_plan(
            _config(machine_type="vm"),
            "10.0.0.50",
        )

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.guest_kind, "VM")
        self.assertIn("ip=10.0.0.60/24", plan.requested_value)
        self.assertIn("ip6=2001:db8::50/64", plan.requested_value)
        self.assertIn("gw6=2001:db8::1", plan.requested_value)

    @patch("lib.proxmox_network_transition._ssh_run")
    def test_refuses_ambiguous_guest_identity(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            _result("VMID Status Name\n101 running old\n102 stopped new\n"),
            _result("hostname: old\nnet0: name=eth0,ip=10.0.0.50/24,type=veth\n"),
            _result("hostname: new\nnet0: name=eth0,ip=10.0.0.60/24,type=veth\n"),
        ]

        with self.assertRaisesRegex(RuntimeError, "Multiple Proxmox"):
            prepare_proxmox_network_plan(_config(), "10.0.0.50")

    @patch("lib.proxmox_network_transition._ssh_run")
    def test_refuses_incomplete_conflict_scan_when_a_guest_is_unreadable(
        self,
        mock_run: MagicMock,
    ) -> None:
        mock_run.side_effect = [
            _result("VMID Status Name\n101 running old\n102 running unknown\n"),
            _result("hostname: old\nnet0: name=eth0,ip=10.0.0.50/24,type=veth\n"),
            subprocess.CompletedProcess([], 1, "", "permission denied"),
        ]

        with self.assertRaisesRegex(RuntimeError, "checking network conflicts"):
            prepare_proxmox_network_plan(_config(), "10.0.0.50")


class TestApplyProxmoxNetworkPlan(unittest.TestCase):
    @patch("lib.proxmox_network_transition._ssh_run")
    def test_applies_preflighted_value_with_pct(self, mock_run: MagicMock) -> None:
        from lib.proxmox_network_transition import ProxmoxNetworkPlan

        plan = ProxmoxNetworkPlan(
            node="10.0.0.10",
            user="root",
            ssh_opts=[],
            guest_kind="LXC",
            vmid=101,
            option="net0",
            previous_value="name=eth0,ip=10.0.0.50/24,type=veth",
            requested_value="name=eth0,type=veth,ip=10.0.0.60/24",
        )
        mock_run.side_effect = [
            _result(f"net0: {plan.previous_value}\n"),
            _result(),
            _result("net0: ip=10.0.0.60/24,name=eth0,type=veth\n"),
        ]

        apply_proxmox_network_plan(plan)

        self.assertEqual(
            mock_run.call_args_list[1].args[3],
            "pct set 101 --net0 name=eth0,type=veth,ip=10.0.0.60/24",
        )

    @patch("lib.proxmox_network_transition._ssh_run")
    def test_refuses_to_overwrite_metadata_changed_after_preflight(
        self,
        mock_run: MagicMock,
    ) -> None:
        from lib.proxmox_network_transition import ProxmoxNetworkPlan

        plan = ProxmoxNetworkPlan(
            node="10.0.0.10",
            user="root",
            ssh_opts=[],
            guest_kind="LXC",
            vmid=101,
            option="net0",
            previous_value="name=eth0,ip=10.0.0.50/24,type=veth",
            requested_value="name=eth0,ip=10.0.0.60/24,type=veth",
        )
        mock_run.return_value = _result(
            "net0: name=eth0,bridge=vmbr1,ip=10.0.0.50/24,type=veth\n"
        )

        with self.assertRaisesRegex(RuntimeError, "changed after preflight"):
            apply_proxmox_network_plan(plan)

        self.assertEqual(mock_run.call_count, 1)

    @patch("lib.proxmox_network_transition._ssh_run")
    def test_rollback_does_not_overwrite_a_concurrent_metadata_change(
        self,
        mock_run: MagicMock,
    ) -> None:
        from lib.proxmox_network_transition import ProxmoxNetworkPlan

        plan = ProxmoxNetworkPlan(
            node="10.0.0.10",
            user="root",
            ssh_opts=[],
            guest_kind="LXC",
            vmid=101,
            option="net0",
            previous_value="name=eth0,bridge=vmbr0,ip=10.0.0.50/24,type=veth",
            requested_value="name=eth0,bridge=vmbr0,ip=10.0.0.60/24,type=veth",
        )
        mock_run.return_value = _result(
            "net0: name=eth0,bridge=vmbr1,ip=10.0.0.60/24,type=veth\n"
        )

        rollback_proxmox_network_plan(plan)

        self.assertEqual(mock_run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
