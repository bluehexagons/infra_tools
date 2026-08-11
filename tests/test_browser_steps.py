"""Tests for desktop.browser_steps helper behavior."""

from __future__ import annotations

import os
import sys
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from desktop.browser_steps import (
    _browsh_architecture,
    _browsh_asset_matches,
    install_single_browser,
    is_flatpak_app_installed,
)


class TestBrowserSteps(unittest.TestCase):
    @patch("desktop.browser_steps.run")
    def test_browsh_architecture_maps_debian_armhf(self, mock_run):
        mock_run.return_value = SimpleNamespace(
            returncode=0, stdout="armhf\n", stderr=""
        )

        self.assertEqual(_browsh_architecture(), "armv7")

    def test_browsh_asset_match_uses_release_tag_and_architecture(self):
        self.assertTrue(
            _browsh_asset_matches(
                "v1.8.2", "browsh_1.8.2_linux_arm64.deb", "arm64"
            )
        )
        self.assertFalse(
            _browsh_asset_matches(
                "v1.8.3", "browsh_1.8.2_linux_arm64.deb", "arm64"
            )
        )

    @patch("desktop.browser_steps.shutil.which", return_value="")
    @patch("desktop.browser_steps.is_package_installed", return_value=False)
    @patch(
        "desktop.browser_steps._resolve_browsh_deb",
        return_value=("v1.8.2", "https://example.test/browsh_1.8.2_linux_amd64.deb"),
    )
    @patch("desktop.browser_steps.run")
    def test_browsh_resolves_current_architectural_release(
        self, mock_run, _resolve, _installed, _which
    ):
        mock_run.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")

        install_single_browser("browsh", use_flatpak=False)

        commands = [call.args[0] for call in mock_run.call_args_list]
        self.assertIn(
            "https://example.test/browsh_1.8.2_linux_amd64.deb",
            commands[1],
        )
        self.assertNotIn("v1.8.0", " ".join(commands))
        self.assertIn("apt-get install -y -qq /tmp/browsh.deb", commands)

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
