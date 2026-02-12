"""Tests for lib/validation.py: validate_directory_empty, validate_network_endpoint, validate_positive_integer."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.validation import (
    validate_directory_empty,
    validate_network_endpoint,
    validate_positive_integer,
)


class TestValidateDirectoryEmpty(unittest.TestCase):
    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            validate_directory_empty(tmpdir)  # should not raise

    def test_non_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, 'file.txt'), 'w') as f:
                f.write('content')
            with self.assertRaises(ValueError):
                validate_directory_empty(tmpdir)

    def test_hidden_files_ignored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, '.hidden'), 'w') as f:
                f.write('hidden')
            validate_directory_empty(tmpdir)  # hidden files should not count

    def test_not_a_directory(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name
        try:
            with self.assertRaises(ValueError):
                validate_directory_empty(path)
        finally:
            os.unlink(path)

    def test_nonexistent_directory(self):
        with self.assertRaises(ValueError):
            validate_directory_empty('/nonexistent/path/xyz')


class TestValidateNetworkEndpoint(unittest.TestCase):
    def test_valid_ip_port(self):
        validate_network_endpoint('192.168.1.1:8080')  # should not raise

    def test_valid_hostname_port(self):
        validate_network_endpoint('example.com:443')  # should not raise

    def test_empty_endpoint(self):
        with self.assertRaises(ValueError):
            validate_network_endpoint('')

    def test_missing_port(self):
        with self.assertRaises(ValueError):
            validate_network_endpoint('192.168.1.1')

    def test_port_out_of_range_high(self):
        with self.assertRaises(ValueError):
            validate_network_endpoint('192.168.1.1:70000')

    def test_port_out_of_range_zero(self):
        with self.assertRaises(ValueError):
            validate_network_endpoint('192.168.1.1:0')

    def test_invalid_host(self):
        with self.assertRaises(ValueError):
            validate_network_endpoint('-invalid:80')

    def test_non_numeric_port(self):
        with self.assertRaises(ValueError):
            validate_network_endpoint('host:abc')

    def test_multiple_colons(self):
        with self.assertRaises(ValueError):
            validate_network_endpoint('host:80:90')


class TestValidatePositiveInteger(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(validate_positive_integer('42'), 42)

    def test_valid_with_spaces(self):
        self.assertEqual(validate_positive_integer('  7  '), 7)

    def test_zero_not_positive(self):
        with self.assertRaises(ValueError):
            validate_positive_integer('0')

    def test_negative(self):
        with self.assertRaises(ValueError):
            validate_positive_integer('-5')

    def test_empty(self):
        with self.assertRaises(ValueError):
            validate_positive_integer('')

    def test_non_numeric(self):
        with self.assertRaises(ValueError):
            validate_positive_integer('abc')

    def test_custom_name_in_error(self):
        with self.assertRaises(ValueError) as ctx:
            validate_positive_integer('0', name='count')
        self.assertIn('count', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
