"""Tests for lib/progress.py: progress bar, step registration, and execution."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.progress import (
    progress_bar,
    register_step,
    get_total_steps,
    clear_steps,
    run_step,
    run_all_steps,
)


class TestProgressBar(unittest.TestCase):
    def test_zero_progress(self):
        bar = progress_bar(0, 10)
        self.assertIn('0%', bar)

    def test_full_progress(self):
        bar = progress_bar(10, 10)
        self.assertIn('100%', bar)

    def test_half_progress(self):
        bar = progress_bar(5, 10)
        self.assertIn('50%', bar)

    def test_zero_total(self):
        bar = progress_bar(0, 0)
        self.assertIn('0%', bar)

    def test_custom_width(self):
        bar = progress_bar(5, 10, width=40)
        self.assertIn('50%', bar)


class TestStepRegistration(unittest.TestCase):
    def setUp(self):
        clear_steps()

    def tearDown(self):
        clear_steps()

    def test_register_step(self):
        register_step('test_step', lambda: None)
        self.assertEqual(get_total_steps(), 1)

    def test_register_multiple_steps(self):
        register_step('step1', lambda: None)
        register_step('step2', lambda: None)
        register_step('step3', lambda: None)
        self.assertEqual(get_total_steps(), 3)

    def test_clear_steps(self):
        register_step('step1', lambda: None)
        clear_steps()
        self.assertEqual(get_total_steps(), 0)


class TestRunStep(unittest.TestCase):
    def setUp(self):
        clear_steps()

    def tearDown(self):
        clear_steps()

    def test_run_step_calls_function(self):
        called = []
        def step_func():
            called.append(True)

        register_step('test', step_func)
        run_step(1, 'test', step_func)
        self.assertEqual(len(called), 1)

    def test_run_step_returns_result(self):
        def step_func():
            return 42

        register_step('test', step_func)
        result = run_step(1, 'test', step_func)
        self.assertEqual(result, 42)


class TestRunAllSteps(unittest.TestCase):
    def setUp(self):
        clear_steps()

    def tearDown(self):
        clear_steps()

    def test_run_all_steps(self):
        executed = []
        register_step('s1', lambda: executed.append('s1'))
        register_step('s2', lambda: executed.append('s2'))
        register_step('s3', lambda: executed.append('s3'))
        run_all_steps()
        self.assertEqual(executed, ['s1', 's2', 's3'])


if __name__ == '__main__':
    unittest.main()
