
from __future__ import annotations
import time
import threading
from typing import Optional, Any

from lib.config import SetupConfig
from lib.concurrent_operations import (
    OperationType, OperationPriority, 
    ResourceRequirement, get_operation_manager
)
from lib.operation_log import OperationLogger
from lib.operation_log import create_operation_logger
from lib.sync_steps import parse_sync_spec, create_sync_service
from lib.scrub_steps import parse_scrub_spec, create_scrub_service

class ConcurrentSyncScrubCoordinator:
    def __init__(self, config: SetupConfig, max_concurrent: int = 3, 
                 memory_warning_mb: int = 512, memory_critical_mb: int = 256):
        self.config = config
        self.operation_manager = get_operation_manager(
            max_concurrent=max_concurrent,
            memory_warning_mb=memory_warning_mb,
            memory_critical_mb=memory_critical_mb
        )
        self._active_operations: dict[str, dict[str, Any]] = {}
        self._operation_lock = threading.Lock()
        self._shared_resources: dict[str, dict[str, Any]] = {}

    def wait_until_idle(self, timeout: Optional[float] = None) -> bool:
        return self.operation_manager.wait_until_idle(timeout or 0.0)

    def submit_sync_operation(self, sync_spec: list[str], priority: OperationPriority = OperationPriority.NORMAL) -> str:
        try:
            sync_config = parse_sync_spec(sync_spec)
            operation_id = f"sync_{int(time.time())}_{hash(sync_config['source']) % 10000}"
            
            logger = create_operation_logger("concurrent_sync", 
                                           source=sync_config['source'],
                                           destination=sync_config['destination'],
                                           interval=sync_config['interval'])
            
            def sync_callback():
                return self._execute_sync_operation(sync_config, logger)
            
            resource_req = ResourceRequirement(
                memory_mb=self._estimate_memory_usage('sync'), 
                cpu_percent=30.0
            )
            
            with self._operation_lock:
                self._active_operations[operation_id] = {
                    'type': 'sync',
                    'config': sync_config,
                    'priority': priority,
                    'submitted_at': time.time()
                }
            
            success = self.operation_manager.submit_operation(
                operation_id=operation_id,
                operation_type=OperationType.SYNC,
                priority=priority,
                resource_req=resource_req,
                paths=[sync_config['source'], sync_config['destination']],
                callback=sync_callback,
                logger=logger
            )
            
            if success:
                logger.log_step("submitted", "completed", f"Sync operation submitted: {operation_id}")
                return operation_id
            
            with self._operation_lock:
                self._active_operations.pop(operation_id, None)
            raise RuntimeError("Failed to submit sync operation")
                
        except Exception as e:
            logger = create_operation_logger("sync_error")
            logger.log_error("sync_submission_error", str(e))
            raise
    
    def submit_scrub_operation(self, scrub_spec: list[str], priority: OperationPriority = OperationPriority.NORMAL) -> str:
        try:
            scrub_config = parse_scrub_spec(scrub_spec)
            operation_id = f"scrub_{int(time.time())}_{hash(scrub_config['directory']) % 10000}"
            
            logger = create_operation_logger("concurrent_scrub",
                                           directory=scrub_config['directory'],
                                           database_path=scrub_config['database_path'])
            
            def scrub_callback():
                return self._execute_scrub_operation(scrub_config, logger)
            
            resource_req = ResourceRequirement(
                memory_mb=self._estimate_memory_usage('scrub'), 
                cpu_percent=50.0
            )
            
            with self._operation_lock:
                self._active_operations[operation_id] = {
                    'type': 'scrub',
                    'config': scrub_config,
                    'priority': priority,
                    'submitted_at': time.time()
                }
            
            success = self.operation_manager.submit_operation(
                operation_id=operation_id,
                operation_type=OperationType.SCRUB,
                priority=priority,
                resource_req=resource_req,
                paths=[scrub_config['directory']],
                callback=scrub_callback,
                logger=logger
            )
            
            if success:
                logger.log_step("submitted", "completed", f"Scrub operation submitted: {operation_id}")
                return operation_id
            
            with self._operation_lock:
                self._active_operations.pop(operation_id, None)
            raise RuntimeError("Failed to submit scrub operation")
                
        except Exception as e:
            logger = create_operation_logger("scrub_error")
            logger.log_error("scrub_submission_error", str(e))
            raise

    def _execute_sync_operation(self, sync_config: dict[str, Any], logger: OperationLogger) -> bool:
        try:
            logger.log_step("sync_execution", "started", 
                          f"Executing sync: {sync_config['source']} → {sync_config['destination']}")
            create_sync_service(self.config, [sync_config['source'], sync_config['destination'], sync_config['interval']])
            logger.log_step("sync_execution", "completed", "Sync completed")
            return True
        except Exception as e:
            logger.log_error("sync_execution_failed", str(e))
            return False

    def _execute_scrub_operation(self, scrub_config: dict[str, Any], logger: OperationLogger) -> bool:
        try:
            logger.log_step("scrub_execution", "started", f"Executing scrub: {scrub_config['directory']}")
            create_scrub_service(self.config, [scrub_config['directory'], scrub_config['database_path'], 
                                scrub_config['redundancy'], scrub_config['frequency']])
            logger.log_step("scrub_execution", "completed", "Scrub completed")
            return True
        except Exception as e:
            logger.log_error("scrub_execution_failed", str(e))
            return False
    
    def _estimate_memory_usage(self, operation_type: str) -> int:
        """Return conservative fixed memory estimates. Tools manage their own memory.
        
        rsync uses minimal memory regardless of file count.
        par2 memory usage scales with block count, not file count.
        """
        # Fixed conservative estimates - actual memory managed by tools
        estimates = {
            'sync': 64,   # rsync is memory-efficient
            'scrub': 128  # par2 uses more for parity calculation
        }
        return estimates.get(operation_type, 100)

    def get_coordinator_status(self) -> dict[str, Any]:
        manager_status = self.operation_manager.get_status()
        with self._operation_lock:
            active_ops = list(self._active_operations.values())
        
        return {
            'active_operations': len(active_ops),
            'operation_types': {
                'sync': sum(1 for op in active_ops if op['type'] == 'sync'),
                'scrub': sum(1 for op in active_ops if op['type'] == 'scrub')
            },
            'manager_status': manager_status
        }

def create_concurrent_coordinator(config: SetupConfig, **kwargs: Any) -> ConcurrentSyncScrubCoordinator:
    return ConcurrentSyncScrubCoordinator(config, **kwargs)
