"""Tests for shared Proxmox guest helpers."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.proxmox_guest import _build_guest_hostname, _wait_for_guest_ssh


class TestBuildGuestHostname(unittest.TestCase):
    def test_friendly_name_passthrough(self) -> None:
        self.assertEqual(
            _build_guest_hostname("10.0.0.50", "My Web Server", default_prefix="vm"),
            "my-web-server",
        )

    def test_default_prefix_rewrites_legacy_lxc_prefix(self) -> None:
        self.assertEqual(
            _build_guest_hostname("10.0.0.50", None, default_prefix="vm"),
            "vm-10-0-0-50",
        )
        self.assertEqual(
            _build_guest_hostname("10.0.0.50", None),
            "guest-10-0-0-50",
        )


class TestWaitForGuestSsh(unittest.TestCase):
    @patch("lib.proxmox_guest._ssh_run")
    def test_returns_when_probe_succeeds(self, mock_run) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="READY\n", stderr="")

        _wait_for_guest_ssh("10.0.0.50", "10.0.0.1", "root", [], timeout=3)

        mock_run.assert_called_once()

    @patch("lib.proxmox_guest._ssh_run")
    def test_dry_run_skips_probe(self, mock_run) -> None:
        _wait_for_guest_ssh("10.0.0.50", "10.0.0.1", "root", [], dry_run=True)
        mock_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
