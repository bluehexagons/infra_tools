"""Tests for security.security_steps auto-update configuration."""

from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import mock_open, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.config import SetupConfig
from security.security_steps import configure_auto_updates, ensure_unattended_upgrade_origin


class TestConfigureAutoUpdates(unittest.TestCase):
    @patch("security.security_steps.run")
    @patch("security.security_steps.is_service_active", return_value=True)
    @patch(
        "security.security_steps.os.path.exists",
        side_effect=lambda p: p in {"/etc/apt/apt.conf.d/20auto-upgrades", "/etc/apt/apt.conf.d/52infra-tools-unattended-upgrades"},
    )
    def test_already_configured(self, _exists, _active, mock_run):
        configure_auto_updates(SetupConfig(username="u", host="h", system_type="server_lite"))
        mock_run.assert_not_called()

    @patch("security.security_steps.open", new_callable=mock_open)
    @patch(
        "security.security_steps.run",
        side_effect=[
            SimpleNamespace(returncode=0),  # apt-get install unattended-upgrades
            SimpleNamespace(returncode=0),  # systemctl enable unattended-upgrades
            SimpleNamespace(returncode=0),  # systemctl start unattended-upgrades
        ],
    )
    @patch("security.security_steps.is_service_active", return_value=False)
    @patch("security.security_steps.os.path.exists", return_value=False)
    def test_writes_base_origins_config(self, _exists, _active, mock_run, mock_file):
        configure_auto_updates(SetupConfig(username="u", host="h", system_type="server_lite"))

        opened_paths = [args[0] for args, _ in mock_file.call_args_list]
        self.assertIn("/etc/apt/apt.conf.d/20auto-upgrades", opened_paths)
        self.assertIn("/etc/apt/apt.conf.d/52infra-tools-unattended-upgrades", opened_paths)

        run_commands = [args[0] for args, _ in mock_run.call_args_list]
        self.assertIn("systemctl enable unattended-upgrades", run_commands)
        self.assertIn("systemctl start unattended-upgrades", run_commands)

        written_text = "".join(call.args[0] for call in mock_file().write.call_args_list)
        self.assertIn("origin=${distro_id},codename=${distro_codename}", written_text)
        self.assertNotIn("origin=packages.microsoft.com", written_text)
        self.assertNotIn("origin=Brave Software", written_text)

    @patch("security.security_steps._load_managed_unattended_origins", return_value=["packages.microsoft.com", "Brave Software"])
    @patch("security.security_steps.open", new_callable=mock_open)
    @patch(
        "security.security_steps.run",
        side_effect=[
            SimpleNamespace(returncode=0),
            SimpleNamespace(returncode=0),
            SimpleNamespace(returncode=0),
        ],
    )
    @patch("security.security_steps.is_service_active", return_value=False)
    @patch("security.security_steps.os.path.exists", return_value=False)
    def test_writes_optional_origins_when_managed(self, _exists, _active, _run, mock_file, _managed):
        configure_auto_updates(SetupConfig(username="u", host="h", system_type="server_lite"))
        written_text = "".join(call.args[0] for call in mock_file().write.call_args_list)
        self.assertIn("origin=packages.microsoft.com", written_text)
        self.assertIn("origin=Brave Software", written_text)


class TestEnsureUnattendedUpgradeOrigin(unittest.TestCase):
    BASE_ORIGINS_CONTENT = """Unattended-Upgrade::Origins-Pattern {
        "origin=${distro_id},codename=${distro_codename}";
};
"""

    @patch("security.security_steps.open", new_callable=mock_open, read_data=BASE_ORIGINS_CONTENT)
    @patch("security.security_steps._store_managed_unattended_origin")
    @patch("security.security_steps.os.path.exists", return_value=True)
    def test_adds_missing_origin(self, _exists, _store, mock_file):
        ensure_unattended_upgrade_origin("packages.microsoft.com")
        _store.assert_called_once_with("packages.microsoft.com")
        written_text = "".join(call.args[0] for call in mock_file().write.call_args_list)
        self.assertIn('"origin=packages.microsoft.com";', written_text)


if __name__ == "__main__":
    unittest.main()
