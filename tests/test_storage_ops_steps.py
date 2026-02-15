"""Tests for sync/storage_ops_steps.py."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.config import SetupConfig
from sync.storage_ops_steps import generate_mount_check_condition


class TestGenerateMountCheckCondition(unittest.TestCase):
    @patch("lib.task_utils.get_mount_ancestor", return_value=None)
    def test_includes_derived_mnt_mountpoint_when_unmounted(self, _ancestor):
        config = SetupConfig(
            host="test",
            username="test",
            system_type="server_lite",
            sync_specs=[["/mnt/data/source", "/home/test/backup", "daily"]],
            scrub_specs=[],
        )
        condition = generate_mount_check_condition(config)
        self.assertIn("ExecCondition=", condition)
        self.assertIn("/mnt/data", condition)


if __name__ == "__main__":
    unittest.main()
