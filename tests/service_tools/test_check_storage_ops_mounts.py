"""Tests for check_storage_ops_mounts.py script."""

from __future__ import annotations

import io
import logging
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from sync.service_tools.check_storage_ops_mounts import check_mount, main


class TestCheckStorageOpsMounts(unittest.TestCase):
    def make_logger(self, name: str) -> logging.Logger:
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = False
        logger.addHandler(logging.StreamHandler(io.StringIO()))
        logger.setLevel(logging.INFO)
        return logger

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
            result = main(['/mnt/data', '/mnt/backup'], logger=self.make_logger('test.check_storage_ops_mounts.argv_success'))
            self.assertEqual(result, 0)

    def test_main_returns_1_when_mount_not_available(self):
        """Test that main returns 1 when any mount is not available."""
        def mock_ismount(path):
            return path == '/mnt/data'
        
        with patch('os.path.ismount', side_effect=mock_ismount):
            result = main(['/mnt/data', '/mnt/backup'], logger=self.make_logger('test.check_storage_ops_mounts.argv_failure'))
            self.assertEqual(result, 1)

    def test_main_returns_1_when_no_args(self):
        """Test that main returns 1 when no mount points are specified."""
        result = main([], logger=self.make_logger('test.check_storage_ops_mounts.argv_usage'))
        self.assertEqual(result, 1)

    def test_main_logs_success_with_structured_context(self):
        log_stream = io.StringIO()
        logger = self.make_logger('test.check_storage_ops_mounts.success')
        logger.handlers = [logging.StreamHandler(log_stream)]

        with patch('os.path.ismount', return_value=True):
            result = main(['/mnt/data', '/mnt/backup'], logger=logger)

        self.assertEqual(result, 0)
        output = log_stream.getvalue()
        self.assertIn('All mount points available', output)
        self.assertIn('mount_count=2', output)

    def test_main_logs_missing_mount_with_structured_context(self):
        log_stream = io.StringIO()
        logger = self.make_logger('test.check_storage_ops_mounts.failure')
        logger.handlers = [logging.StreamHandler(log_stream)]

        def mock_ismount(path):
            return path == '/mnt/data'

        with patch('os.path.ismount', side_effect=mock_ismount):
            result = main(['/mnt/data', '/mnt/backup'], logger=logger)

        self.assertEqual(result, 1)
        output = log_stream.getvalue()
        self.assertIn('Mount point unavailable', output)
        self.assertIn("mount_point='/mnt/backup'", output)

    def test_main_logs_usage_error_with_structured_context(self):
        log_stream = io.StringIO()
        logger = self.make_logger('test.check_storage_ops_mounts.usage')
        logger.handlers = [logging.StreamHandler(log_stream)]

        result = main([], logger=logger)

        self.assertEqual(result, 1)
        output = log_stream.getvalue()
        self.assertIn('Mount check invocation missing arguments', output)


if __name__ == '__main__':
    unittest.main()
