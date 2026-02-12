"""Tests for lib/operation_log.py: OperationLogger and OperationLoggerManager."""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.operation_log import (
    OperationLogger,
    OperationLoggerManager,
    set_operation_logger_manager,
)


class TestOperationLogger(unittest.TestCase):
    def _make_logger(self, tmpdir):
        op_id = f'test-op-{uuid.uuid4().hex[:8]}'
        log_file = os.path.join(tmpdir, f'{op_id}.log')
        return OperationLogger(op_id, log_file)

    def test_initial_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = self._make_logger(tmpdir)
            self.assertEqual(logger.status, 'running')
            self.assertIsNone(logger.current_step)

    def test_log_step(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = self._make_logger(tmpdir)
            logger.log_step('step1', 'started', 'First step')
            self.assertEqual(logger.current_step, 'step1')

    def test_create_and_get_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = self._make_logger(tmpdir)
            logger.create_checkpoint('cp1', {'files_processed': 100})
            cp = logger.get_checkpoint('cp1')
            self.assertIsNotNone(cp)
            self.assertEqual(cp['state']['files_processed'], 100)

    def test_get_missing_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = self._make_logger(tmpdir)
            self.assertIsNone(logger.get_checkpoint('missing'))

    def test_get_all_checkpoints(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = self._make_logger(tmpdir)
            logger.create_checkpoint('cp1', {'a': 1})
            logger.create_checkpoint('cp2', {'b': 2})
            cps = logger.get_all_checkpoints()
            self.assertEqual(len(cps), 2)
            self.assertIn('cp1', cps)
            self.assertIn('cp2', cps)

    def test_log_rollback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = self._make_logger(tmpdir)
            logger.create_checkpoint('cp1', {'state': 'ok'})
            logger.log_rollback('cp1', 'test failure')
            self.assertEqual(logger.status, 'rolled_back')

    def test_log_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = self._make_logger(tmpdir)
            logger.log_error('RuntimeError', 'something broke')
            # Should not change status
            self.assertEqual(logger.status, 'running')

    def test_log_warning(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = self._make_logger(tmpdir)
            logger.log_warning('disk space low')
            self.assertEqual(logger.status, 'running')

    def test_log_metric(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = self._make_logger(tmpdir)
            logger.log_metric('files_processed', 42, unit='files')
            # No exception = success

    def test_complete(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = self._make_logger(tmpdir)
            logger.complete('completed', summary='All done')
            self.assertEqual(logger.status, 'completed')

    def test_complete_failed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = self._make_logger(tmpdir)
            logger.complete('failed')
            self.assertEqual(logger.status, 'failed')

    def test_get_operation_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = self._make_logger(tmpdir)
            summary = logger.get_operation_summary()
            self.assertEqual(summary['operation_id'], logger.operation_id)
            self.assertEqual(summary['status'], 'running')
            self.assertIn('elapsed_time_seconds', summary)

    def test_log_context_public(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = self._make_logger(tmpdir)
            logger.log_context('custom_event', {'key': 'value'})
            # Should not raise


class TestOperationLoggerManager(unittest.TestCase):
    def test_create_logger(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = OperationLoggerManager(tmpdir)
            logger = manager.create_logger('sync', source='/mnt/a')
            self.assertIsNotNone(logger)
            self.assertEqual(logger.status, 'running')

    def test_get_logger(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = OperationLoggerManager(tmpdir)
            logger = manager.create_logger('sync')
            retrieved = manager.get_logger(logger.operation_id)
            self.assertIs(retrieved, logger)

    def test_get_missing_logger(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = OperationLoggerManager(tmpdir)
            self.assertIsNone(manager.get_logger('missing'))

    def test_complete_logger(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = OperationLoggerManager(tmpdir)
            logger = manager.create_logger('sync')
            op_id = logger.operation_id
            manager.complete_logger(op_id)
            self.assertIsNone(manager.get_logger(op_id))
            self.assertEqual(logger.status, 'completed')

    def test_get_active_operations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = OperationLoggerManager(tmpdir)
            manager.create_logger('sync')
            manager.create_logger('scrub')
            active = manager.get_active_operations()
            self.assertEqual(len(active), 2)

    def test_cleanup_old_logs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = OperationLoggerManager(tmpdir)
            # Create an old log file
            old_log = os.path.join(tmpdir, 'old_sync.log')
            with open(old_log, 'w') as f:
                f.write('old log')
            # Set mtime to 60 days ago
            old_time = time.time() - (60 * 24 * 60 * 60)
            os.utime(old_log, (old_time, old_time))
            cleaned = manager.cleanup_old_logs(days_to_keep=30)
            self.assertEqual(cleaned, 1)
            self.assertFalse(os.path.exists(old_log))

    def test_cleanup_keeps_recent_logs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = OperationLoggerManager(tmpdir)
            recent_log = os.path.join(tmpdir, 'recent.log')
            with open(recent_log, 'w') as f:
                f.write('recent log')
            cleaned = manager.cleanup_old_logs(days_to_keep=30)
            self.assertEqual(cleaned, 0)
            self.assertTrue(os.path.exists(recent_log))


class TestSetOperationLoggerManager(unittest.TestCase):
    def test_set_to_none(self):
        set_operation_logger_manager(None)
        # Should not raise


if __name__ == '__main__':
    unittest.main()
