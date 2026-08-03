"""Tests for web.ssl_steps certificate state handling."""

from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from web.ssl_steps import obtain_letsencrypt_certificate


class TestObtainLetsEncryptCertificate(unittest.TestCase):
    @patch("web.ssl_steps._certificate_is_usable", return_value=True)
    @patch("web.ssl_steps.run")
    @patch("web.ssl_steps.os.path.exists", side_effect=[True, True])
    def test_complete_existing_certificate_is_reused(
        self,
        _mock_exists,
        mock_run,
        _mock_usable,
    ):
        self.assertTrue(obtain_letsencrypt_certificate(["example.com"], cert_name="example.com"))
        mock_run.assert_not_called()

    @patch("web.ssl_steps.run")
    @patch("web.ssl_steps.os.path.exists", side_effect=[True, False, True])
    def test_incomplete_existing_certificate_attempts_replacement(self, _mock_exists, mock_run):
        mock_run.return_value = SimpleNamespace(returncode=1)
        self.assertFalse(obtain_letsencrypt_certificate(["example.com"], cert_name="example.com"))
        mock_run.assert_called()


if __name__ == "__main__":
    unittest.main()
