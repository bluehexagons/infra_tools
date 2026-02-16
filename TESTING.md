# Testing Guide

This document explains how to run tests in the infra_tools project.

## Quick Start

### Run all tests
```bash
make test
# or
./run_tests.py
```

### Run specific test file
```bash
make test TEST=test_scrub_par2
# or
./run_tests.py test_scrub_par2
```

### Run with verbose output
```bash
make test-verbose
# or
./run_tests.py -v
```

## Available Commands

### Using Make (recommended)
```bash
make test                       # Run all tests
make test-verbose               # Run all tests with verbose output
make test TEST=test_name        # Run specific test
make compile                    # Check all Python files compile
make clean                      # Remove Python cache files
make help                       # Show available commands
```

### Using run_tests.py directly
```bash
./run_tests.py                  # Run all tests
./run_tests.py -v               # Verbose output
./run_tests.py test_config      # Run specific test file
./run_tests.py test_scrub_par2  # Run test (with or without .py)
./run_tests.py -h               # Show help and list all tests
```

### Using unittest directly (if you prefer)
```bash
# Run all tests
python3 -m unittest discover -s tests -p 'test_*.py'

# Run all tests with verbose output
python3 -m unittest discover -s tests -p 'test_*.py' -v

# Run specific test file
python3 -m unittest tests.test_config

# Run specific test file in subdirectory
python3 -m unittest tests.service_tools.test_scrub_par2

# Run specific test class
python3 -m unittest tests.test_config.TestSetupConfigDefaults

# Run specific test method
python3 -m unittest tests.test_config.TestSetupConfigDefaults.test_default_values
```

## Writing Tests

All tests use Python's `unittest` framework. Follow this pattern:

```python
"""Tests for my_module."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from my_module import my_function


class TestMyFunction(unittest.TestCase):
    """Tests for my_function."""
    
    def test_basic_case(self):
        """Test basic functionality."""
        result = my_function('input')
        self.assertEqual(result, 'expected')
    
    def test_edge_case(self):
        """Test edge case."""
        with self.assertRaises(ValueError):
            my_function(None)


if __name__ == '__main__':
    unittest.main()
```

### Test File Locations
- Main tests: `tests/test_*.py`
- Service tool tests: `tests/service_tools/test_*.py`

### Common Assertions
```python
self.assertEqual(a, b)           # a == b
self.assertNotEqual(a, b)        # a != b
self.assertTrue(x)               # bool(x) is True
self.assertFalse(x)              # bool(x) is False
self.assertIsNone(x)             # x is None
self.assertIsNotNone(x)          # x is not None
self.assertIn(a, b)              # a in b
self.assertNotIn(a, b)           # a not in b
self.assertRaises(exc, func)     # func raises exc
self.assertGreater(a, b)         # a > b
self.assertLess(a, b)            # a < b
```

## Continuous Integration

Tests run automatically on:
- Every commit (local development)
- Pull requests (CI/CD)

Make sure all tests pass before committing:
```bash
make test
```

## Troubleshooting

### Test discovery issues
If a test file isn't being discovered:
1. Make sure it starts with `test_`
2. Make sure it's in the `tests/` directory
3. Make sure it imports `unittest` and defines test classes

### Import errors
If you get import errors:
1. Make sure the module path is correct
2. Check that `sys.path.insert(0, ...)` is at the top of the test file
3. Verify the module exists and has no syntax errors

### Running individual test methods
```bash
python3 -m unittest tests.test_config.TestSetupConfigDefaults.test_default_values
```

## Best Practices

1. **Run tests before committing** - Always run `make test` before committing
2. **Write tests for bug fixes** - Add tests that would have caught the bug
3. **Test edge cases** - Don't just test the happy path
4. **Use descriptive names** - Test names should describe what they test
5. **Keep tests fast** - Avoid unnecessary sleeps or external dependencies
6. **Mock external dependencies** - Use `unittest.mock` for filesystem, network, etc.
7. **One assertion per test** - Makes failures easier to diagnose (when practical)

## Examples

### Test a simple function
```python
def test_add_numbers(self):
    """Test that add_numbers correctly sums two integers."""
    self.assertEqual(add_numbers(2, 3), 5)
```

### Test with mock
```python
from unittest.mock import patch

def test_with_mock(self):
    """Test function that calls os.path.exists."""
    with patch('os.path.exists', return_value=True):
        result = check_file_exists('/some/path')
        self.assertTrue(result)
```

### Test exceptions
```python
def test_raises_error(self):
    """Test that invalid input raises ValueError."""
    with self.assertRaises(ValueError):
        validate_input(None)
```

### Parameterized tests
```python
def test_multiple_cases(self):
    """Test multiple input/output pairs."""
    test_cases = [
        ('input1', 'output1'),
        ('input2', 'output2'),
        ('input3', 'output3'),
    ]
    for input_val, expected in test_cases:
        with self.subTest(input=input_val):
            self.assertEqual(my_function(input_val), expected)
```
