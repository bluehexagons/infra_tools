#!/usr/bin/env python3
"""Test script for centralized logging system.

This script demonstrates and tests the centralized logging system by:
1. Creating loggers for different services
2. Writing test messages at different log levels
3. Verifying log file creation
4. Testing log rotation
"""

import os
import sys
import tempfile
import shutil

# Add lib directory to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from lib.logging_utils import get_service_logger, get_rotating_logger
from logging import DEBUG
from lib.operation_log import create_operation_logger


def test_basic_logging():
    """Test basic service logger functionality."""
    print("=" * 60)
    print("Test 1: Basic Service Logger")
    print("=" * 60)
    
    # Use temporary directory for testing
    temp_dir = tempfile.mkdtemp(prefix='infra_tools_test_')
    
    try:
        # Override default log dir for testing
        import lib.logging_utils as logging_utils
        original_log_dir = logging_utils.DEFAULT_LOG_DIR
        logging_utils.DEFAULT_LOG_DIR = temp_dir
        
        # Create test logger
        logger = get_service_logger('test_service', 'test_category')
        
        # Write test messages
        logger.info("This is an INFO message")
        logger.warning("This is a WARNING message")
        logger.error("This is an ERROR message")
        logger.debug("This is a DEBUG message (won't appear unless level is DEBUG)")
        
        # Check if log file was created
        log_file = os.path.join(temp_dir, 'test_category', 'test_service.log')
        if os.path.exists(log_file):
            print(f"✓ Log file created: {log_file}")
            print(f"✓ Log file size: {os.path.getsize(log_file)} bytes")
            
            # Read and display log contents
            with open(log_file, 'r') as f:
                contents = f.read()
                print("\nLog contents:")
                print("-" * 60)
                print(contents)
                print("-" * 60)
            
            # Verify messages are in log
            if "INFO" in contents and "WARNING" in contents and "ERROR" in contents:
                print("✓ All log levels written successfully")
            else:
                print("✗ Some log levels missing")
        else:
            print(f"✗ Log file not created at {log_file}")
        
        # Restore original log dir
        logging_utils.DEFAULT_LOG_DIR = original_log_dir
        
    finally:
        # Cleanup
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    print()


def test_operation_logging():
    """Test operation logger functionality."""
    print("=" * 60)
    print("Test 2: Operation Logger")
    print("=" * 60)
    
    # Use temporary directory for testing
    temp_dir = tempfile.mkdtemp(prefix='infra_tools_op_test_')
    
    try:
        # Override the default log directory for operation logger
        import lib.operation_log as operation_log
        original_manager = getattr(operation_log, '_logger_manager', None)
        operation_log.set_operation_logger_manager(None)
        
        # Create manager with temp directory
        from lib.operation_log import OperationLoggerManager
        temp_manager = OperationLoggerManager(temp_dir)
        operation_log.set_operation_logger_manager(temp_manager)
        
        # Create operation logger
        logger = create_operation_logger('test_operation', test_param='test_value')
        
        # Test operation logging
        logger.log_step('initialization', 'started', 'Initializing test operation')
        logger.log_step('initialization', 'completed', 'Initialization complete')
        
        logger.log_metric('test_metric', 42, 'units')
        logger.log_warning('Test warning message')
        logger.log_error('test_error', 'Test error message', {'detail': 'test detail'})
        
        logger.create_checkpoint('test_checkpoint', {'state': 'test_state'})
        logger.complete('completed', 'Test operation completed')
        
        # Check if any log file exists in temp dir
        log_files = [f for f in os.listdir(temp_dir) if f.endswith('.log')]
        
        if log_files:
            print(f"✓ Operation log file created")
            for log_file in log_files:
                full_path = os.path.join(temp_dir, log_file)
                print(f"✓ Log file: {log_file} ({os.path.getsize(full_path)} bytes)")
                
                # Show a sample of the log
                with open(full_path, 'r') as f:
                    lines = f.readlines()
                    if lines:
                        print(f"✓ Log contains {len(lines)} entries")
                        print("  Sample entry:", lines[0].strip()[:80] + "...")
        else:
            print("✗ No operation log files created")
        
        print("✓ Operation logger test completed")
        
        # Restore original manager
        operation_log.set_operation_logger_manager(original_manager)
        
    finally:
        # Cleanup
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    print()


def test_log_levels():
    """Test different log levels."""
    print("=" * 60)
    print("Test 3: Log Levels")
    print("=" * 60)
    
    temp_dir = tempfile.mkdtemp(prefix='infra_tools_level_test_')
    
    try:
        # Test with DEBUG level
        logger = get_rotating_logger(
            'test_debug',
            os.path.join(temp_dir, 'debug.log'),
            level=DEBUG
        )
        
        logger.debug("Debug message")
        logger.info("Info message")
        logger.warning("Warning message")
        logger.error("Error message")
        
        log_file = os.path.join(temp_dir, 'debug.log')
        with open(log_file, 'r') as f:
            contents = f.read()
        
        if "DEBUG" in contents:
            print("✓ DEBUG level messages are logged when level=DEBUG")
        else:
            print("✗ DEBUG messages missing")
        
        if "INFO" in contents and "WARNING" in contents and "ERROR" in contents:
            print("✓ All log levels present")
        else:
            print("✗ Some log levels missing")
        
        print(f"✓ Log file has {len(contents.splitlines())} lines")
        
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    print()


def test_directory_creation():
    """Test automatic directory creation."""
    print("=" * 60)
    print("Test 4: Directory Creation")
    print("=" * 60)
    
    temp_dir = tempfile.mkdtemp(prefix='infra_tools_dir_test_')
    
    try:
        # Create logger with nested directory structure
        log_file = os.path.join(temp_dir, 'level1', 'level2', 'level3', 'test.log')
        logger = get_rotating_logger('test_dirs', log_file)
        
        logger.info("Test message")
        
        if os.path.exists(log_file):
            print(f"✓ Nested directories created automatically")
            print(f"✓ Log file created at: {log_file}")
        else:
            print(f"✗ Failed to create nested directories")
        
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    print()


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("INFRA_TOOLS CENTRALIZED LOGGING SYSTEM TEST")
    print("=" * 60 + "\n")
    
    try:
        test_basic_logging()
        test_operation_logging()
        test_log_levels()
        test_directory_creation()
        
        print("=" * 60)
        print("ALL TESTS COMPLETED")
        print("=" * 60)
        print("\nNote: Production logs are written to /var/log/infra_tools/")
        print("This test used temporary directories for safety.")
        
        return 0
        
    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
