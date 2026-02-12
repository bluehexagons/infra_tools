"""Tests for lib/disk_utils.py: get_multiple_paths_usage and additional edge cases."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.disk_utils import get_multiple_paths_usage, check_disk_space_threshold


class TestGetMultiplePathsUsage(unittest.TestCase):
    def test_single_valid_path(self):
        results = get_multiple_paths_usage(['/'])
        self.assertIn('/', results)
        self.assertGreater(results['/']['total_mb'], 0)

    def test_multiple_paths(self):
        results = get_multiple_paths_usage(['/', '/tmp'])
        self.assertEqual(len(results), 2)
        self.assertIn('/', results)
        self.assertIn('/tmp', results)

    def test_invalid_path(self):
        results = get_multiple_paths_usage(['/nonexistent/path/xyz'])
        self.assertIn('/nonexistent/path/xyz', results)
        self.assertEqual(results['/nonexistent/path/xyz']['total_mb'], 0)

    def test_empty_list(self):
        results = get_multiple_paths_usage([])
        self.assertEqual(len(results), 0)


class TestCheckDiskSpaceThresholdCustom(unittest.TestCase):
    def _fake_usage(self, total, used, free):
        """Create a mock disk_usage result."""
        from collections import namedtuple
        Usage = namedtuple('usage', ['total', 'used', 'free'])
        return Usage(total, used, free)

    def test_ok_status(self):
        # 50% usage → ok
        with patch('shutil.disk_usage', return_value=self._fake_usage(1000, 500, 500)):
            status, pct = check_disk_space_threshold('/')
            self.assertEqual(status, 'ok')
            self.assertEqual(pct, 50)

    def test_warning_status(self):
        # 85% usage → warning (>=80, <90)
        with patch('shutil.disk_usage', return_value=self._fake_usage(1000, 850, 150)):
            status, pct = check_disk_space_threshold('/')
            self.assertEqual(status, 'warning')
            self.assertEqual(pct, 85)

    def test_critical_status(self):
        # 95% usage → critical (>=90)
        with patch('shutil.disk_usage', return_value=self._fake_usage(1000, 950, 50)):
            status, pct = check_disk_space_threshold('/')
            self.assertEqual(status, 'critical')
            self.assertEqual(pct, 95)


if __name__ == '__main__':
    unittest.main()
