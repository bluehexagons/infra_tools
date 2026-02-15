"""Tests for check_storage_ops_mounts.py script."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from sync.service_tools.check_storage_ops_mounts import check_mount, main


class TestCheckStorageOpsMounts(unittest.TestCase):
    def test_check_mount_returns_true_when_mounted(self):
        """Test that check_mount returns True when path is a mount point."""
        with patch('os.path.ismount', return_value=True):
            result = check_mount('/mnt/data')
            self.assertTrue(result)

    def test_check_mount_returns_false_when_not_mounted(self):
        """Test that check_mount returns False when path is not a mount point."""
        with patch('os.path.ismount', return_value=False):
            result = check_mount('/not/a/mount')
            self.assertFalse(result)

    def test_main_returns_0_when_all_mounts_available(self):
        """Test that main returns 0 when all specified mounts are available."""
        with patch('os.path.ismount', return_value=True):
            with patch.object(sys, 'argv', ['check_storage_ops_mounts.py', '/mnt/data', '/mnt/backup']):
                result = main()
                self.assertEqual(result, 0)

    def test_main_returns_1_when_mount_not_available(self):
        """Test that main returns 1 when any mount is not available."""
        def mock_ismount(path):
            return path == '/mnt/data'
        
        with patch('os.path.ismount', side_effect=mock_ismount):
            with patch.object(sys, 'argv', ['check_storage_ops_mounts.py', '/mnt/data', '/mnt/backup']):
                result = main()
                self.assertEqual(result, 1)

    def test_main_returns_1_when_no_args(self):
        """Test that main returns 1 when no mount points are specified."""
        with patch.object(sys, 'argv', ['check_storage_ops_mounts.py']):
            result = main()
            self.assertEqual(result, 1)


if __name__ == '__main__':
    unittest.main()
