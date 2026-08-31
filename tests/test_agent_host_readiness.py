"""Tests for resource-aware agent host diagnostics."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from lib.agent_cli import (
    _directory_size_bytes,
    _maintenance_status,
    _read_memory_capacity_bytes,
    _read_meminfo,
    inspect_host_readiness,
)
from lib.types import BYTES_PER_GB, BYTES_PER_MB


class _DiskUsage:
    def __init__(self, total: int, used: int, free: int) -> None:
        self.total = total
        self.used = used
        self.free = free


class TestAgentHostReadiness(unittest.TestCase):
    def test_maintenance_includes_installed_development_timers_only(self) -> None:
        def properties(
            unit: str,
            _properties: tuple[str, ...],
            *,
            user: bool = False,
        ) -> dict[str, str]:
            self.assertFalse(user)
            if unit.startswith("auto-update-godot"):
                return {"LoadState": "not-found"}
            if unit == "auto-update-node.timer":
                return {
                    "LoadState": "loaded",
                    "ActiveState": "active",
                    "UnitFileState": "enabled",
                }
            if unit == "auto-update-node.service":
                return {
                    "LoadState": "loaded",
                    "ActiveState": "failed",
                    "Result": "failed",
                    "ExecMainStatus": "1",
                }
            if unit.endswith(".timer"):
                return {
                    "LoadState": "loaded",
                    "ActiveState": "active",
                    "UnitFileState": "enabled",
                }
            return {
                "LoadState": "loaded",
                "ActiveState": "inactive",
                "Result": "success",
                "ExecMainStatus": "0",
            }

        with patch("lib.agent_cli._systemd_properties", side_effect=properties):
            result = _maintenance_status()

        self.assertIn("auto-update-node", result["units"])
        self.assertNotIn("auto-update-godot", result["units"])
        self.assertIn("auto-update-node maintenance last failed", result["errors"])

    def test_read_meminfo_converts_kibibytes_to_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "meminfo")
            with open(path, "w", encoding="utf-8") as file_obj:
                file_obj.write(
                    "MemTotal:       2097152 kB\n"
                    "MemAvailable:    524288 kB\n"
                    "SwapTotal:      1048576 kB\n"
                    "SwapFree:        786432 kB\n"
                )

            values = _read_meminfo(path)

        self.assertEqual(values["MemTotal"], 2 * BYTES_PER_GB)
        self.assertEqual(values["MemAvailable"], 512 * BYTES_PER_MB)
        self.assertEqual(
            values["SwapTotal"] - values["SwapFree"],
            256 * BYTES_PER_MB,
        )

    def test_directory_inventory_does_not_follow_links(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = os.path.join(temp_dir, "root")
            outside = os.path.join(temp_dir, "outside")
            os.mkdir(root)
            os.mkdir(outside)
            with open(os.path.join(root, "local"), "wb") as file_obj:
                file_obj.write(b"1234")
            with open(os.path.join(outside, "large"), "wb") as file_obj:
                file_obj.write(b"x" * 100)
            os.symlink(outside, os.path.join(root, "linked"))

            self.assertEqual(_directory_size_bytes(root), 4)

    def test_memory_capacity_includes_ballooned_sysfs_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with open(
                os.path.join(temp_dir, "block_size_bytes"),
                "w",
                encoding="utf-8",
            ) as file_obj:
                file_obj.write("8000000\n")
            for index in range(32):
                os.mkdir(os.path.join(temp_dir, f"memory{index}"))

            capacity = _read_memory_capacity_bytes(temp_dir)

        self.assertEqual(capacity, 4 * BYTES_PER_GB)

    def test_ballooned_guest_uses_capacity_for_memory_recommendation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            meminfo_path = os.path.join(temp_dir, "meminfo")
            memory_path = os.path.join(temp_dir, "memory")
            os.mkdir(memory_path)
            with open(meminfo_path, "w", encoding="utf-8") as file_obj:
                file_obj.write(
                    "MemTotal:       2097152 kB\n"
                    "MemAvailable:   1048576 kB\n"
                )
            with open(
                os.path.join(memory_path, "block_size_bytes"),
                "w",
                encoding="utf-8",
            ) as file_obj:
                file_obj.write("8000000\n")
            for index in range(32):
                os.mkdir(os.path.join(memory_path, f"memory{index}"))

            with (
                patch("lib.agent_cli._agent_storage_inventory") as storage,
                patch("lib.agent_cli._systemd_properties", return_value={}),
                patch("lib.agent_cli.shutil.disk_usage") as disk_usage,
                patch("lib.agent_cli.inspect_agent_maintenance") as maintenance,
            ):
                storage.return_value = {
                    "paths": {},
                    "size_bytes": {},
                    "codex_release_count": 0,
                }
                disk_usage.return_value = _DiskUsage(
                    32 * BYTES_PER_GB,
                    8 * BYTES_PER_GB,
                    24 * BYTES_PER_GB,
                )
                maintenance.return_value = {"status": "inactive"}
                result = inspect_host_readiness(
                    temp_dir,
                    meminfo_path=meminfo_path,
                    memory_sysfs_path=memory_path,
                )

        self.assertEqual(result["memory"]["total_bytes"], 2 * BYTES_PER_GB)
        self.assertEqual(result["memory"]["capacity_bytes"], 4 * BYTES_PER_GB)
        self.assertTrue(result["memory"]["ballooned"])
        self.assertNotIn(
            "memory is below the 4 GiB recommendation for T3 Code with browser or build workloads",
            result["warnings"],
        )

    def test_kernel_reserved_memory_is_not_reported_as_ballooning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            meminfo_path = os.path.join(temp_dir, "meminfo")
            memory_path = os.path.join(temp_dir, "memory")
            os.mkdir(memory_path)
            with open(meminfo_path, "w", encoding="utf-8") as file_obj:
                file_obj.write(
                    "MemTotal:       4050000 kB\n"
                    "MemAvailable:   3000000 kB\n"
                )
            with open(
                os.path.join(memory_path, "block_size_bytes"),
                "w",
                encoding="utf-8",
            ) as file_obj:
                file_obj.write("8000000\n")
            for index in range(32):
                os.mkdir(os.path.join(memory_path, f"memory{index}"))

            with (
                patch("lib.agent_cli._agent_storage_inventory") as storage,
                patch("lib.agent_cli._systemd_properties", return_value={}),
                patch("lib.agent_cli.shutil.disk_usage") as disk_usage,
                patch("lib.agent_cli.inspect_agent_maintenance") as maintenance,
            ):
                storage.return_value = {
                    "paths": {},
                    "size_bytes": {},
                    "codex_release_count": 0,
                }
                disk_usage.return_value = _DiskUsage(
                    32 * BYTES_PER_GB,
                    8 * BYTES_PER_GB,
                    24 * BYTES_PER_GB,
                )
                maintenance.return_value = {"status": "inactive"}
                result = inspect_host_readiness(
                    temp_dir,
                    meminfo_path=meminfo_path,
                    memory_sysfs_path=memory_path,
                )

        self.assertFalse(result["memory"]["ballooned"])

    def test_host_diagnostic_separates_warnings_from_critical_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            meminfo_path = os.path.join(temp_dir, "meminfo")
            with open(meminfo_path, "w", encoding="utf-8") as file_obj:
                file_obj.write(
                    "MemTotal:       2097152 kB\n"
                    "MemAvailable:    262144 kB\n"
                    "SwapTotal:      1048576 kB\n"
                    "SwapFree:        524288 kB\n"
                )

            def properties(
                unit: str,
                _properties: tuple[str, ...],
                *,
                user: bool = False,
            ) -> dict[str, str]:
                if user:
                    return {
                        "MemoryCurrent": str(1800 * BYTES_PER_MB),
                        "MemoryPeak": str(3 * BYTES_PER_GB),
                        "TasksCurrent": "40",
                    }
                if unit.endswith(".timer"):
                    return {
                        "LoadState": "loaded",
                        "ActiveState": "active",
                        "UnitFileState": "enabled",
                        "NextElapseUSecRealtime": "Fri 2026-08-28 03:00:00 CDT",
                    }
                return {
                    "LoadState": "loaded",
                    "ActiveState": "inactive",
                    "Result": "success",
                    "ExecMainStatus": "0",
                }

            storage = {
                "paths": {},
                "size_bytes": {
                    "npm_cache": 3 * BYTES_PER_GB,
                    "browser_cache": 0,
                    "t3_logs": 0,
                    "codex_packages": 0,
                    "workspace": 0,
                },
                "codex_release_count": 3,
            }
            disk = _DiskUsage(
                32 * BYTES_PER_GB,
                31 * BYTES_PER_GB,
                BYTES_PER_GB,
            )
            with (
                patch(
                    "lib.agent_cli._agent_storage_inventory",
                    return_value=storage,
                ),
                patch("lib.agent_cli._systemd_properties", side_effect=properties),
                patch("lib.agent_cli.shutil.disk_usage", return_value=disk),
                patch("lib.agent_cli.os.path.exists", return_value=False),
            ):
                result = inspect_host_readiness(
                    temp_dir,
                    meminfo_path=meminfo_path,
                    memory_sysfs_path=os.path.join(temp_dir, "missing-memory"),
                )

        self.assertFalse(result["healthy"])
        self.assertEqual(result["status"], "error")
        self.assertIn(
            "agent filesystem has critical free-space pressure",
            result["errors"],
        )
        self.assertIn(
            "memory is below the 4 GiB recommendation for T3 Code with browser or build workloads",
            result["warnings"],
        )
        self.assertIn(
            "npm_cache exceeds its diagnostic size threshold",
            result["warnings"],
        )
        self.assertIn(
            "more than two Codex standalone releases are retained",
            result["warnings"],
        )


if __name__ == "__main__":
    unittest.main()
