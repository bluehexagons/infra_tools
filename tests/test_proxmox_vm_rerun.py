"""Regression tests for existing Proxmox VM shape reconciliation."""

from __future__ import annotations

from argparse import Namespace
import unittest
from unittest.mock import MagicMock, patch

import infra_tools
from lib.config import SetupConfig
from lib.proxmox_vm import (
    ProvisionError,
    _disk_hardware_update_verified,
    _disk_hardware_value,
    _reconcile_existing_vm,
    _storage_specs_with_resolved_pools,
    verify_vm_rebind_source_stopped,
)
from lib.vm_storage import VMDataDisk, VMDiskHardware


class TestExistingVMMemoryReconciliation(unittest.TestCase):
    def test_disk_hardware_value_replaces_conflicting_managed_options(self) -> None:
        value = _disk_hardware_value(
            "bulk:vm-112-disk-1,iothread=0,iothread=1,serial=old,size=64G",
            discard=True,
            ssd=False,
            backup=False,
            serial="it-data",
        )

        self.assertEqual(
            value,
            "bulk:vm-112-disk-1,iothread=1,serial=it-data,size=64G,"
            "discard=on,backup=0",
        )

    def test_disk_hardware_verification_requires_unowned_options(self) -> None:
        original = (
            "bulk:vm-112-disk-1,iothread=0,serial=it-data,size=64G,cache=none"
        )
        self.assertTrue(
            _disk_hardware_update_verified(
                original,
                "bulk:vm-112-disk-1,serial=it-data,size=64G,cache=none,"
                "iothread=1,discard=on,ssd=1",
                discard=True,
                ssd=True,
                backup=True,
            )
        )
        self.assertFalse(
            _disk_hardware_update_verified(
                original,
                "bulk:vm-112-disk-1,size=64G,cache=none,iothread=1,"
                "discard=on,ssd=1",
                discard=True,
                ssd=True,
                backup=True,
            )
        )
        self.assertFalse(
            _disk_hardware_update_verified(
                original,
                "other:vm-112-disk-1,serial=it-data,size=64G,cache=none,"
                "iothread=1,discard=on,ssd=1",
                discard=True,
                ssd=True,
                backup=True,
            )
        )

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

    def test_resolved_storage_pools_replace_auto_declarations(self) -> None:
        self.assertEqual(
            _storage_specs_with_resolved_pools(
                [
                    ["root", "auto", "32G"],
                    ["data", "auto", "64G"],
                    ["template", "local"],
                ],
                "fast-zfs",
                [VMDataDisk("data", "archive", "64G")],
            ),
            [
                ["root", "fast-zfs", "32G"],
                ["data", "archive", "64G"],
                ["template", "local"],
            ],
        )

    @patch("lib.proxmox_vm._ssh_run")
    def test_cpu_and_disk_hints_are_reconciled_and_verified(self, mock_run) -> None:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="VMID NAME STATUS\n112 agent-2 running\n"),
            MagicMock(
                returncode=0,
                stdout=(
                    "name: agent-2\ncpu: kvm64\n"
                    "scsi0: local-lvm:vm-112-disk-0,iothread=1,size=32G\n"
                    "scsi1: bulk:vm-112-disk-1,iothread=1,serial=it-data,size=64G\n"
                    "scsi2: manual:vm-112-disk-2,size=1T\n"
                    "ipconfig0: ip=10.0.0.50/24,gw=10.0.0.1\n"
                ),
            ),
            MagicMock(returncode=0, stdout="status: running\n"),
            MagicMock(returncode=0, stdout="READY\n"),
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(
                returncode=0,
                stdout=(
                    "name: agent-2\ncpu: x86-64-v2-AES\n"
                    "scsi0: local-lvm:vm-112-disk-0,iothread=1,size=32G,"
                    "discard=on,ssd=1\n"
                    "scsi1: bulk:vm-112-disk-1,iothread=1,serial=it-data,"
                    "size=64G,discard=on\n"
                    "scsi2: manual:vm-112-disk-2,size=1T\n"
                    "ipconfig0: ip=10.0.0.50/24,gw=10.0.0.1\n"
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
                desired_cpu_type="x86-64-v2-AES",
                desired_disk_hardware={
                    "root": VMDiskHardware("root", True, True),
                    "data": VMDiskHardware("data", True, False),
                },
                allow_managed_data_disks=True,
            )
        )

        commands = [call.args[3] for call in mock_run.call_args_list]
        self.assertIn("qm set 112 --cpu x86-64-v2-AES", commands)
        self.assertIn(
            "qm set 112 --scsi0 local-lvm:vm-112-disk-0,iothread=1,size=32G,"
            "discard=on,ssd=1",
            commands,
        )
        self.assertIn(
            "qm set 112 --scsi1 bulk:vm-112-disk-1,iothread=1,serial=it-data,"
            "size=64G,discard=on",
            commands,
        )
        self.assertFalse(any("--scsi2" in command for command in commands))

    @patch("lib.proxmox_vm._ssh_run")
    def test_unsaved_named_disks_are_rejected_before_mutation(self, mock_run) -> None:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="VMID NAME STATUS\n112 agent-2 running\n"),
            MagicMock(
                returncode=0,
                stdout=(
                    "name: agent-2\n"
                    "scsi0: local-lvm:vm-112-disk-0,size=32G\n"
                    "scsi1: bulk:vm-112-disk-1,serial=it-data,size=64G\n"
                    "ipconfig0: ip=10.0.0.50/24,gw=10.0.0.1\n"
                ),
            ),
            MagicMock(returncode=0, stdout="status: running\n"),
            MagicMock(returncode=0, stdout="READY\n"),
        ]

        with self.assertRaisesRegex(ProvisionError, "existing unsaved VM"):
            _reconcile_existing_vm(
                "10.0.0.1",
                "10.0.0.50",
                "agent-2",
                "root",
                [],
                desired_disk_hardware={
                    "root": VMDiskHardware("root", True, True),
                    "data": VMDiskHardware("data", True, False),
                },
            )

        self.assertEqual(len(mock_run.call_args_list), 2)
        self.assertFalse(
            any(
                call.args[3].startswith("qm set")
                for call in mock_run.call_args_list
            )
        )

    @patch("lib.proxmox_vm._ssh_run")
    def test_migrated_vm_bridge_and_storage_are_verified(self, mock_run) -> None:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="VMID NAME STATUS\n112 agent-2 running\n"),
            MagicMock(
                returncode=0,
                stdout=(
                    "name: agent-2\n"
                    "net0: virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr1\n"
                    "scsi0: fast-zfs:vm-112-disk-0,iothread=1,size=32G\n"
                    "scsi1: archive:vm-112-disk-1,iothread=1,serial=it-data,size=64G\n"
                    "ipconfig0: ip=10.0.0.50/24,gw=10.0.0.1\n"
                ),
            ),
            MagicMock(returncode=0, stdout="status: running\n"),
            MagicMock(returncode=0, stdout="READY\n"),
        ]

        self.assertTrue(
            _reconcile_existing_vm(
                "10.0.0.11",
                "10.0.0.50",
                "agent-2",
                "root",
                [],
                desired_disk_hardware={
                    "root": VMDiskHardware("root", False, False),
                    "data": VMDiskHardware("data", False, False),
                },
                desired_storage_layout={
                    "root": VMDataDisk("root", "fast-zfs", "32G"),
                    "data": VMDataDisk("data", "archive", "64G"),
                },
                desired_bridge="vmbr1",
                allow_managed_data_disks=True,
            )
        )

    @patch("lib.proxmox_vm._ssh_run")
    def test_migrated_vm_storage_mismatch_stops_before_mutation(self, mock_run) -> None:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="VMID NAME STATUS\n112 agent-2 running\n"),
            MagicMock(
                returncode=0,
                stdout=(
                    "name: agent-2\n"
                    "net0: virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr1\n"
                    "scsi0: local-lvm:vm-112-disk-0,size=32G\n"
                    "ipconfig0: ip=10.0.0.50/24,gw=10.0.0.1\n"
                ),
            ),
            MagicMock(returncode=0, stdout="status: running\n"),
            MagicMock(returncode=0, stdout="READY\n"),
        ]

        with self.assertRaisesRegex(ProvisionError, "uses storage 'local-lvm'"):
            _reconcile_existing_vm(
                "10.0.0.11",
                "10.0.0.50",
                "agent-2",
                "root",
                [],
                desired_disk_hardware={
                    "root": VMDiskHardware("root", False, False),
                },
                desired_storage_layout={
                    "root": VMDataDisk("root", "fast-zfs", "32G"),
                },
                allow_managed_data_disks=True,
            )

        self.assertFalse(
            any(call.args[3].startswith("qm set") for call in mock_run.call_args_list)
        )

    @patch("lib.proxmox_vm._ssh_run")
    def test_provider_rebind_requires_saved_destination_name(self, mock_run) -> None:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="VMID NAME STATUS\n112 copied-vm running\n"),
            MagicMock(
                returncode=0,
                stdout=(
                    "name: copied-vm\n"
                    "ipconfig0: ip=10.0.0.50/24,gw=10.0.0.1\n"
                ),
            ),
        ]

        with self.assertRaisesRegex(ProvisionError, "expected saved name 'agent-2'"):
            _reconcile_existing_vm(
                "10.0.0.11",
                "10.0.0.50",
                "agent-2",
                "root",
                [],
                require_existing_name=True,
            )

        self.assertEqual(len(mock_run.call_args_list), 2)

    @patch("lib.proxmox_vm._wait_for_guest_ssh")
    @patch("lib.proxmox_vm._ssh_run")
    def test_provider_rebind_starts_verified_stopped_destination(
        self,
        mock_run,
        mock_wait,
    ) -> None:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="VMID NAME STATUS\n112 agent-2 stopped\n"),
            MagicMock(
                returncode=0,
                stdout=(
                    "name: agent-2\n"
                    "ipconfig0: ip=10.0.0.50/24,gw=10.0.0.1\n"
                ),
            ),
            MagicMock(returncode=0, stdout="status: stopped\n"),
            MagicMock(returncode=0, stdout="", stderr=""),
        ]

        self.assertTrue(
            _reconcile_existing_vm(
                "10.0.0.11",
                "10.0.0.50",
                "agent-2",
                "root",
                [],
                require_existing=True,
                require_existing_name=True,
                start_existing=True,
            )
        )

        self.assertEqual(mock_run.call_args_list[3].args[3], "qm start 112")
        mock_wait.assert_called_once_with(
            "10.0.0.50",
            "10.0.0.11",
            "root",
            [],
            timeout=300,
            dry_run=False,
            label="Migrated VM",
        )

    @patch("lib.proxmox_vm._ssh_run")
    def test_provider_rebind_refuses_missing_destination(self, mock_run) -> None:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="VMID NAME STATUS\n",
        )

        with self.assertRaisesRegex(ProvisionError, "No VM matching saved name"):
            _reconcile_existing_vm(
                "10.0.0.11",
                "10.0.0.50",
                "agent-2",
                "root",
                [],
                require_existing=True,
                require_existing_name=True,
            )

        mock_run.assert_called_once()

    @patch("lib.proxmox_vm._ssh_run")
    def test_provider_rebind_requires_stopped_source_vm(self, mock_run) -> None:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="VMID NAME STATUS\n112 agent-2 running\n"),
            MagicMock(
                returncode=0,
                stdout=(
                    "name: agent-2\n"
                    "ipconfig0: ip=10.0.0.50/24,gw=10.0.0.1\n"
                ),
            ),
            MagicMock(returncode=0, stdout="status: running\n"),
        ]
        config = SetupConfig(
            host="10.0.0.50",
            username="agent",
            system_type="agent_code_vm",
            machine_type="vm",
            hosted_node="10.0.0.10",
            system_hostname="agent-2",
            static_ipv4="10.0.0.50/24",
        )

        with self.assertRaisesRegex(ProvisionError, "source VM 112.*not stopped"):
            verify_vm_rebind_source_stopped(config)

    @patch("lib.proxmox_vm._ssh_run")
    def test_provider_rebind_accepts_stopped_source_vm(self, mock_run) -> None:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="VMID NAME STATUS\n112 agent-2 stopped\n"),
            MagicMock(
                returncode=0,
                stdout=(
                    "name: agent-2\n"
                    "ipconfig0: ip=10.0.0.50/24,gw=10.0.0.1\n"
                ),
            ),
            MagicMock(returncode=0, stdout="status: stopped\n"),
        ]
        config = SetupConfig(
            host="10.0.0.50",
            username="agent",
            system_type="agent_code_vm",
            machine_type="vm",
            hosted_node="10.0.0.10",
            system_hostname="agent-2",
            static_ipv4="10.0.0.50/24",
        )

        verify_vm_rebind_source_stopped(config)

    @patch("lib.proxmox_vm._ssh_run")
    def test_provider_rebind_dry_run_does_not_contact_source(self, mock_run) -> None:
        config = SetupConfig(
            host="10.0.0.50",
            username="agent",
            system_type="agent_code_vm",
            machine_type="vm",
            hosted_node="10.0.0.10",
            system_hostname="agent-2",
            static_ipv4="10.0.0.50/24",
        )

        verify_vm_rebind_source_stopped(config, dry_run=True)

        mock_run.assert_not_called()


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

    def test_vm_hardware_changes_are_reconcilable(self) -> None:
        current = SetupConfig(
            host="10.0.0.50",
            username="agent",
            system_type="agent_code_vm",
            machine_type="vm",
            vm_cpu_type="x86-64-v2-AES",
            vm_disk_discard=False,
            vm_disk_ssd=True,
            vm_disk_settings=[["root", "ssd=on"]],
        )
        cached = SetupConfig(
            host="10.0.0.50",
            username="agent",
            system_type="agent_code_vm",
            machine_type="vm",
        )

        changes = infra_tools._unsupported_cached_provisioning_changes(
            current,
            cached,
            Namespace(
                vm_cpu_type="x86-64-v2-AES",
                vm_disk_discard=False,
                vm_disk_ssd=True,
                vm_disk_settings=[["root", "ssd=on"]],
            ),
        )

        self.assertEqual(changes, [])

    def test_existing_vm_storage_change_is_deferred_to_live_verification(self) -> None:
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

        self.assertEqual(changes, [])


if __name__ == "__main__":
    unittest.main()
