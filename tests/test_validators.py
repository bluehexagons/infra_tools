"""Tests for lib/validators.py: IP, host, and username validation."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.validators import validate_ip_address, validate_host, validate_username


class TestValidateIpAddress(unittest.TestCase):
    def test_valid_ipv4(self):
        self.assertTrue(validate_ip_address('192.168.1.1'))

    def test_valid_all_zeros(self):
        self.assertTrue(validate_ip_address('0.0.0.0'))

    def test_valid_max_octets(self):
        self.assertTrue(validate_ip_address('255.255.255.255'))

    def test_invalid_octet_too_large(self):
        self.assertFalse(validate_ip_address('256.0.0.1'))

    def test_invalid_too_few_octets(self):
        self.assertFalse(validate_ip_address('192.168.1'))

    def test_invalid_too_many_octets(self):
        self.assertFalse(validate_ip_address('192.168.1.1.1'))

    def test_invalid_non_numeric(self):
        self.assertFalse(validate_ip_address('abc.def.ghi.jkl'))

    def test_invalid_empty(self):
        self.assertFalse(validate_ip_address(''))

    def test_invalid_negative_octet(self):
        self.assertFalse(validate_ip_address('-1.0.0.1'))


class TestValidateHost(unittest.TestCase):
    def test_valid_ip(self):
        self.assertTrue(validate_host('192.168.1.1'))

    def test_valid_hostname(self):
        self.assertTrue(validate_host('myserver'))

    def test_valid_fqdn(self):
        self.assertTrue(validate_host('server.example.com'))

    def test_valid_trailing_dot(self):
        self.assertTrue(validate_host('server.example.com.'))

    def test_valid_subdomain(self):
        self.assertTrue(validate_host('sub.domain.example.com'))

    def test_invalid_starts_with_hyphen(self):
        self.assertFalse(validate_host('-invalid.com'))

    def test_invalid_special_chars(self):
        self.assertFalse(validate_host('server!.com'))

    def test_invalid_empty(self):
        self.assertFalse(validate_host(''))


class TestValidateUsername(unittest.TestCase):
    def test_valid_simple(self):
        self.assertTrue(validate_username('john'))

    def test_valid_with_underscore(self):
        self.assertTrue(validate_username('john_doe'))

    def test_valid_with_hyphen(self):
        self.assertTrue(validate_username('john-doe'))

    def test_valid_starts_with_underscore(self):
        self.assertTrue(validate_username('_service'))

    def test_valid_with_digits(self):
        self.assertTrue(validate_username('user123'))

    def test_invalid_starts_with_digit(self):
        self.assertFalse(validate_username('1user'))

    def test_invalid_uppercase(self):
        self.assertFalse(validate_username('John'))

    def test_invalid_too_long(self):
        self.assertFalse(validate_username('a' * 33))

    def test_valid_max_length(self):
        self.assertTrue(validate_username('a' * 32))

    def test_invalid_empty(self):
        self.assertFalse(validate_username(''))

    def test_invalid_special_chars(self):
        self.assertFalse(validate_username('user@name'))


if __name__ == '__main__':
    unittest.main()
