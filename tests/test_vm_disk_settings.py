"""Validation tests for per-device Proxmox disk hardware settings."""

from __future__ import annotations

from types import SimpleNamespace
import unittest

from lib.validation import validate_vm_storage_settings


class TestVMDiskSettingsValidation(unittest.TestCase):
    def _config(self, **overrides):
        values = {
            "container_storage": [
                ["root", "local-lvm", "32G"],
                ["archive", "bulk-lvm", "2T"],
            ],
            "storage_mounts": [["archive", "/srv/archive", "ext4"]],
            "storage_caches": None,
            "swap_devices": None,
            "vm_disk_settings": [
                ["root", "ssd=on"],
                ["archive", "discard=off", "ssd=off"],
            ],
            "hosted_node": "pve1",
            "machine_type": "vm",
            "agent_workspace": None,
            "username": "agent",
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_accepts_root_and_named_disk_overrides(self):
        validate_vm_storage_settings(
            self._config(),
            require_provisioning=True,
        )

    def test_rejects_unknown_disk_override(self):
        with self.assertRaisesRegex(ValueError, "unknown VM disk 'missing'"):
            validate_vm_storage_settings(
                self._config(vm_disk_settings=[["missing", "ssd=on"]]),
                require_provisioning=True,
            )

    def test_rejects_invalid_or_duplicate_settings(self):
        with self.assertRaisesRegex(ValueError, r"discard=on\|off"):
            validate_vm_storage_settings(
                self._config(vm_disk_settings=[["root", "ssd=yes"]]),
                require_provisioning=True,
            )
        with self.assertRaisesRegex(ValueError, "Duplicate ssd setting"):
            validate_vm_storage_settings(
                self._config(
                    vm_disk_settings=[["root", "ssd=on", "ssd=off"]]
                ),
                require_provisioning=True,
            )

    def test_requires_vm_provisioning(self):
        with self.assertRaisesRegex(ValueError, "require --provision-on"):
            validate_vm_storage_settings(
                self._config(hosted_node=None),
                require_provisioning=True,
            )
        with self.assertRaisesRegex(ValueError, "require --machine vm"):
            validate_vm_storage_settings(
                self._config(machine_type="unprivileged"),
                require_provisioning=True,
            )

    def test_swap_disk_needs_no_mount_and_cannot_be_backed_up(self):
        config = self._config(
            storage_mounts=None,
            swap_devices=[["bulk", "archive", "priority=10"]],
            vm_disk_settings=[["archive", "backup=off"]],
        )
        validate_vm_storage_settings(config, require_provisioning=True)

        with self.assertRaisesRegex(ValueError, "cannot be included"):
            validate_vm_storage_settings(
                self._config(
                    storage_mounts=None,
                    swap_devices=[["bulk", "archive"]],
                    vm_disk_settings=[["archive", "backup=on"]],
                ),
                require_provisioning=True,
            )

    def test_swap_disk_cannot_also_be_mounted(self):
        with self.assertRaisesRegex(ValueError, "must not use --storage-mount"):
            validate_vm_storage_settings(
                self._config(swap_devices=[["bulk", "archive"]]),
                require_provisioning=True,
            )


if __name__ == "__main__":
    unittest.main()
