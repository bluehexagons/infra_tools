"""Tests for XRDP certificate discovery and health checks."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from lib.xrdp_certificate import (
    DEFAULT_XRDP_CERTIFICATE,
    DEFAULT_XRDP_PRIVATE_KEY,
    inspect_xrdp_certificate,
    inspect_xrdp_certificate_pair,
    read_xrdp_certificate_paths,
)


class TestXrdpCertificatePaths(unittest.TestCase):
    def test_blank_values_use_xrdp_defaults(self) -> None:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as config_file:
            config_file.write("[Globals]\ncertificate=\nkey_file=\n")
            config_file.flush()

            paths = read_xrdp_certificate_paths(config_file.name)

        self.assertEqual(paths, (DEFAULT_XRDP_CERTIFICATE, DEFAULT_XRDP_PRIVATE_KEY))

    def test_explicit_absolute_paths_are_preserved(self) -> None:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as config_file:
            config_file.write(
                "[Globals]\ncertificate=/etc/pki/rdp.crt\n"
                "key_file=/etc/pki/rdp.key\n"
            )
            config_file.flush()

            paths = read_xrdp_certificate_paths(config_file.name)

        self.assertEqual(paths, ("/etc/pki/rdp.crt", "/etc/pki/rdp.key"))

    def test_relative_path_is_rejected(self) -> None:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as config_file:
            config_file.write("[Globals]\ncertificate=cert.pem\nkey_file=/tmp/key.pem\n")
            config_file.flush()

            with self.assertRaisesRegex(ValueError, "normalized and absolute"):
                read_xrdp_certificate_paths(config_file.name)


class TestXrdpCertificateHealth(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.certificate = os.path.join(self.tempdir.name, "cert.pem")
        self.private_key = os.path.join(self.tempdir.name, "key.pem")
        for path in (self.certificate, self.private_key):
            with open(path, "w", encoding="utf-8") as file_obj:
                file_obj.write("test\n")
        os.chmod(self.private_key, 0o640)

    @staticmethod
    def _openssl_result(arguments: tuple[str, ...], *, expires: str = "Sep  8 12:00:00 2026 GMT"):
        from subprocess import CompletedProcess

        if "-enddate" in arguments:
            return CompletedProcess(
                arguments,
                0,
                f"notAfter={expires}\nsha256 Fingerprint=AA:BB:CC\n",
                "",
            )
        return CompletedProcess(arguments, 0, "PUBLIC KEY\n", "")

    @patch("lib.xrdp_certificate._daemon_can_read", return_value=True)
    @patch("lib.xrdp_certificate._run_openssl")
    def test_healthy_matching_pair(self, mock_openssl, _mock_readable) -> None:
        mock_openssl.side_effect = lambda *args: self._openssl_result(args)

        health = inspect_xrdp_certificate_pair(
            self.certificate,
            self.private_key,
            now=datetime(2026, 8, 9, tzinfo=timezone.utc),
        )

        self.assertEqual(health.status, "ok")
        self.assertEqual(health.fingerprint, "aabbcc")
        self.assertIsNone(health.issue)

    @patch("lib.xrdp_certificate._daemon_can_read", return_value=True)
    @patch("lib.xrdp_certificate._run_openssl")
    def test_expiring_pair_is_warning(self, mock_openssl, _mock_readable) -> None:
        mock_openssl.side_effect = lambda *args: self._openssl_result(
            args, expires="Aug 20 12:00:00 2026 GMT"
        )

        health = inspect_xrdp_certificate_pair(
            self.certificate,
            self.private_key,
            now=datetime(2026, 8, 9, tzinfo=timezone.utc),
        )

        self.assertEqual(health.status, "warning")
        self.assertIn("expires within 30 days", health.issue or "")

    @patch("lib.xrdp_certificate._daemon_can_read", return_value=True)
    @patch("lib.xrdp_certificate._run_openssl")
    def test_mismatched_pair_is_error(self, mock_openssl, _mock_readable) -> None:
        def result(*args):
            from subprocess import CompletedProcess

            if "-enddate" in args:
                return self._openssl_result(args)
            output = "CERTIFICATE KEY\n" if args[0] == "x509" else "PRIVATE KEY\n"
            return CompletedProcess(args, 0, output, "")

        mock_openssl.side_effect = result

        health = inspect_xrdp_certificate_pair(
            self.certificate,
            self.private_key,
            now=datetime(2026, 8, 9, tzinfo=timezone.utc),
        )

        self.assertEqual(health.status, "error")
        self.assertIn("do not match", health.issue or "")

    @patch("lib.xrdp_certificate._daemon_can_read", return_value=True)
    @patch("lib.xrdp_certificate._run_openssl")
    def test_world_readable_private_key_is_error(self, mock_openssl, _mock_readable) -> None:
        mock_openssl.side_effect = lambda *args: self._openssl_result(args)
        os.chmod(self.private_key, 0o644)

        health = inspect_xrdp_certificate_pair(
            self.certificate,
            self.private_key,
            now=datetime(2026, 8, 9, tzinfo=timezone.utc),
        )

        self.assertEqual(health.status, "error")
        self.assertIn("permissions are too broad", health.issue or "")

    def test_missing_pair_is_error(self) -> None:
        health = inspect_xrdp_certificate_pair(
            os.path.join(self.tempdir.name, "missing-cert.pem"),
            os.path.join(self.tempdir.name, "missing-key.pem"),
        )

        self.assertEqual(health.status, "error")
        self.assertEqual(len(health.details), 2)

    def test_missing_xrdp_configuration_is_not_configured(self) -> None:
        health = inspect_xrdp_certificate(
            os.path.join(self.tempdir.name, "missing-xrdp.ini")
        )

        self.assertEqual(health.status, "not_configured")


if __name__ == "__main__":
    unittest.main()
