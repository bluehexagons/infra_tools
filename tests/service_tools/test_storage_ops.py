"""Tests for storage_ops runtime helpers."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, mock_open, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from lib.runtime_config import RuntimeConfig
from sync.service_tools.storage_ops import OperationLock, run_scrub, validate_mounts_for_operation


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


if __name__ == "__main__":
    unittest.main()
