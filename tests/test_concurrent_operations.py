"""Tests for lib/concurrent_operations.py: concurrent operation coordination."""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, mock_open, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.concurrent_operations import (
    OperationType,
    OperationPriority,
    ResourceRequirement,
    Operation,
    MemoryMonitor,
    SimpleLockManager,
    OperationQueue,
    ConcurrentOperationManager,
    get_operation_manager,
    _operation_manager,
)
from lib.operation_log import OperationLogger
from lib.types import BYTES_PER_KB, BYTES_PER_MB


def _make_logger(tmpdir: str) -> OperationLogger:
    """Create a real OperationLogger in a temp directory."""
    log_file = os.path.join(tmpdir, 'test_op.log')
    return OperationLogger('test-op', log_file)


def _make_operation(
    tmpdir: str,
    op_id: str = 'op-1',
    op_type: OperationType = OperationType.SYNC,
    priority: OperationPriority = OperationPriority.NORMAL,
    memory_mb: int = 64,
    paths: list[str] | None = None,
    callback=None,
) -> Operation:
    """Create an Operation with sensible defaults for testing."""
    logger = _make_logger(tmpdir)
    return Operation(
        id=op_id,
        type=op_type,
        priority=priority,
        resource_req=ResourceRequirement(memory_mb=memory_mb, cpu_percent=10.0),
        paths=paths or ['/tmp/test_path'],
        callback=callback or (lambda: None),
        logger=logger,
    )


# ---------------------------------------------------------------------------
# Enums and dataclasses
# ---------------------------------------------------------------------------

class TestEnums(unittest.TestCase):
    def test_operation_types(self):
        self.assertEqual(OperationType.SYNC.value, 'sync')
        self.assertEqual(OperationType.SCRUB.value, 'scrub')
        self.assertEqual(OperationType.BACKUP.value, 'backup')

    def test_priority_ordering(self):
        self.assertLess(OperationPriority.LOW.value, OperationPriority.NORMAL.value)
        self.assertLess(OperationPriority.NORMAL.value, OperationPriority.HIGH.value)
        self.assertLess(OperationPriority.HIGH.value, OperationPriority.CRITICAL.value)


class TestResourceRequirement(unittest.TestCase):
    def test_defaults(self):
        req = ResourceRequirement(memory_mb=128, cpu_percent=25.0)
        self.assertEqual(req.io_weight, 1)
        self.assertTrue(req.can_share_resources)

    def test_custom_values(self):
        req = ResourceRequirement(memory_mb=256, cpu_percent=50.0, io_weight=3, can_share_resources=False)
        self.assertEqual(req.memory_mb, 256)
        self.assertFalse(req.can_share_resources)


class TestOperation(unittest.TestCase):
    def test_duration_not_started(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            op = _make_operation(tmpdir)
            self.assertIsNone(op.duration)

    def test_duration_started_not_completed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            op = _make_operation(tmpdir)
            op.started_at = time.time()
            self.assertIsNone(op.duration)

    def test_duration_completed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            op = _make_operation(tmpdir)
            op.started_at = 100.0
            op.completed_at = 105.5
            self.assertAlmostEqual(op.duration, 5.5)  # type: ignore[arg-type]  # duration is Optional[float]

    def test_created_at_auto_set(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            before = time.time()
            op = _make_operation(tmpdir)
            after = time.time()
            self.assertGreaterEqual(op.created_at, before)
            self.assertLessEqual(op.created_at, after)


# ---------------------------------------------------------------------------
# MemoryMonitor
# ---------------------------------------------------------------------------

class TestMemoryMonitor(unittest.TestCase):
    def _mock_meminfo(self, available_kb: int):
        content = (
            f"MemTotal:       8000000 kB\n"
            f"MemFree:        1000000 kB\n"
            f"MemAvailable:   {available_kb} kB\n"
            f"Buffers:         100000 kB\n"
        )
        return patch('builtins.open', mock_open(read_data=content))

    def test_get_available_memory(self):
        with self._mock_meminfo(2000000):
            monitor = MemoryMonitor()
            self.assertEqual(monitor.get_available_memory(), 2000000 * BYTES_PER_KB)

    def test_get_available_memory_unreadable(self):
        with patch('builtins.open', side_effect=IOError("no /proc")):
            monitor = MemoryMonitor()
            self.assertEqual(monitor.get_available_memory(), 0)

    def test_memory_pressure_normal(self):
        # 2 GB available — well above default thresholds
        with self._mock_meminfo(2000000):
            monitor = MemoryMonitor(warning_threshold_mb=512, critical_threshold_mb=256)
            self.assertEqual(monitor.get_memory_pressure_level(), 'normal')

    def test_memory_pressure_warning(self):
        # 400 MB available — between warning (512) and critical (256)
        with self._mock_meminfo(400 * 1024):
            monitor = MemoryMonitor(warning_threshold_mb=512, critical_threshold_mb=256)
            self.assertEqual(monitor.get_memory_pressure_level(), 'warning')

    def test_memory_pressure_critical(self):
        # 100 MB available — below critical (256)
        with self._mock_meminfo(100 * 1024):
            monitor = MemoryMonitor(warning_threshold_mb=512, critical_threshold_mb=256)
            self.assertEqual(monitor.get_memory_pressure_level(), 'critical')

    def test_can_allocate_memory_yes(self):
        # 2 GB available, requesting 100 MB, critical at 256 MB
        with self._mock_meminfo(2000000):
            monitor = MemoryMonitor(critical_threshold_mb=256)
            self.assertTrue(monitor.can_allocate_memory(100))

    def test_can_allocate_memory_no(self):
        # 300 MB available, requesting 100 MB, critical at 256 MB
        # After allocation: 200 MB < 256 MB critical
        with self._mock_meminfo(300 * 1024):
            monitor = MemoryMonitor(critical_threshold_mb=256)
            self.assertFalse(monitor.can_allocate_memory(100))


# ---------------------------------------------------------------------------
# SimpleLockManager
# ---------------------------------------------------------------------------

class TestSimpleLockManager(unittest.TestCase):
    def test_acquire_and_release(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SimpleLockManager(lock_dir=tmpdir)
            self.assertTrue(mgr.acquire_lock('resource-a'))
            mgr.release_lock('resource-a')

    def test_acquire_same_resource_twice_returns_true(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SimpleLockManager(lock_dir=tmpdir)
            self.assertTrue(mgr.acquire_lock('resource-a'))
            # Already held by us
            self.assertTrue(mgr.acquire_lock('resource-a'))
            mgr.release_lock('resource-a')

    def test_release_unknown_resource_no_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SimpleLockManager(lock_dir=tmpdir)
            mgr.release_lock('never-locked')  # Should not raise

    def test_check_locked_returns_true_when_held(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SimpleLockManager(lock_dir=tmpdir)
            mgr.acquire_lock('resource-b')
            self.assertTrue(mgr.check_locked('resource-b'))
            mgr.release_lock('resource-b')

    def test_check_locked_returns_false_when_released(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SimpleLockManager(lock_dir=tmpdir)
            mgr.acquire_lock('resource-c')
            mgr.release_lock('resource-c')
            self.assertFalse(mgr.check_locked('resource-c'))

    def test_check_locked_nonexistent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SimpleLockManager(lock_dir=tmpdir)
            self.assertFalse(mgr.check_locked('no-such'))

    def test_shared_lock(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SimpleLockManager(lock_dir=tmpdir)
            self.assertTrue(mgr.acquire_lock('shared-r', exclusive=False))
            mgr.release_lock('shared-r')

    def test_exclusive_lock_blocks_second_manager(self):
        """Two separate lock managers simulating two processes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr1 = SimpleLockManager(lock_dir=tmpdir)
            mgr2 = SimpleLockManager(lock_dir=tmpdir)

            self.assertTrue(mgr1.acquire_lock('contested'))
            # Second manager should fail to acquire (LOCK_NB = non-blocking)
            self.assertFalse(mgr2.acquire_lock('contested'))

            mgr1.release_lock('contested')
            # Now second manager should succeed
            self.assertTrue(mgr2.acquire_lock('contested'))
            mgr2.release_lock('contested')

    def test_lock_dir_created_automatically(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_dir = os.path.join(tmpdir, 'sub', 'locks')
            mgr = SimpleLockManager(lock_dir=lock_dir)
            self.assertTrue(os.path.isdir(lock_dir))
            self.assertTrue(mgr.acquire_lock('auto-dir'))
            mgr.release_lock('auto-dir')


# ---------------------------------------------------------------------------
# OperationQueue
# ---------------------------------------------------------------------------

class TestOperationQueue(unittest.TestCase):
    def test_enqueue_dequeue(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            q = OperationQueue(max_size=10)
            op = _make_operation(tmpdir, op_id='q-1')
            self.assertTrue(q.enqueue(op))
            result = q.dequeue()
            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result.id, 'q-1')

    def test_enqueue_duplicate_id_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            q = OperationQueue(max_size=10)
            op1 = _make_operation(tmpdir, op_id='dup')
            op2 = _make_operation(tmpdir, op_id='dup')
            self.assertTrue(q.enqueue(op1))
            self.assertFalse(q.enqueue(op2))

    def test_enqueue_over_max_size(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            q = OperationQueue(max_size=2)
            self.assertTrue(q.enqueue(_make_operation(tmpdir, op_id='a')))
            self.assertTrue(q.enqueue(_make_operation(tmpdir, op_id='b')))
            self.assertFalse(q.enqueue(_make_operation(tmpdir, op_id='c')))

    def test_priority_ordering(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            q = OperationQueue(max_size=10)
            q.enqueue(_make_operation(tmpdir, op_id='low', priority=OperationPriority.LOW))
            q.enqueue(_make_operation(tmpdir, op_id='high', priority=OperationPriority.HIGH))
            q.enqueue(_make_operation(tmpdir, op_id='normal', priority=OperationPriority.NORMAL))

            first = q.dequeue()
            second = q.dequeue()
            third = q.dequeue()
            assert first is not None and second is not None and third is not None
            self.assertEqual(first.id, 'high')
            self.assertEqual(second.id, 'normal')
            self.assertEqual(third.id, 'low')

    def test_size(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            q = OperationQueue(max_size=10)
            self.assertEqual(q.size(), 0)
            q.enqueue(_make_operation(tmpdir, op_id='s1'))
            self.assertEqual(q.size(), 1)

    def test_peek(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            q = OperationQueue(max_size=10)
            self.assertIsNone(q.peek())
            op = _make_operation(tmpdir, op_id='peek-1')
            q.enqueue(op)
            peeked = q.peek()
            self.assertIsNotNone(peeked)
            assert peeked is not None
            self.assertEqual(peeked.id, 'peek-1')
            # Peek should not remove
            self.assertEqual(q.size(), 1)

    def test_remove(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            q = OperationQueue(max_size=10)
            q.enqueue(_make_operation(tmpdir, op_id='rm-1'))
            q.enqueue(_make_operation(tmpdir, op_id='rm-2'))
            self.assertTrue(q.remove('rm-1'))
            self.assertEqual(q.size(), 1)
            self.assertFalse(q.remove('rm-1'))  # Already removed

    def test_remove_nonexistent(self):
        q = OperationQueue(max_size=10)
        self.assertFalse(q.remove('no-such'))

    def test_get_queue_info(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            q = OperationQueue(max_size=10)
            q.enqueue(_make_operation(tmpdir, op_id='i1', priority=OperationPriority.HIGH))
            q.enqueue(_make_operation(tmpdir, op_id='i2', priority=OperationPriority.LOW))
            info = q.get_queue_info()
            self.assertEqual(info['size'], 2)
            self.assertEqual(info['max_size'], 10)
            self.assertIn('HIGH', info['priorities'])
            self.assertIn('LOW', info['priorities'])

    def test_get_queue_info_empty(self):
        q = OperationQueue(max_size=5)
        info = q.get_queue_info()
        self.assertEqual(info['size'], 0)
        self.assertEqual(info['oldest_age'], 0)

    def test_max_size_property(self):
        q = OperationQueue(max_size=42)
        self.assertEqual(q.max_size, 42)

    def test_shutdown_unblocks_dequeue(self):
        """dequeue() should return None after shutdown."""
        q = OperationQueue(max_size=10)
        result = [None]

        def dequeue_thread():
            result[0] = q.dequeue()  # type: ignore[call-overload]  # dequeue returns Operation | None

        t = threading.Thread(target=dequeue_thread, daemon=True)
        t.start()
        time.sleep(0.1)
        q.shutdown()
        t.join(timeout=3.0)
        self.assertFalse(t.is_alive())
        self.assertIsNone(result[0])

    def test_enqueue_after_shutdown_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            q = OperationQueue(max_size=10)
            q.shutdown()
            self.assertFalse(q.enqueue(_make_operation(tmpdir, op_id='late')))


# ---------------------------------------------------------------------------
# ConcurrentOperationManager
# ---------------------------------------------------------------------------

class TestConcurrentOperationManager(unittest.TestCase):
    """Test the main coordinator.

    We use max_concurrent=1 and mock the memory monitor to avoid
    reading /proc/meminfo on systems where it may not exist.
    """

    def _make_manager(self, tmpdir, max_concurrent=1):
        lock_dir = os.path.join(tmpdir, 'locks')
        mgr = ConcurrentOperationManager(
            max_concurrent=max_concurrent,
            memory_warning_mb=512,
            memory_critical_mb=256,
            lock_dir=lock_dir,
        )
        # Mock memory monitor to always report normal
        mgr.memory_monitor = MagicMock()
        mgr.memory_monitor.get_memory_pressure_level.return_value = 'normal'
        mgr.memory_monitor.can_allocate_memory.return_value = True
        mgr.memory_monitor.get_available_memory.return_value = 4 * BYTES_PER_MB * 1024
        return mgr

    def test_submit_and_execute(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = self._make_manager(tmpdir)
            executed = threading.Event()

            def work():
                executed.set()

            logger = _make_logger(tmpdir)
            success = mgr.submit_operation(
                operation_id='exec-1',
                operation_type=OperationType.SYNC,
                priority=OperationPriority.NORMAL,
                resource_req=ResourceRequirement(memory_mb=64, cpu_percent=10.0),
                paths=[os.path.join(tmpdir, 'path-a')],
                callback=work,
                logger=logger,
            )
            self.assertTrue(success)
            executed.wait(timeout=5.0)
            self.assertTrue(executed.is_set())
            mgr.shutdown()

    def test_submit_failing_callback_tracked(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = self._make_manager(tmpdir)

            def fail_work():
                raise RuntimeError("boom")

            logger = _make_logger(tmpdir)
            mgr.submit_operation(
                operation_id='fail-1',
                operation_type=OperationType.SCRUB,
                priority=OperationPriority.NORMAL,
                resource_req=ResourceRequirement(memory_mb=64, cpu_percent=10.0),
                paths=[os.path.join(tmpdir, 'path-fail')],
                callback=fail_work,
                logger=logger,
            )
            mgr.wait_until_idle(timeout=5.0)
            status = mgr.get_status()
            self.assertGreaterEqual(status['metrics']['operations_failed'], 1)
            mgr.shutdown()

    def test_get_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = self._make_manager(tmpdir)
            status = mgr.get_status()
            self.assertIn('running_operations', status)
            self.assertIn('queue_info', status)
            self.assertIn('metrics', status)
            self.assertEqual(status['max_concurrent'], 1)
            mgr.shutdown()

    def test_cancel_operation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = self._make_manager(tmpdir)
            # Shut down workers so nothing dequeues
            mgr._shutdown = True
            mgr.queue.shutdown()
            for w in mgr._workers:
                w.join(timeout=2.0)

            # Re-create queue for testing cancel
            mgr.queue = OperationQueue(max_size=50)
            logger = _make_logger(tmpdir)
            op = Operation(
                id='cancel-me',
                type=OperationType.BACKUP,
                priority=OperationPriority.LOW,
                resource_req=ResourceRequirement(memory_mb=32, cpu_percent=5.0),
                paths=['/tmp/cancel'],
                callback=lambda: None,
                logger=logger,
            )
            mgr.queue.enqueue(op)
            self.assertTrue(mgr.cancel_operation('cancel-me'))
            self.assertFalse(mgr.cancel_operation('cancel-me'))

    def test_get_resource_conflicts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = self._make_manager(tmpdir)
            # No conflicts initially
            conflicts = mgr.get_resource_conflicts(['/tmp/no-conflict'])
            self.assertEqual(conflicts, [])

            # Lock a resource and check
            mgr.lock_manager.acquire_lock('/tmp/locked-resource')
            conflicts = mgr.get_resource_conflicts(['/tmp/locked-resource', '/tmp/free'])
            self.assertEqual(conflicts, ['/tmp/locked-resource'])
            mgr.lock_manager.release_lock('/tmp/locked-resource')
            mgr.shutdown()

    def test_shutdown_idempotent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = self._make_manager(tmpdir)
            mgr.shutdown()
            mgr.shutdown()  # Should not raise

    def test_wait_until_idle_already_idle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = self._make_manager(tmpdir)
            self.assertTrue(mgr.wait_until_idle(timeout=1.0))
            mgr.shutdown()

    def test_wait_until_idle_timeout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = self._make_manager(tmpdir)
            # Enqueue a long-running operation
            started = threading.Event()
            logger = _make_logger(tmpdir)

            def slow_callback():
                started.set()
                time.sleep(10)

            mgr.submit_operation(
                operation_id='slow-1',
                operation_type=OperationType.SYNC,
                priority=OperationPriority.NORMAL,
                resource_req=ResourceRequirement(memory_mb=64, cpu_percent=10.0),
                paths=[os.path.join(tmpdir, 'slow-path')],
                callback=slow_callback,
                logger=logger,
            )
            # Wait for the operation to actually start executing
            started.wait(timeout=5.0)
            # Should time out because operation is still running
            result = mgr.wait_until_idle(timeout=0.5)
            self.assertFalse(result)
            mgr.shutdown()

    def test_memory_throttle_blocks_operation(self):
        """Operations should be re-queued under memory pressure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = self._make_manager(tmpdir)
            # Set critical memory pressure
            mgr.memory_monitor.get_memory_pressure_level.return_value = 'critical'  # type: ignore[attr-defined]  # MagicMock attribute

            executed = threading.Event()
            logger = _make_logger(tmpdir)
            mgr.submit_operation(
                operation_id='throttled-1',
                operation_type=OperationType.SYNC,
                priority=OperationPriority.NORMAL,
                resource_req=ResourceRequirement(memory_mb=64, cpu_percent=10.0),
                paths=[os.path.join(tmpdir, 'throttle-path')],
                callback=lambda: executed.set(),
                logger=logger,
            )
            # Give worker a moment to try and re-queue
            time.sleep(1.5)
            # Should NOT have executed
            self.assertFalse(executed.is_set())
            self.assertGreaterEqual(mgr._metrics['memory_throttles'], 1)
            mgr.shutdown()

    def test_submit_full_queue_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_dir = os.path.join(tmpdir, 'locks')
            mgr = ConcurrentOperationManager(
                max_concurrent=1,
                lock_dir=lock_dir,
            )
            mgr.memory_monitor = MagicMock()
            mgr.memory_monitor.get_memory_pressure_level.return_value = 'normal'
            mgr.memory_monitor.can_allocate_memory.return_value = True
            mgr.memory_monitor.get_available_memory.return_value = 4 * BYTES_PER_MB * 1024

            # Shut down workers so queue fills up
            mgr._shutdown = True
            mgr.queue.shutdown()
            for w in mgr._workers:
                w.join(timeout=2.0)

            # Replace queue with tiny max
            mgr.queue = OperationQueue(max_size=1)

            logger = _make_logger(tmpdir)
            req = ResourceRequirement(memory_mb=32, cpu_percent=5.0)
            self.assertTrue(mgr.submit_operation('fill-1', OperationType.SYNC,
                                                  OperationPriority.NORMAL, req,
                                                  ['/tmp/a'], lambda: None, logger))
            logger2 = _make_logger(tmpdir)
            self.assertFalse(mgr.submit_operation('fill-2', OperationType.SYNC,
                                                   OperationPriority.NORMAL, req,
                                                   ['/tmp/b'], lambda: None, logger2))


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

class TestGetOperationManager(unittest.TestCase):
    def test_returns_manager(self):
        import lib.concurrent_operations as co
        original = co._operation_manager
        try:
            co._operation_manager = None
            with tempfile.TemporaryDirectory() as tmpdir:
                lock_dir = os.path.join(tmpdir, 'global_locks')
                mgr = co.get_operation_manager(lock_dir=lock_dir)
                self.assertIsInstance(mgr, ConcurrentOperationManager)
                # Same instance on second call
                mgr2 = co.get_operation_manager()
                self.assertIs(mgr, mgr2)
                mgr.shutdown()
        finally:
            co._operation_manager = original

    def test_singleton_reuses_existing(self):
        import lib.concurrent_operations as co
        original = co._operation_manager
        try:
            sentinel = MagicMock()
            co._operation_manager = sentinel
            result = co.get_operation_manager()
            self.assertIs(result, sentinel)
        finally:
            co._operation_manager = original


if __name__ == '__main__':
    unittest.main()
