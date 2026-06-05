"""Tests for the repository test runner."""

from __future__ import annotations

import contextlib
import io
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import run_tests


class TestRunTestsSuites(unittest.TestCase):
    def test_named_suites_are_available(self) -> None:
        self.assertIn("smoke", run_tests.TEST_SUITES)
        self.assertIn("proxmox", run_tests.TEST_SUITES)
        self.assertIn("all", run_tests.TEST_SUITES)

    def test_build_named_suite(self) -> None:
        loader = unittest.TestLoader()
        suite = run_tests._build_suite(loader, [], ["smoke"])
        self.assertGreater(suite.countTestCases(), 0)

    def test_list_suites_output(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = run_tests.main(["--list-suites"])
        self.assertEqual(rc, 0)
        output = stdout.getvalue()
        self.assertIn("smoke", output)
        self.assertIn("proxmox", output)


class TestRunTestsExpensivePrereqs(unittest.TestCase):
    def test_all_expands_to_known_prereq_categories(self) -> None:
        categories = run_tests._requested_prereq_categories(["all"])
        self.assertIn("live_proxmox", categories)

    def test_live_proxmox_prereq_check_reports_missing_env(self) -> None:
        stdout = io.StringIO()
        with _env_unset("PROXMOX_TEST_HOST"), \
             _env_unset("PROXMOX_TEST_IP"), \
             contextlib.redirect_stdout(stdout):
            rc = run_tests.main(["--check-prereqs", "--expensive", "live_proxmox"])
        self.assertEqual(rc, 2)
        output = stdout.getvalue()
        self.assertIn("live_proxmox", output)
        self.assertIn("PROXMOX_TEST_HOST", output)
        self.assertIn("PROXMOX_TEST_IP", output)

    def test_live_proxmox_lxc_prereq_check_requires_template(self) -> None:
        stdout = io.StringIO()
        with patch.dict(os.environ, {"PROXMOX_TEST_GUEST_TYPE": "lxc"}), \
             _env_unset("PROXMOX_TEST_HOST"), \
             _env_unset("PROXMOX_TEST_TEMPLATE"), \
             contextlib.redirect_stdout(stdout):
            rc = run_tests.main(["--check-prereqs", "--expensive", "live_proxmox"])
        self.assertEqual(rc, 2)
        output = stdout.getvalue()
        self.assertIn("live_proxmox", output)
        self.assertIn("PROXMOX_TEST_HOST", output)
        self.assertIn("PROXMOX_TEST_TEMPLATE", output)


class TestRunTestsDurations(unittest.TestCase):
    def test_duration_output_can_be_requested(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = run_tests.main(["--durations", "1", "test_expensive_support"])
        self.assertEqual(rc, 0)
        self.assertIn("Slowest 1 tests:", stdout.getvalue())


class _env_unset:
    def __init__(self, key: str) -> None:
        self.key = key
        self._previous: object = None

    def __enter__(self) -> None:
        self._previous = os.environ.get(self.key)
        os.environ.pop(self.key, None)

    def __exit__(self, *exc) -> None:
        if self._previous is not None:
            os.environ[self.key] = str(self._previous)


if __name__ == "__main__":
    unittest.main()
