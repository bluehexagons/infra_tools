#!/usr/bin/env python3
"""Simple test runner for infra_tools.

Usage:
    ./run_tests.py                    # Run all tests (concise output)
    ./run_tests.py test_config        # Run specific test file
    ./run_tests.py TestSetupConfig    # Run specific test class
    ./run_tests.py -v                 # Verbose output (detailed)
    ./run_tests.py -h                 # Show help
    
Examples:
    ./run_tests.py
    ./run_tests.py -v
    ./run_tests.py test_scrub_par2
    ./run_tests.py test_scrub_par2 -v
"""

from __future__ import annotations

import sys
import os
import io

# Parse arguments at the very beginning (before any imports)
verbose = '-v' in sys.argv or '--verbose' in sys.argv
help_requested = '-h' in sys.argv or '--help' in sys.argv

# Set test mode to suppress console logging from infra_tools
if not verbose and not help_requested:
    os.environ['INFRA_TOOLS_TEST'] = '1'

from pathlib import Path
from typing import TextIO
import unittest


class TeeIO:
    """Captures output to a buffer while optionally passing through to original stream."""
    
    def __init__(self, original: TextIO, capture: io.StringIO, passthrough: bool = False):
        self.original = original
        self.capture = capture
        self.passthrough = passthrough
    
    def write(self, data: str) -> int:
        self.capture.write(data)
        if self.passthrough:
            return self.original.write(data)
        return len(data)
    
    def flush(self) -> None:
        if self.passthrough:
            self.original.flush()
    
    def isatty(self) -> bool:
        return self.original.isatty()


def show_help():
    """Display help message."""
    print(__doc__)
    print("\nAvailable test files:")
    test_dir = Path(__file__).parent / "tests"
    for test_file in sorted(test_dir.rglob("test_*.py")):
        rel_path = test_file.relative_to(test_dir)
        print(f"  {rel_path}")


def main():
    """Run tests with simple command-line interface."""
    
    if help_requested:
        show_help()
        return 0
    
    # Remove flags from argv
    args = [arg for arg in sys.argv[1:] if not arg.startswith('-')]
    
    # Change to project directory
    project_dir = Path(__file__).parent
    os.chdir(project_dir)
    
    # Set up output capture for non-verbose mode
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    capture = io.StringIO()
    
    if not verbose:
        # Suppress all output during test discovery and execution
        sys.stdout = capture
        sys.stderr = capture
    
    # Set up test loader
    loader = unittest.TestLoader()
    
    if not args:
        # Run all tests
        suite = loader.discover('tests', pattern='test_*.py')
    else:
        # Run specific tests
        test_pattern = args[0]
        
        # Add .py extension if not present
        if not test_pattern.endswith('.py'):
            test_pattern_with_ext = test_pattern + '.py'
        else:
            test_pattern_with_ext = test_pattern
            test_pattern = test_pattern[:-3]
        
        # Try to find the test file
        test_dir = Path('tests')
        found_files = list(test_dir.rglob(f"*{test_pattern_with_ext}"))
        
        if found_files:
            # Load specific test file
            test_file = found_files[0]
            rel_path = test_file.relative_to(test_dir)
            module_path = str(rel_path.with_suffix('')).replace(os.sep, '.')
            module_name = f'tests.{module_path}'
            try:
                suite = loader.loadTestsFromName(module_name)
            except (ImportError, AttributeError) as e:
                print(f"Error loading test module: {e}")
                return 1
        else:
            # Try loading as a module path (e.g., tests.test_config)
            if not test_pattern.startswith('tests.'):
                if '/' in test_pattern or os.sep in test_pattern:
                    # Convert path to module notation
                    test_pattern = test_pattern.replace('/', '.').replace(os.sep, '.')
                module_name = f'tests.{test_pattern}'
            else:
                module_name = test_pattern
            
            try:
                suite = loader.loadTestsFromName(module_name)
            except (ImportError, AttributeError) as e:
                print(f"Error: Could not find test '{test_pattern}'")
                print(f"Details: {e}")
                print("\nRun './run_tests.py -h' to see available tests")
                return 1
    
    # Run tests
    if verbose:
        # Restore stdout for verbose mode
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)
    else:
        # Already captured in 'capture', just run tests
        runner = unittest.TextTestRunner(stream=capture, verbosity=0)
        result = runner.run(suite)
        
        # Restore stdout to print results
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        
        # Show output only if there were failures
        if not result.wasSuccessful():
            print(capture.getvalue())
    
    # Print summary
    print()
    if result.wasSuccessful():
        print(f"✓ All tests passed ({result.testsRun} tests)")
        return 0
    else:
        print(f"✗ Tests failed: {len(result.failures)} failures, {len(result.errors)} errors")
        return 1


if __name__ == '__main__':
    sys.exit(main())
