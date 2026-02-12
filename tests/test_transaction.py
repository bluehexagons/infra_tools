"""Tests for lib/transaction.py: Transaction execution, rollback, checkpoints."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.operation_log import OperationLogger
from lib.transaction import Transaction, TransactionManager


class TestTransaction(unittest.TestCase):
    def _make_transaction(self, tmpdir, timeout_seconds=3600):
        log_file = os.path.join(tmpdir, 'tx.log')
        logger = OperationLogger('tx-001', log_file)
        return Transaction('tx-001', logger, timeout_seconds=timeout_seconds)

    def test_initial_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tx = self._make_transaction(tmpdir)
            self.assertEqual(tx.status, 'pending')

    def test_execute_single_step(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tx = self._make_transaction(tmpdir)
            executed = []
            tx.add_step(lambda: executed.append('run'), lambda: None, 'test step')
            result = tx.execute()
            self.assertTrue(result)
            self.assertEqual(tx.status, 'completed')
            self.assertEqual(executed, ['run'])

    def test_execute_multiple_steps(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tx = self._make_transaction(tmpdir)
            order = []
            tx.add_step(lambda: order.append('a'), lambda: None, 'step a')
            tx.add_step(lambda: order.append('b'), lambda: None, 'step b')
            tx.add_step(lambda: order.append('c'), lambda: None, 'step c')
            result = tx.execute()
            self.assertTrue(result)
            self.assertEqual(order, ['a', 'b', 'c'])

    def test_execute_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tx = self._make_transaction(tmpdir)
            tx.add_step(lambda: None, lambda: None, 'ok step')
            tx.add_step(lambda: (_ for _ in ()).throw(RuntimeError('fail')), lambda: None, 'bad step')
            result = tx.execute()
            self.assertFalse(result)
            self.assertEqual(tx.status, 'failed')

    def test_execute_continue_on_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tx = self._make_transaction(tmpdir)
            executed = []
            tx.add_step(lambda: (_ for _ in ()).throw(RuntimeError('fail')), lambda: None, 'bad step')
            tx.add_step(lambda: executed.append('after'), lambda: None, 'after step')
            result = tx.execute(continue_on_error=True)
            self.assertTrue(result)
            self.assertIn('after', executed)

    def test_rollback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tx = self._make_transaction(tmpdir)
            rollback_order = []
            tx.add_step(lambda: None, lambda: rollback_order.append('rb_a'), 'step a')
            tx.add_step(lambda: None, lambda: rollback_order.append('rb_b'), 'step b')
            tx.execute()
            result = tx.rollback('test rollback')
            self.assertTrue(result)
            # Rollback in reverse order
            self.assertEqual(rollback_order, ['rb_b', 'rb_a'])
            self.assertEqual(tx.status, 'rolled_back')

    def test_rollback_only_completed_steps(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tx = self._make_transaction(tmpdir)
            rollback_order = []
            tx.add_step(lambda: None, lambda: rollback_order.append('rb_a'), 'step a')
            def fail_step():
                raise RuntimeError('fail')
            tx.add_step(fail_step, lambda: rollback_order.append('rb_b'), 'step b')
            tx.execute()
            tx.rollback('failure')
            # Only step a was completed, so only its rollback runs
            self.assertEqual(rollback_order, ['rb_a'])

    def test_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tx = self._make_transaction(tmpdir)
            tx.add_step(lambda: None, lambda: None, 'step 1')
            tx.create_checkpoint('cp1')
            self.assertIn('cp1', tx.checkpoints)

    def test_rollback_to_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tx = self._make_transaction(tmpdir)
            rollback_order = []
            tx.add_step(lambda: None, lambda: rollback_order.append('rb_a'), 'step a', name='a')
            tx.create_checkpoint('cp1')
            tx.add_step(lambda: None, lambda: rollback_order.append('rb_b'), 'step b', name='b')
            tx.execute()
            result = tx.rollback_to_checkpoint('cp1')
            self.assertTrue(result)
            # Steps from checkpoint_index onward are rolled back in reverse order
            self.assertEqual(rollback_order, ['rb_b', 'rb_a'])

    def test_rollback_to_missing_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tx = self._make_transaction(tmpdir)
            result = tx.rollback_to_checkpoint('nonexistent')
            self.assertFalse(result)

    def test_add_validation_step(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tx = self._make_transaction(tmpdir)
            validated = []
            tx.add_validation_step(lambda: validated.append(True), 'validate')
            result = tx.execute()
            self.assertTrue(result)
            self.assertEqual(validated, [True])

    def test_get_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tx = self._make_transaction(tmpdir)
            tx.add_step(lambda: None, lambda: None, 'step 1')
            tx.execute()
            status = tx.get_status()
            self.assertEqual(status['status'], 'completed')
            self.assertEqual(status['total_steps'], 1)
            self.assertEqual(status['completed_steps'], 1)
            self.assertEqual(status['failed_steps'], 0)

    def test_get_step_details(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tx = self._make_transaction(tmpdir)
            tx.add_step(lambda: None, lambda: None, 'step 1', name='s1')
            tx.execute()
            details = tx.get_step_details()
            self.assertEqual(len(details), 1)
            self.assertEqual(details[0]['name'], 's1')
            self.assertTrue(details[0]['completed'])


class TestTransactionManager(unittest.TestCase):
    def _make_logger(self, tmpdir):
        log_file = os.path.join(tmpdir, 'mgr.log')
        return OperationLogger('mgr-001', log_file)

    def test_create_and_get(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = TransactionManager()
            logger = self._make_logger(tmpdir)
            tx = manager.create_transaction('op1', logger)
            self.assertIs(manager.get_transaction('op1'), tx)

    def test_get_missing(self):
        manager = TransactionManager()
        self.assertIsNone(manager.get_transaction('missing'))

    def test_complete_transaction(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = TransactionManager()
            logger = self._make_logger(tmpdir)
            manager.create_transaction('op1', logger)
            manager.complete_transaction('op1')
            self.assertIsNone(manager.get_transaction('op1'))

    def test_active_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = TransactionManager()
            logger = self._make_logger(tmpdir)
            manager.create_transaction('op1', logger)
            manager.create_transaction('op2', logger)
            self.assertEqual(manager.get_active_transaction_count(), 2)

    def test_cleanup_stalled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = TransactionManager()
            logger = self._make_logger(tmpdir)
            tx = manager.create_transaction('op1', logger)
            # Simulate old transaction
            tx.transaction_start_time -= 7200  # 2 hours ago
            tx.status = 'pending'
            cleaned = manager.cleanup_stalled_transactions(max_age_seconds=3600)
            self.assertEqual(cleaned, 1)
            self.assertIsNone(manager.get_transaction('op1'))


if __name__ == '__main__':
    unittest.main()
