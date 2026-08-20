"""Security tests for shared release installation helpers."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from lib.release_management import (
    install_binary_release,
    validate_release_download_url,
    validate_release_sha256_digest,
    validate_release_tag,
)


class TestReleaseValidation(unittest.TestCase):
    def test_release_tag_is_safe_as_path_component(self):
        self.assertEqual(validate_release_tag("v1.2.3-rc.1"), "v1.2.3-rc.1")
        for invalid in ("../../etc", "release/name", "v1\nnext", "", "."):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_release_tag(invalid)

    def test_release_download_requires_credential_free_https(self):
        self.assertEqual(
            validate_release_download_url("https://example.test/release"),
            "https://example.test/release",
        )
        for invalid in (
            "http://example.test/release",
            "https://token@example.test/release",
            "file:///tmp/release",
            "",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_release_download_url(invalid)

    def test_release_sha256_digest_is_strict_and_normalized(self):
        self.assertEqual(
            validate_release_sha256_digest(f"sha256:{'A' * 64}"),
            "a" * 64,
        )
        for invalid in ("a" * 64, "sha512:" + "a" * 64, "sha256:bad", ""):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_release_sha256_digest(invalid)

    @patch("lib.release_management.run")
    def test_binary_name_cannot_escape_private_download_directory(self, mock_run):
        with self.assertRaisesRegex(ValueError, "Invalid release binary name"):
            install_binary_release(
                binary_name="../escape",
                binary_path="/usr/local/bin/example",
                tag_name="v1.0.0",
                download_url="https://example.test/release",
                installed_tag=None,
                persist_installed_tag=MagicMock(),
            )

        mock_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
