"""Tests for storage_ops runtime helpers."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, mock_open, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from lib.runtime_config import RuntimeConfig
from sync.service_tools.storage_ops import (
    FREQUENCY_SECONDS,
    OperationLock,
    get_scrub_op_id,
    get_sync_op_id,
    is_operation_due,
    load_last_run,
    resolve_scrub_database_path,
    run_scrub,
    save_last_run,
    validate_mounts_for_operation,
)


class TestOperationLock(unittest.TestCase):
    @patch("sync.service_tools.storage_ops.os.makedirs")
    @patch("sync.service_tools.storage_ops.fcntl.flock", side_effect=OSError("busy"))
    @patch("sync.service_tools.storage_ops.open", new_callable=mock_open)
    def test_nonblocking_acquire_failure_closes_file(self, mock_file_open, _flock, _makedirs):
        lock = OperationLock("/run/lock/storage-ops.lock")
        acquired = lock.acquire(blocking=False)
        self.assertFalse(acquired)
        mock_file_open.assert_called_once_with("/run/lock/storage-ops.lock", "a+")
        mock_file_open.return_value.close.assert_called_once()
        self.assertIsNone(lock.lock_file)


class TestValidateMountsForOperation(unittest.TestCase):
    @patch("sync.service_tools.storage_ops.get_mount_ancestor", return_value=None)
    @patch("sync.service_tools.storage_ops.os.path.exists", return_value=True)
    def test_rejects_missing_mount_ancestor(self, _exists, _ancestor):
        config = RuntimeConfig(username="test", sync_specs=[], scrub_specs=[], notify_specs=[])
        valid, message = validate_mounts_for_operation(["/mnt/data/source"], config, "sync")
        self.assertFalse(valid)
        self.assertIn("No mounted filesystem found", message)


class TestRunScrub(unittest.TestCase):
    @patch("sync.service_tools.storage_ops.os.makedirs")
    def test_invalid_redundancy_returns_failure_tuple(self, _makedirs):
        logger = MagicMock()
        success, message = run_scrub("/mnt/data", "/mnt/data/.pardb", "abc%", True, logger)
        self.assertFalse(success)
        self.assertIn("Invalid redundancy value", message)
        logger.error.assert_called()


class TestGetSyncOpId(unittest.TestCase):
    def test_basic_format(self):
        op_id = get_sync_op_id("/mnt/source", "/mnt/dest")
        self.assertEqual(op_id, "sync:/mnt/source:/mnt/dest")

    def test_different_paths_produce_different_ids(self):
        id1 = get_sync_op_id("/a", "/b")
        id2 = get_sync_op_id("/c", "/d")
        self.assertNotEqual(id1, id2)

    def test_same_paths_produce_same_ids(self):
        id1 = get_sync_op_id("/mnt/data", "/backup/data")
        id2 = get_sync_op_id("/mnt/data", "/backup/data")
        self.assertEqual(id1, id2)


class TestGetScrubOpId(unittest.TestCase):
    def test_basic_format(self):
        op_id = get_scrub_op_id("/mnt/data", ".pardatabase")
        self.assertEqual(op_id, "scrub:/mnt/data:.pardatabase")

    def test_absolute_database_path(self):
        op_id = get_scrub_op_id("/mnt/data", "/mnt/data/.pardatabase")
        self.assertEqual(op_id, "scrub:/mnt/data:/mnt/data/.pardatabase")

    def test_relative_database_preserves_raw_value(self):
        """Op IDs must use the raw spec value, not a resolved path."""
        op_id = get_scrub_op_id("/mnt/data", ".pardatabase")
        self.assertIn(".pardatabase", op_id)
        self.assertNotIn("/mnt/data/.pardatabase", op_id)

    def test_different_directories_produce_different_ids(self):
        id1 = get_scrub_op_id("/mnt/data1", ".pardb")
        id2 = get_scrub_op_id("/mnt/data2", ".pardb")
        self.assertNotEqual(id1, id2)


class TestResolveScrubDatabasePath(unittest.TestCase):
    def test_relative_path_resolved_against_directory(self):
        result = resolve_scrub_database_path("/mnt/data", ".pardatabase")
        self.assertEqual(result, "/mnt/data/.pardatabase")

    def test_absolute_path_unchanged(self):
        result = resolve_scrub_database_path("/mnt/data", "/var/lib/pardb")
        self.assertEqual(result, "/var/lib/pardb")

    def test_relative_path_with_subdirectory(self):
        result = resolve_scrub_database_path("/mnt/data", "parity/db")
        self.assertEqual(result, "/mnt/data/parity/db")

    def test_normpath_applied(self):
        """Redundant separators and . components are normalized."""
        result = resolve_scrub_database_path("/mnt/data/", "./pardb")
        self.assertEqual(result, "/mnt/data/pardb")

    def test_dotdot_normalized(self):
        result = resolve_scrub_database_path("/mnt/data/subdir", "../pardb")
        self.assertEqual(result, "/mnt/data/pardb")


class TestIsOperationDue(unittest.TestCase):
    def test_never_run_is_due(self):
        self.assertTrue(is_operation_due({}, "sync:/a:/b", "hourly"))

    def test_recently_run_not_due(self):
        last_run = {"sync:/a:/b": time.time()}
        self.assertFalse(is_operation_due(last_run, "sync:/a:/b", "hourly"))

    def test_old_run_is_due(self):
        one_week_ago = time.time() - 604800 - 1
        last_run = {"sync:/a:/b": one_week_ago}
        self.assertTrue(is_operation_due(last_run, "sync:/a:/b", "daily"))

    def test_unknown_interval_defaults_to_hourly(self):
        """Unknown intervals fall back to hourly (3600s)."""
        two_hours_ago = time.time() - 7200
        last_run = {"op1": two_hours_ago}
        self.assertTrue(is_operation_due(last_run, "op1", "nonexistent_interval"))

    def test_unknown_op_id_is_due(self):
        last_run = {"sync:/a:/b": time.time()}
        self.assertTrue(is_operation_due(last_run, "sync:/c:/d", "hourly"))

    def test_all_known_intervals(self):
        """All named intervals are recognized and have positive values."""
        for name, seconds in FREQUENCY_SECONDS.items():
            self.assertGreater(seconds, 0, f"Interval {name} should be positive")
            # Just-expired should be due
            last_run = {"op": time.time() - seconds - 1}
            self.assertTrue(
                is_operation_due(last_run, "op", name),
                f"Operation should be due after {name} interval expires"
            )
            # Just-before-expiry should not be due
            last_run = {"op": time.time() - seconds + 60}
            self.assertFalse(
                is_operation_due(last_run, "op", name),
                f"Operation should not be due before {name} interval expires"
            )


class TestLoadLastRun(unittest.TestCase):
    def test_returns_empty_dict_when_file_missing(self):
        with patch("sync.service_tools.storage_ops.STATE_FILE", "/nonexistent/path.json"):
            result = load_last_run()
        self.assertEqual(result, {})

    def test_loads_valid_json(self):
        data = {"sync:/a:/b": 1234567890.0}
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(data, f)
            f.flush()
            temp_path = f.name
        try:
            with patch("sync.service_tools.storage_ops.STATE_FILE", temp_path):
                result = load_last_run()
            self.assertEqual(result, data)
        finally:
            os.unlink(temp_path)

    def test_returns_empty_dict_on_corrupt_json(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("not valid json{{{")
            f.flush()
            temp_path = f.name
        try:
            with patch("sync.service_tools.storage_ops.STATE_FILE", temp_path):
                result = load_last_run()
            self.assertEqual(result, {})
        finally:
            os.unlink(temp_path)


class TestSaveLastRun(unittest.TestCase):
    def test_saves_and_roundtrips(self):
        data = {"scrub:/data:.pardb": 1700000000.0, "sync:/a:/b": 1700001000.0}
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = os.path.join(tmpdir, "subdir", "last_run.json")
            with patch("sync.service_tools.storage_ops.STATE_FILE", state_path):
                save_last_run(data)
                # Verify the file exists and contains correct data
                with open(state_path, 'r') as f:
                    loaded = json.load(f)
                self.assertEqual(loaded, data)

    def test_creates_parent_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = os.path.join(tmpdir, "a", "b", "c", "state.json")
            with patch("sync.service_tools.storage_ops.STATE_FILE", state_path):
                save_last_run({"op": 123.0})
            self.assertTrue(os.path.exists(state_path))
            os.unlink(state_path)


class TestOpIdStability(unittest.TestCase):
    """Verify that op_id uses the raw database path, not the resolved one.

    This is critical: if the spec stores '.pardatabase' as a relative path,
    the op_id must be 'scrub:/data:.pardatabase' not 'scrub:/data:/data/.pardatabase'.
    Otherwise last_run.json state tracking breaks (previously completed operations
    appear as never-run because their IDs changed).
    """

    @patch("sync.service_tools.storage_ops.send_operation_notification")
    @patch("sync.service_tools.storage_ops.run_scrub", return_value=(True, "OK"))
    @patch("sync.service_tools.storage_ops.validate_mounts_for_operation", return_value=(True, ""))
    @patch("sync.service_tools.storage_ops.save_last_run")
    @patch("sync.service_tools.storage_ops.load_last_run", return_value={})
    @patch("sync.service_tools.storage_ops.parse_notification_args", return_value=[])
    @patch("sync.service_tools.storage_ops.load_setup_config")
    @patch("sync.service_tools.storage_ops.get_service_logger")
    def test_scrub_op_id_uses_raw_database_path(
        self, mock_logger, mock_load_config, _notif_args,
        _load_last, mock_save_last, _validate, mock_run_scrub, _send_notif
    ):
        """Op IDs saved to last_run.json must use raw (unresolved) database paths."""
        from sync.service_tools.storage_ops import execute_storage_operations

        mock_logger.return_value = MagicMock()
        mock_load_config.return_value = {
            "username": "test",
            "sync_specs": [],
            "scrub_specs": [["/data", ".pardatabase", "5%", "weekly"]],
            "notify_specs": [],
        }

        execute_storage_operations()

        # Verify save_last_run was called
        mock_save_last.assert_called_once()
        saved_state = mock_save_last.call_args[0][0]

        # The op_id must use the raw relative database path
        expected_op_id = "scrub:/data:.pardatabase"
        self.assertIn(expected_op_id, saved_state,
                      f"Expected op_id '{expected_op_id}' in saved state, got keys: {list(saved_state.keys())}")

        # The resolved path should NOT appear as an op_id
        wrong_op_id = "scrub:/data:/data/.pardatabase"
        self.assertNotIn(wrong_op_id, saved_state,
                         "Resolved path should not be used in op_id")

        # But run_scrub must receive the resolved path
        mock_run_scrub.assert_called()
        # First call is full scrub (verify=True), second is parity update (verify=False)
        for call in mock_run_scrub.call_args_list:
            database_arg = call[0][1]  # second positional arg is database
            self.assertEqual(database_arg, "/data/.pardatabase",
                            f"run_scrub should receive resolved path, got: {database_arg}")


if __name__ == "__main__":
    unittest.main()
