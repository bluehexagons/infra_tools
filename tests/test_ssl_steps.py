"""Tests for web.ssl_steps certificate state handling."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from web.ssl_steps import obtain_letsencrypt_certificate, setup_certificate_renewal


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


class TestCertificateRenewal(unittest.TestCase):
    def test_installs_nginx_reload_deploy_hook(self):
        with tempfile.TemporaryDirectory() as directory:
            hook = os.path.join(directory, "reload-nginx")
            completed = SimpleNamespace(returncode=0)
            with (
                patch("web.ssl_steps.CERTBOT_NGINX_DEPLOY_HOOK", hook),
                patch("web.ssl_steps.run", return_value=completed),
            ):
                setup_certificate_renewal()

            with open(hook, encoding="utf-8") as source:
                content = source.read()
            self.assertIn("/usr/sbin/nginx -t", content)
            self.assertIn("systemctl reload nginx", content)
            self.assertEqual(os.stat(hook).st_mode & 0o777, 0o755)


if __name__ == "__main__":
    unittest.main()
