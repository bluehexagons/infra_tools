"""Tests for desktop.browser_steps helper behavior."""

from __future__ import annotations

import os
import sys
import subprocess
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from desktop.browser_steps import is_flatpak_app_installed


class TestBrowserSteps(unittest.TestCase):
    @patch("desktop.browser_steps.subprocess.run")
    def test_flatpak_app_detection_uses_argument_list(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["flatpak"],
            returncode=0,
            stdout="org.mozilla.firefox\n",
            stderr="",
        )
        self.assertTrue(is_flatpak_app_installed("org.mozilla.firefox"))
        mock_run.assert_called_once_with(
            ["flatpak", "list", "--app", "--columns=application"],
            capture_output=True,
            text=True,
        )

    @patch("desktop.browser_steps.subprocess.run")
    def test_flatpak_app_detection_handles_missing_app(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["flatpak"],
            returncode=0,
            stdout="org.mozilla.firefox\n",
            stderr="",
        )
        self.assertFalse(is_flatpak_app_installed("com.brave.Browser"))


if __name__ == "__main__":
    unittest.main()
