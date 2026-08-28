"""Failure-recovery and ownership tests for managed swap reconciliation."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, call, patch

from common.swap_steps import (
    SWAP_SCHEMA_VERSION,
    _active_swap_inventory,
    _ensure_swap_device,
    _load_state,
    _ownership_union,
    _reconcile_zram,
    _write_state,
    _zram_configuration,
    configure_swap,
)
from lib.config import SetupConfig
from lib.swap_config import SwapDevice, SwapFile, SwapZram


class TestSwapRuntimeSafety(unittest.TestCase):
    def _config(self, **overrides) -> SetupConfig:
        values = {
            "host": "vm",
            "username": "agent",
            "system_type": "agent_code_vm",
            "machine_type": "vm",
        }
        values.update(overrides)
        return SetupConfig(**values)

    @patch("common.swap_steps.run")
    def test_swap_inventory_raw_output_handles_paths_and_priorities(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="/swap path/file 20\n/dev/vdb 0\n",
        )

        self.assertEqual(
            _active_swap_inventory(),
            {"/swap path/file": 20, "/dev/vdb": 0},
        )
        self.assertNotIn("--json", mock_run.call_args.args[0])

    def test_legacy_provider_state_is_accepted_for_upgrade(self):
        state = {
            "schema": SWAP_SCHEMA_VERSION,
            "areas": [
                {
                    "name": "fast",
                    "type": "device",
                    "source": "swap-fast",
                    "path": "/dev/vdb",
                    "uuid": "11111111-1111",
                    "priority": 200,
                    "discard": "off",
                    "provider_owned": True,
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "swap.json")
            with open(path, "w", encoding="utf-8") as state_file:
                json.dump(state, state_file)
            with patch("common.swap_steps.SWAP_STATE_FILE", path):
                self.assertEqual(_load_state()["areas"], state["areas"])

    def test_state_loader_rejects_duplicate_device_identity(self):
        state = {
            "schema": SWAP_SCHEMA_VERSION,
            "areas": [
                {
                    "name": "fast",
                    "type": "device",
                    "source": "/dev/disk/by-id/one",
                    "path": "/dev/vdb",
                    "uuid": "11111111-1111",
                    "priority": 200,
                    "discard": "off",
                    "provider_owned": False,
                },
                {
                    "name": "duplicate",
                    "type": "device",
                    "source": "/dev/disk/by-id/two",
                    "path": "/dev/vdb",
                    "uuid": "22222222-2222",
                    "priority": 100,
                    "discard": "off",
                    "provider_owned": False,
                },
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "swap.json")
            with open(path, "w", encoding="utf-8") as state_file:
                json.dump(state, state_file)
            with patch("common.swap_steps.SWAP_STATE_FILE", path):
                with self.assertRaisesRegex(RuntimeError, "duplicate resource"):
                    _load_state()

    @patch("common.swap_steps.write_json_atomic")
    def test_state_writer_refuses_duplicate_resolved_devices(self, mock_write):
        first = {
            "name": "one",
            "type": "device",
            "source": "/dev/disk/by-id/one",
            "path": "/dev/vdb",
            "uuid": "11111111-1111",
            "priority": 100,
            "discard": "off",
            "provider_owned": False,
        }
        second = {
            **first,
            "name": "two",
            "source": "UUID=11111111-1111",
        }

        with self.assertRaisesRegex(RuntimeError, "duplicate resource"):
            _write_state([first, second])
        mock_write.assert_not_called()

    @patch("common.swap_steps._active_swap_inventory")
    @patch("common.swap_steps._swap_uuid", return_value="11111111-1111")
    @patch("common.swap_steps._wipefs_signatures", return_value=["swap"])
    @patch("common.swap_steps._has_mountpoint", return_value=False)
    @patch(
        "common.swap_steps._find_device_by_path",
        return_value={"path": "/dev/vdb", "children": [], "fstype": "swap"},
    )
    @patch("common.swap_steps._resolve_direct_device", return_value="/dev/vdb")
    def test_device_alias_collision_stops_before_swap_changes(
        self,
        _mock_resolve,
        _mock_find,
        _mock_mount,
        _mock_signatures,
        _mock_uuid,
        mock_inventory,
    ):
        claimed = {
            "name": "one",
            "type": "device",
            "source": "/dev/disk/by-id/one",
            "path": "/dev/vdb",
            "uuid": "11111111-1111",
            "priority": 100,
            "discard": "off",
            "provider_owned": False,
        }

        with self.assertRaisesRegex(RuntimeError, "same block device"):
            _ensure_swap_device(
                self._config(),
                SwapDevice("two", "UUID=11111111-1111"),
                None,
                [],
                [claimed],
            )
        mock_inventory.assert_not_called()

    def test_ownership_union_replaces_renamed_same_resource(self):
        old = {
            "name": "old",
            "type": "device",
            "source": "/dev/disk/by-id/stable",
            "path": "/dev/vdb",
            "uuid": "11111111-1111",
            "priority": 100,
        }
        new = {**old, "name": "new", "priority": 200}

        self.assertEqual(_ownership_union([new], [old]), [new])

    @patch("common.swap_steps._configure_resume")
    @patch("common.swap_steps._configure_zswap")
    @patch("common.swap_steps._configure_swappiness")
    @patch("common.swap_steps._replace_fstab")
    @patch("common.swap_steps._reconcile_zram", return_value=[])
    @patch("common.swap_steps._ensure_swap_file")
    @patch("common.swap_steps._write_state")
    @patch("common.swap_steps._active_swap", return_value=set())
    @patch("common.swap_steps._load_state")
    @patch("common.swap_steps.can_manage_swap", return_value=True)
    @patch("common.swap_steps.is_dry_run", return_value=False)
    def test_new_file_ownership_is_journaled_before_creation(
        self,
        _mock_dry_run,
        _mock_manage,
        mock_load,
        _mock_active,
        mock_write,
        mock_ensure,
        _mock_zram,
        _mock_fstab,
        _mock_swappiness,
        _mock_zswap,
        _mock_resume,
    ):
        mock_load.return_value = {"schema": SWAP_SCHEMA_VERSION, "areas": []}
        mock_ensure.return_value = {
            "name": "root",
            "type": "file",
            "source": "/managed-swap",
            "priority": 100,
            "size": "1G",
        }
        with patch("common.swap_steps.os.path.exists", return_value=False):
            configure_swap(
                self._config(swap_files=[["root", "/managed-swap", "1G"]])
            )

        first_state = mock_write.call_args_list[0].args[0]
        self.assertEqual(first_state[0]["source"], "/managed-swap")
        self.assertTrue(first_state[0]["pending"])
        mock_ensure.assert_called_once_with(
            SwapFile("root", "/managed-swap", "1G"),
            first_state[0],
        )

    @patch("common.swap_steps._configure_resume")
    @patch("common.swap_steps._configure_zswap")
    @patch("common.swap_steps._configure_swappiness")
    @patch("common.swap_steps._replace_fstab")
    @patch("common.swap_steps._reconcile_zram", return_value=[])
    @patch("common.swap_steps._remove_area")
    @patch("common.swap_steps._ensure_swap_device")
    @patch("common.swap_steps._write_state")
    @patch("common.swap_steps._active_swap", return_value=set())
    @patch("common.swap_steps._load_state")
    @patch("common.swap_steps.can_manage_swap", return_value=True)
    @patch("common.swap_steps.is_dry_run", return_value=False)
    def test_renamed_device_is_not_disabled_as_an_omitted_old_area(
        self,
        _mock_dry_run,
        _mock_manage,
        mock_load,
        _mock_active,
        _mock_write,
        mock_ensure,
        mock_remove,
        _mock_zram,
        _mock_fstab,
        _mock_swappiness,
        _mock_zswap,
        _mock_resume,
    ):
        source = "/dev/disk/by-id/scsi-stable"
        old = {
            "name": "old",
            "type": "device",
            "source": source,
            "path": "/dev/vdb",
            "uuid": "11111111-1111",
            "priority": 100,
            "discard": "off",
            "provider_owned": False,
        }
        new = {**old, "name": "new", "priority": 200}
        mock_load.return_value = {"schema": SWAP_SCHEMA_VERSION, "areas": [old]}
        mock_ensure.return_value = new
        config = self._config(swap_devices=[["new", source, "priority=200"]])

        configure_swap(config)

        mock_ensure.assert_called_once_with(
            config,
            SwapDevice("new", source, priority=200),
            old,
            [old],
            [],
        )
        mock_remove.assert_not_called()

    @patch("common.swap_steps._zram_device_busy", return_value=False)
    @patch("common.swap_steps._active_swap_inventory")
    @patch("common.swap_steps.run")
    def test_unchanged_zram_restarts_a_missing_owned_unit(
        self, mock_run, mock_inventory, _mock_busy
    ):
        area = SwapZram("fast", "1G", 300, "auto")
        old = {
            "name": "fast",
            "type": "zram",
            "source": "/dev/zram0",
            "priority": 300,
            "size": "1G",
            "algorithm": "auto",
        }
        mock_inventory.side_effect = [{}, {"/dev/zram0": 300}]
        with patch(
            "common.swap_steps.Path.read_text",
            return_value=_zram_configuration([area]),
        ):
            self.assertEqual(_reconcile_zram([area], [old]), [old])

        self.assertIn(
            call("systemctl start systemd-zram-setup@zram0.service"),
            mock_run.call_args_list,
        )

    @patch("common.swap_steps._zram_device_busy", return_value=False)
    @patch("common.swap_steps._active_swap_inventory")
    @patch("common.swap_steps.run")
    def test_unchanged_zram_repairs_live_priority_drift(
        self, mock_run, mock_inventory, _mock_busy
    ):
        area = SwapZram("fast", "1G", 300, "auto")
        old = {
            "name": "fast",
            "type": "zram",
            "source": "/dev/zram0",
            "priority": 300,
            "size": "1G",
            "algorithm": "auto",
        }
        mock_inventory.side_effect = [
            {"/dev/zram0": 10},
            {"/dev/zram0": 300},
        ]
        with patch(
            "common.swap_steps.Path.read_text",
            return_value=_zram_configuration([area]),
        ):
            self.assertEqual(_reconcile_zram([area], [old]), [old])

        self.assertIn(
            call("systemctl stop systemd-zram-setup@zram0.service", check=False),
            mock_run.call_args_list,
        )
        self.assertIn(
            call("systemctl start systemd-zram-setup@zram0.service"),
            mock_run.call_args_list,
        )

    @patch("common.swap_steps._zram_device_busy", return_value=True)
    @patch("common.swap_steps._active_swap_inventory", return_value={})
    def test_new_zram_refuses_an_unmanaged_busy_device(
        self, _mock_active, _mock_busy
    ):
        journal = MagicMock()
        with patch("common.swap_steps.Path.read_text", side_effect=FileNotFoundError):
            with self.assertRaisesRegex(RuntimeError, "unmanaged zram"):
                _reconcile_zram(
                    [SwapZram("fast", "1G")],
                    [],
                    journal_ownership=journal,
                )
        journal.assert_not_called()


if __name__ == "__main__":
    unittest.main()
