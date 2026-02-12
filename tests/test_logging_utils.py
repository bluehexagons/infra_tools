"""Tests for lib/logging_utils.py: rotating logger, service logger, log messaging."""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.logging_utils import (
    get_standard_formatter,
    get_rotating_logger,
    get_service_logger,
    log_message,
    ensure_log_directory,
    STANDARD_LOG_FORMAT,
    DEFAULT_LOG_MAX_BYTES,
)


class TestGetStandardFormatter(unittest.TestCase):
    def test_returns_formatter(self):
        fmt = get_standard_formatter()
        self.assertIsInstance(fmt, logging.Formatter)

    def test_format_string(self):
        fmt = get_standard_formatter()
        self.assertIn('%(asctime)s', fmt._fmt)
        self.assertIn('%(levelname)', fmt._fmt)


class TestGetRotatingLogger(unittest.TestCase):
    def test_creates_logger(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, 'test.log')
            logger = get_rotating_logger('test_logger_1', log_file)
            self.assertIsInstance(logger, logging.Logger)
            self.assertTrue(len(logger.handlers) > 0)

    def test_idempotent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, 'test.log')
            logger1 = get_rotating_logger('test_logger_idempotent', log_file)
            handler_count = len(logger1.handlers)
            logger2 = get_rotating_logger('test_logger_idempotent', log_file)
            self.assertEqual(len(logger2.handlers), handler_count)

    def test_writes_to_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, 'test.log')
            logger = get_rotating_logger('test_logger_write', log_file)
            logger.info('test message')
            # Flush handlers
            for h in logger.handlers:
                h.flush()
            with open(log_file, 'r') as f:
                content = f.read()
            self.assertIn('test message', content)

    def test_fallback_on_bad_path(self):
        # /proc is not writable, so the logger should fallback to stderr
        logger = get_rotating_logger('test_logger_fallback', '/proc/nonexistent/test.log')
        self.assertIsInstance(logger, logging.Logger)
        # Should have a fallback handler
        self.assertTrue(len(logger.handlers) > 0)


class TestLogMessage(unittest.TestCase):
    def test_log_message(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, 'test.log')
            logger = get_rotating_logger('test_log_msg', log_file)
            log_message(logger, 'hello world')
            for h in logger.handlers:
                h.flush()
            with open(log_file, 'r') as f:
                content = f.read()
            self.assertIn('hello world', content)


class TestEnsureLogDirectory(unittest.TestCase):
    def test_creates_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = os.path.join(tmpdir, 'logs', 'sub')
            with unittest.mock.patch('lib.logging_utils.DEFAULT_LOG_DIR', os.path.join(tmpdir, 'logs')):
                result = ensure_log_directory('sub')
                self.assertTrue(result.exists())

    def test_no_subdir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with unittest.mock.patch('lib.logging_utils.DEFAULT_LOG_DIR', os.path.join(tmpdir, 'logs')):
                result = ensure_log_directory()
                self.assertTrue(result.exists())


if __name__ == '__main__':
    unittest.main()
