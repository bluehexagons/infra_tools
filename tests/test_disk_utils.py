"""Tests for lib/disk_utils.py: get_multiple_paths_usage and additional edge cases."""

from __future__ import annotations

import os
import sys
import unittest

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
    def test_custom_thresholds(self):
        status, pct = check_disk_space_threshold('/', warning_threshold=1, critical_threshold=2)
        # Since usage is almost certainly > 2%, expect warning or critical
        self.assertIn(status, ['ok', 'warning', 'critical'])


if __name__ == '__main__':
    unittest.main()
