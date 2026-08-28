"""Regression tests for existing Proxmox VM shape reconciliation."""

from __future__ import annotations

from argparse import Namespace
import unittest
from unittest.mock import MagicMock, patch

import infra_tools
from lib.config import SetupConfig
from lib.proxmox_vm import ProvisionError, _reconcile_existing_vm


class TestExistingVMMemoryReconciliation(unittest.TestCase):
    @patch("lib.proxmox_vm._enforce_memory_floor")
    @patch("lib.proxmox_vm._report_memory_capacity", return_value=True)
    @patch("lib.proxmox_vm._ssh_run")
    def test_memory_balloon_and_shares_are_applied_and_verified(
        self,
        mock_run,
        mock_capacity,
        mock_enforce,
    ) -> None:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="VMID NAME STATUS\n112 agent-2 running\n"),
            MagicMock(
                returncode=0,
                stdout=(
                    "name: agent-2\ncores: 3\nmemory: 2048\nballoon: 2048\n"
                    "shares: 500\nipconfig0: ip=10.0.0.50/24,gw=10.0.0.1\n"
                ),
            ),
            MagicMock(returncode=0, stdout="status: running\n"),
            MagicMock(returncode=0, stdout="READY\n"),
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(
                returncode=0,
                stdout=(
                    "name: agent-2\ncores: 3\nmemory: 4096\nballoon: 2048\n"
                    "shares: 1000\nipconfig0: ip=10.0.0.50/24,gw=10.0.0.1\n"
                ),
            ),
        ]

        self.assertTrue(
            _reconcile_existing_vm(
                "10.0.0.1",
                "10.0.0.50",
                "agent-2",
                "root",
                [],
                desired_cores=3,
                desired_memory_mib=4096,
                desired_balloon_min_mib=2048,
                desired_balloon_shares=1000,
            )
        )

        self.assertEqual(
            mock_run.call_args_list[4].args[3],
            "qm set 112 --memory 4096 --balloon 2048 --shares 1000",
        )
        mock_capacity.assert_called_once_with(
            node_ip="10.0.0.1",
            user="root",
            ssh_opts=[],
            proposed_minimum_mib=2048,
            proposed_maximum_mib=4096,
            replacing_vmid=112,
        )
        mock_enforce.assert_called_once_with(True, False)

    @patch("lib.proxmox_vm._enforce_memory_floor")
    @patch("lib.proxmox_vm._report_memory_capacity", return_value=False)
    @patch("lib.proxmox_vm._ssh_run")
    def test_memory_floor_policy_runs_before_provider_mutation(
        self,
        mock_run,
        _mock_capacity,
        mock_enforce,
    ) -> None:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="VMID NAME STATUS\n112 agent-2 running\n"),
            MagicMock(
                returncode=0,
                stdout=(
                    "name: agent-2\nmemory: 2048\nballoon: 1024\n"
                    "ipconfig0: ip=10.0.0.50/24,gw=10.0.0.1\n"
                ),
            ),
            MagicMock(returncode=0, stdout="status: running\n"),
            MagicMock(returncode=0, stdout="READY\n"),
        ]
        mock_enforce.side_effect = ProvisionError("unsafe floor")

        with self.assertRaisesRegex(ProvisionError, "unsafe floor"):
            _reconcile_existing_vm(
                "10.0.0.1",
                "10.0.0.50",
                "agent-2",
                "root",
                [],
                desired_memory_mib=8192,
                desired_balloon_min_mib=4096,
            )

        self.assertEqual(len(mock_run.call_args_list), 4)


class TestCachedProvisioningChangeSafety(unittest.TestCase):
    def test_vm_memory_changes_are_reconcilable(self) -> None:
        current = SetupConfig(
            host="10.0.0.50",
            username="agent",
            system_type="agent_code_vm",
            machine_type="vm",
            container_memory="8G",
        )
        cached = SetupConfig(
            host="10.0.0.50",
            username="agent",
            system_type="agent_code_vm",
            machine_type="vm",
            container_memory="4G",
        )

        changes = infra_tools._unsupported_cached_provisioning_changes(
            current,
            cached,
            Namespace(container_memory="8G"),
        )

        self.assertEqual(changes, [])

    def test_existing_vm_storage_change_is_rejected_before_cache_update(self) -> None:
        current = SetupConfig(
            host="10.0.0.50",
            username="agent",
            system_type="agent_code_vm",
            machine_type="vm",
            container_storage=[["root", "fast-lvm", "64G"]],
        )
        cached = SetupConfig(
            host="10.0.0.50",
            username="agent",
            system_type="agent_code_vm",
            machine_type="vm",
            container_storage=[["root", "local-lvm", "32G"]],
        )

        changes = infra_tools._unsupported_cached_provisioning_changes(
            current,
            cached,
            Namespace(container_storage=[["root", "fast-lvm", "64G"]]),
        )

        self.assertEqual(changes, ["--storage"])


if __name__ == "__main__":
    unittest.main()
