"""Tests for fail-closed VM data-disk setup."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import call, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from common import storage_steps
from lib.config import SetupConfig
from lib.vm_storage import VMStorageMount


def _result(*, returncode: int = 0, stdout: str = "", stderr: str = ""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


class TestDiskIdentity(unittest.TestCase):
    @patch("common.storage_steps._lsblk")
    def test_requires_exactly_one_matching_serial(self, mock_lsblk):
        mock_lsblk.return_value = [
            {"type": "disk", "serial": "it-data", "size": 2 * 1024**3},
            {"type": "disk", "serial": "it-data", "size": 2 * 1024**3},
        ]

        with self.assertRaisesRegex(RuntimeError, "exactly one.*found 2"):
            storage_steps._find_declared_disk("it-data", "1G")

    @patch("common.storage_steps._lsblk")
    def test_rejects_disk_smaller_than_declaration(self, mock_lsblk):
        mock_lsblk.return_value = [
            {"type": "disk", "serial": "it-data", "size": 1024**3},
        ]

        with self.assertRaisesRegex(RuntimeError, "smaller than declared"):
            storage_steps._find_declared_disk("it-data", "2G")


class TestDiskPreparationSafety(unittest.TestCase):
    @patch("common.storage_steps._wipefs_signatures", return_value=["ext4"])
    def test_refuses_signatures_on_unpartitioned_disk(self, _signatures):
        disk = {
            "path": "/dev/sdb",
            "type": "disk",
            "size": 2 * 1024**3,
            "serial": "it-data",
            "children": [],
        }

        with self.assertRaisesRegex(RuntimeError, "signatures found: ext4"):
            storage_steps._partition_for_mount(disk, "it-data", "2G")

    @patch("common.storage_steps._lsblk")
    def test_refuses_existing_wrong_filesystem(self, mock_lsblk):
        mock_lsblk.return_value = [
            {
                "type": "disk",
                "children": [
                    {
                        "type": "part",
                        "path": "/dev/sdb1",
                        "fstype": "xfs",
                    }
                ],
            }
        ]

        with self.assertRaisesRegex(RuntimeError, "contains xfs, expected ext4"):
            storage_steps._ensure_filesystem("/dev/sdb1", "ext4")

    @patch("common.storage_steps._run_capture")
    def test_findmnt_parent_mount_is_not_accepted(self, mock_run):
        mock_run.return_value = _result(
            stdout=json.dumps(
                {
                    "filesystems": [
                        {"source": "/dev/sda1", "fstype": "ext4", "target": "/"}
                    ]
                }
            )
        )

        self.assertIsNone(storage_steps._mounted_info("/srv/data"))

    @patch("common.storage_steps._run_capture")
    def test_rejects_uuid_unsafe_for_systemd_unit(self, mock_run):
        mock_run.return_value = _result(stdout="valid-looking%specifier\n")

        with self.assertRaisesRegex(RuntimeError, "filesystem UUID"):
            storage_steps._filesystem_uuid("/dev/sdb1")


class TestPrepareMount(unittest.TestCase):
    def test_nonempty_mount_path_is_rejected_before_disk_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            with open(os.path.join(directory, "existing"), "w", encoding="utf-8") as file_obj:
                file_obj.write("preserve")
            mount = VMStorageMount("agent-data", directory, "ext4", "empty")
            with (
                patch("common.storage_steps._mounted_info", return_value=None),
                patch("common.storage_steps._find_declared_disk") as find_disk,
                patch("common.storage_steps._partition_for_mount") as partition,
            ):
                with self.assertRaisesRegex(RuntimeError, "must be empty"):
                    storage_steps._prepare_mount(
                        mount,
                        "64G",
                        "it-agent-data",
                        "scsi1",
                    )

            find_disk.assert_not_called()
            partition.assert_not_called()

    def test_writes_native_mount_unit_and_marker_after_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            mount = VMStorageMount("agent-data", directory, "ext4", "empty")
            mounted = ("/dev/sdb1", "ext4")
            with (
                patch("common.storage_steps._find_declared_disk", return_value={}),
                patch(
                    "common.storage_steps._partition_for_mount",
                    return_value="/dev/sdb1",
                ),
                patch(
                    "common.storage_steps._ensure_filesystem",
                    return_value="filesystem-uuid",
                ),
                patch(
                    "common.storage_steps._mounted_info",
                    side_effect=[None, mounted],
                ),
                patch(
                    "common.storage_steps._filesystem_uuid",
                    return_value="filesystem-uuid",
                ),
                patch(
                    "common.storage_steps._systemd_mount_unit",
                    return_value="srv-agent.mount",
                ),
                patch("common.storage_steps._run_capture") as mock_run,
                patch("common.storage_steps.write_text_atomic") as mock_text,
                patch("common.storage_steps.write_json_atomic") as mock_json,
            ):
                record = storage_steps._prepare_mount(
                    mount,
                    "64G",
                    "it-agent-data",
                    "scsi1",
                )

        unit_path, unit_text = mock_text.call_args.args[:2]
        self.assertEqual(unit_path, "/etc/systemd/system/srv-agent.mount")
        self.assertIn("What=/dev/disk/by-uuid/filesystem-uuid", unit_text)
        self.assertIn(f"Where={directory}", unit_text)
        self.assertNotIn("nofail", unit_text)
        mock_run.assert_has_calls(
            [
                call("systemctl daemon-reload"),
                call("systemctl enable --now srv-agent.mount"),
            ]
        )
        self.assertEqual(
            mock_json.call_args.args[0],
            os.path.join(directory, storage_steps.STORAGE_MARKER),
        )
        self.assertEqual(record["uuid"], "filesystem-uuid")
        self.assertEqual(record["bus_slot"], "scsi1")

    def test_rerun_verifies_existing_mount_before_rewriting_unit(self):
        with tempfile.TemporaryDirectory() as directory:
            mount = VMStorageMount("git-data", directory, "xfs", "empty")
            mounted = ("/dev/sdc1", "xfs")
            with (
                patch(
                    "common.storage_steps._find_declared_disk",
                    return_value={"children": [{"type": "part"}]},
                ),
                patch(
                    "common.storage_steps._partition_for_mount",
                    return_value="/dev/sdc1",
                ),
                patch(
                    "common.storage_steps._ensure_filesystem",
                    return_value="existing-uuid",
                ),
                patch(
                    "common.storage_steps._mounted_info",
                    side_effect=[mounted, mounted, mounted],
                ),
                patch(
                    "common.storage_steps._filesystem_uuid",
                    return_value="existing-uuid",
                ),
                patch(
                    "common.storage_steps._systemd_mount_unit",
                    return_value="srv-git.mount",
                ),
                patch("common.storage_steps._run_capture"),
                patch("common.storage_steps.write_text_atomic"),
                patch("common.storage_steps.write_json_atomic"),
            ):
                storage_steps._prepare_mount(
                    mount,
                    "128G",
                    "it-git-data",
                    "scsi2",
                )


class TestDeclaredMountAssertion(unittest.TestCase):
    def test_application_write_requires_matching_active_mount(self):
        with tempfile.TemporaryDirectory() as directory:
            marker_path = os.path.join(directory, storage_steps.STORAGE_MARKER)
            with open(marker_path, "w", encoding="utf-8") as file_obj:
                json.dump({"name": "agent-data", "uuid": "data-uuid"}, file_obj)
            config = SetupConfig(
                host="host",
                username="agent",
                system_type="workstation_dev",
                storage_mounts=[["agent-data", directory]],
            )

            with patch("common.storage_steps._verify_active_mount") as verify:
                storage_steps.assert_declared_storage_mount(
                    config,
                    os.path.join(directory, "repos"),
                )

        verify.assert_called_once_with(
            VMStorageMount("agent-data", directory, "ext4", "empty"),
            "data-uuid",
        )

    def test_missing_marker_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            config = SetupConfig(
                host="host",
                username="git",
                system_type="server_web",
                storage_mounts=[["git-data", directory]],
            )

            with self.assertRaisesRegex(RuntimeError, "marker is missing"):
                storage_steps.assert_declared_storage_mount(config, directory)


if __name__ == "__main__":
    unittest.main()
