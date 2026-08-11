"""Tests for Go runtime setup."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from unittest.mock import mock_open, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import common.common_steps as common_steps
from lib.config import SetupConfig


def _make_config() -> SetupConfig:
    return SetupConfig(host="testhost", username="testuser", system_type="server_lite")


class TestInstallGo(unittest.TestCase):
    def test_go_release_arch_maps_supported_machines(self):
        self.assertEqual(common_steps._go_release_arch("x86_64"), "amd64")
        self.assertEqual(common_steps._go_release_arch("aarch64"), "arm64")
        self.assertEqual(common_steps._go_release_arch("armv7l"), "armv6l")
        self.assertEqual(common_steps._go_release_arch("riscv64"), "riscv64")
        self.assertIsNone(common_steps._go_release_arch("mips64"))

    def test_skips_reinstall_when_usr_local_go_is_current(self):
        commands: list[str] = []

        def fake_run(command: str, **kwargs):
            commands.append(command)
            if "VERSION?m=text" in command:
                return subprocess.CompletedProcess(command, 0, stdout="go1.22.3\n", stderr="")
            if command == "/usr/local/go/bin/go version":
                return subprocess.CompletedProcess(command, 0, stdout="go version go1.22.3 linux/amd64\n", stderr="")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with patch("common.common_steps.os.path.exists", return_value=True), \
             patch("common.common_steps.run", side_effect=fake_run):
            common_steps.install_go(_make_config())

        self.assertNotIn("rm -rf /usr/local/go", commands)
        self.assertFalse(any(command.startswith("wget -q https://go.dev/dl/") for command in commands))

    def test_reinstalls_when_usr_local_go_is_outdated(self):
        commands: list[str] = []

        def fake_run(command: str, **kwargs):
            commands.append(command)
            if "VERSION?m=text" in command:
                return subprocess.CompletedProcess(command, 0, stdout="go1.22.3\n", stderr="")
            if command == "/usr/local/go/bin/go version":
                return subprocess.CompletedProcess(command, 0, stdout="go version go1.21.0 linux/amd64\n", stderr="")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with patch("common.common_steps.os.path.exists", return_value=True), \
             patch("common.common_steps.run", side_effect=fake_run), \
             patch("common.common_steps.open", mock_open()), \
             patch("common.common_steps.shutil.which", return_value=None):
            common_steps.install_go(_make_config())

        self.assertIn("rm -rf /usr/local/go", commands)
        self.assertTrue(any(command.startswith("wget -q https://go.dev/dl/go1.22.3") for command in commands))

    def test_reinstalls_with_native_arm64_archive(self):
        commands: list[str] = []

        def fake_run(command: str, **kwargs):
            commands.append(command)
            if "VERSION?m=text" in command:
                return subprocess.CompletedProcess(command, 0, stdout="go1.22.3\n", stderr="")
            if command == "/usr/local/go/bin/go version":
                return subprocess.CompletedProcess(command, 0, stdout="go version go1.21.0 linux/amd64\n", stderr="")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with patch("common.common_steps.platform.machine", return_value="aarch64"), \
             patch("common.common_steps.os.path.exists", return_value=True), \
             patch("common.common_steps.run", side_effect=fake_run), \
             patch("common.common_steps.open", mock_open()), \
             patch("common.common_steps.shutil.which", return_value=None):
            common_steps.install_go(_make_config())

        self.assertTrue(any("go1.22.3.linux-arm64.tar.gz" in command for command in commands))


if __name__ == "__main__":
    unittest.main()
