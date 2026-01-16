"""Transaction management framework extending dry-run patterns for atomic operations."""

from __future__ import annotations

import time
import traceback
from typing import Callable, Any, Optional
from dataclasses import dataclass
from lib.types import JSONDict, JSONList

from lib.operation_log import OperationLogger


@dataclass
class TransactionStep:
    """Represents a single step in a transaction."""
    name: str
    execute_func: Callable[..., Any]
    rollback_func: Callable[..., Any]
    description: str
    completed: bool = False
    rollback_completed: bool = False
    error: Optional[str] = None
    execution_time: Optional[float] = None


class Transaction:
    """Transaction manager for atomic operations with rollback capability."""
    
    def __init__(self, operation_id: str, logger: OperationLogger, timeout_seconds: int = 3600):
        """Initialize transaction.
        
        Args:
            operation_id: Unique identifier for the operation
            logger: OperationLogger instance
            timeout_seconds: Timeout for transaction in seconds (default: 1 hour)
        """
        self.operation_id = operation_id
        self.logger = logger
        self.timeout_seconds = timeout_seconds
        self.steps: list[TransactionStep] = []
        self.checkpoints: dict[str, int] = {}
        self.current_step_index = 0
        self.transaction_start_time = time.time()
        self.status = "pending"
        self.final_checkpoint_name = None
        
        self.logger.log_step("transaction_initiated", "started", 
                           f"Transaction initialized with {timeout_seconds}s timeout")
    
    def add_step(self, step: Callable[..., Any], rollback: Callable[..., Any], description: str, name: Optional[str] = None) -> None:
        """Add a step to the transaction.
        
        Args:
            step: Function to execute for this step
            rollback: Function to rollback this step
            description: Description of the step
            name: Optional name for the step
        """
        if name is None:
            name = f"step_{len(self.steps) + 1}"
        
        transaction_step = TransactionStep(
            name=name,
            execute_func=step,
            rollback_func=rollback,
            description=description
        )
        
        self.steps.append(transaction_step)
        self.logger.log_step("step_added", "completed", 
                           f"Added step '{name}': {description}")
    
    def add_validation_step(self, validation_func: Callable[..., Any], description: str, name: Optional[str] = None) -> None:
        """Add a validation step (no rollback needed).
        
        Args:
            validation_func: Function to validate something
            description: Description of the validation
            name: Optional name for the step
        """
        if name is None:
            name = f"validation_{len(self.steps) + 1}"
        
        # No-op rollback function for validation steps
        def noop_rollback():
            pass
        
        self.add_step(validation_func, noop_rollback, description, name)
    
    def execute(self, continue_on_error: bool = False) -> bool:
        """Execute all transaction steps.
        
        Args:
            continue_on_error: If True, continue execution after errors
            
        Returns:
            bool: True if all steps completed successfully, False otherwise
        """
        self.status = "executing"
        self.logger.log_step("transaction_execution", "started", 
                           f"Starting execution of {len(self.steps)} steps")
        
        try:
            for i, step in enumerate(self.steps):
                self.current_step_index = i
                
                # Check timeout
                if self._check_timeout():
                    self.logger.log_error("timeout", 
                                        f"Transaction timed out after {self.timeout_seconds}s")
                    return False
                
                self.logger.log_step(step.name, "started", step.description)
                step_start_time = time.time()
                
                try:
                    # Execute the step
                    step.execute_func()
                    step.completed = True
                    step.execution_time = time.time() - step_start_time
                    
                    self.logger.log_step(step.name, "completed", 
                                       step.description, step.execution_time)
                
                except Exception as e:
                    step.error = str(e)
                    step.execution_time = time.time() - step_start_time
                    
                    error_msg = f"Step '{step.name}' failed: {e}"
                    self.logger.log_error("step_execution_error", error_msg, 
                                       {"step": step.name, "traceback": traceback.format_exc()})
                    
                    if not continue_on_error:
                        self.status = "failed"
                        return False
            
            self.status = "completed"
            self.logger.log_step("transaction_execution", "completed", 
                               f"All {len(self.steps)} steps completed successfully")
            return True
            
        except Exception as e:
            self.logger.log_error("transaction_execution_error", str(e), 
                               {"traceback": traceback.format_exc()})
            self.status = "failed"
            return False
    
    def rollback(self, reason: str = "Transaction failed") -> bool:
        """Rollback completed steps in reverse order.
        
        Args:
            reason: Reason for rollback
            
        Returns:
            bool: True if rollback completed successfully, False otherwise
        """
        self.status = "rolling_back"
        self.logger.log_step("transaction_rollback", "started", 
                           f"Rolling back due to: {reason}")
        
        rollback_success = True
        
        # Rollback completed steps in reverse order
        for step in reversed(self.steps):
            if step.completed and not step.rollback_completed:
                self.logger.log_step(f"{step.name}_rollback", "started", 
                                   f"Rolling back: {step.description}")
                
                try:
                    step.rollback_func()
                    step.rollback_completed = True
                    
                    self.logger.log_step(f"{step.name}_rollback", "completed", 
                                       f"Successfully rolled back: {step.description}")
                
                except Exception as e:
                    rollback_success = False
                    error_msg = f"Rollback failed for step '{step.name}': {e}"
                    self.logger.log_error("rollback_error", error_msg, 
                                       {"step": step.name, "traceback": traceback.format_exc()})
        
        if rollback_success:
            self.status = "rolled_back"
            self.logger.log_step("transaction_rollback", "completed", 
                               "All steps rolled back successfully")
        else:
            self.status = "rollback_failed"
            self.logger.log_step("transaction_rollback", "failed", 
                               "Some rollback steps failed")
        
        return rollback_success
    
    def create_checkpoint(self, name: str) -> None:
        """Create a checkpoint at the current position.
        
        Args:
            name: Name for the checkpoint
        """
        self.checkpoints[name] = self.current_step_index
        
        # Capture current state for logger
        checkpoint_state: JSONDict = {
            "step_index": self.current_step_index,
            "completed_steps": [s.name for s in self.steps[:self.current_step_index] if s.completed],
            "pending_steps": [s.name for s in self.steps[self.current_step_index:]],
            "transaction_status": self.status
        }
        
        self.logger.create_checkpoint(name, checkpoint_state)
    
    def rollback_to_checkpoint(self, checkpoint_name: str, reason: Optional[str] = None) -> bool:
        """Rollback to a specific checkpoint.
        
        Args:
            checkpoint_name: Name of checkpoint to rollback to
            reason: Reason for rollback
            
        Returns:
            bool: True if rollback completed successfully, False otherwise
        """
        if checkpoint_name not in self.checkpoints:
            self.logger.log_error("checkpoint_not_found", 
                                f"Checkpoint '{checkpoint_name}' not found")
            return False
        
        checkpoint_index = self.checkpoints[checkpoint_name]
        
        if reason is None:
            reason = f"Rollback to checkpoint '{checkpoint_name}'"
        
        self.logger.log_rollback(checkpoint_name, reason)
        
        # Rollback steps after checkpoint
        rollback_success = True
        for i in range(len(self.steps) - 1, checkpoint_index - 1, -1):
            step = self.steps[i]
            if step.completed and not step.rollback_completed:
                try:
                    step.rollback_func()
                    step.rollback_completed = True
                except Exception as e:
                    rollback_success = False
                    self.logger.log_error("checkpoint_rollback_error", 
                                        f"Rollback failed for step '{step.name}': {e}")
        
        return rollback_success
    
    def _check_timeout(self) -> bool:
        """Check if transaction has timed out.
        
        Returns:
            bool: True if timeout exceeded, False otherwise
        """
        elapsed = time.time() - self.transaction_start_time
        if elapsed > self.timeout_seconds:
            self.logger.log_warning("Transaction approaching timeout", 
                                  {"elapsed_seconds": elapsed, "timeout_seconds": self.timeout_seconds})
        return elapsed > self.timeout_seconds
    
    def get_status(self) -> JSONDict:
        """Get transaction status and statistics.
        
        Returns:
            Dictionary with transaction status
        """
        completed_steps = sum(1 for step in self.steps if step.completed)
        failed_steps = sum(1 for step in self.steps if step.error)
        
        return {
            "operation_id": self.operation_id,
            "status": self.status,
            "total_steps": len(self.steps),
            "completed_steps": completed_steps,
            "failed_steps": failed_steps,
            "current_step_index": self.current_step_index,
            "elapsed_time_seconds": time.time() - self.transaction_start_time,
            "checkpoints": list(self.checkpoints.keys())
        }
    
    def get_step_details(self) -> JSONList:
        """Get details of all transaction steps.
        
        Returns:
            List of step details
        """
        return [
            {
                "name": step.name,
                "description": step.description,
                "completed": step.completed,
                "rollback_completed": step.rollback_completed,
                "error": step.error,
                "execution_time": step.execution_time
            }
            for step in self.steps
        ]


class TransactionManager:
    """Manager for multiple transactions."""
    
    def __init__(self):
        """Initialize transaction manager."""
        self.active_transactions: dict[str, Transaction] = {}
    
    def create_transaction(self, operation_id: str, logger: OperationLogger, **kwargs: Any) -> Transaction:
        """Create a new transaction.
        
        Args:
            operation_id: Unique operation identifier
            logger: OperationLogger instance
            **kwargs: Additional transaction parameters
            
        Returns:
            New Transaction instance
        """
        transaction = Transaction(operation_id, logger, **kwargs)
        self.active_transactions[operation_id] = transaction
        return transaction
    
    def get_transaction(self, operation_id: str) -> Optional[Transaction]:
        """Get active transaction by operation ID.
        
        Args:
            operation_id: Operation ID to retrieve
            
        Returns:
            Transaction if found, None otherwise
        """
        return self.active_transactions.get(operation_id)
    
    def complete_transaction(self, operation_id: str) -> None:
        """Mark transaction as complete and remove from active transactions.
        
        Args:
            operation_id: Operation ID to complete
        """
        if operation_id in self.active_transactions:
            del self.active_transactions[operation_id]
    
    def get_active_transaction_count(self) -> int:
        """Get count of active transactions.
        
        Returns:
            Number of active transactions
        """
        return len(self.active_transactions)
    
    def cleanup_stalled_transactions(self, max_age_seconds: int = 3600) -> int:
        """Clean up stalled transactions.
        
        Args:
            max_age_seconds: Maximum age before considering transaction stalled
            
        Returns:
            Number of transactions cleaned up
        """
        current_time = time.time()
        stalled_count = 0
        
        for operation_id, transaction in list(self.active_transactions.items()):
            age = current_time - transaction.transaction_start_time
            if age > max_age_seconds and transaction.status not in ["executing", "rolling_back"]:
                del self.active_transactions[operation_id]
                stalled_count += 1
        
        return stalled_count


# Global transaction manager instance
_transaction_manager = None


def get_transaction_manager() -> TransactionManager:
    """Get the global transaction manager.
    
    Returns:
        TransactionManager instance
    """
    global _transaction_manager
    if _transaction_manager is None:
        _transaction_manager = TransactionManager()
    return _transaction_manager


def create_transaction(operation_id: str, logger: OperationLogger, **kwargs: Any) -> Transaction:
    """Convenience function to create a new transaction.
    
    Args:
        operation_id: Unique operation identifier
        logger: OperationLogger instance
        **kwargs: Additional transaction parameters
        
    Returns:
        New Transaction instance
    """
    manager = get_transaction_manager()
    return manager.create_transaction(operation_id, logger, **kwargs)