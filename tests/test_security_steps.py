"""Tests for security.security_steps auto-update configuration."""

from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import mock_open, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.config import SetupConfig
from lib.system_types import get_steps_for_system_type
from security.security_steps import configure_auto_updates, configure_cleanup_maintenance


class TestConfigureAutoUpdates(unittest.TestCase):
    @patch("security.security_steps.run")
    @patch("security.security_steps.cleanup_service")
    @patch("security.security_steps.open", new_callable=mock_open)
    @patch("security.security_steps.os.path.exists", return_value=False)
    def test_creates_systemd_service_and_timer(self, _exists, mock_file, _cleanup, mock_run):
        mock_run.return_value = SimpleNamespace(returncode=0)
        configure_auto_updates(SetupConfig(username="u", host="h", system_type="server_lite"))

        opened_paths = [args[0] for args, _ in mock_file.call_args_list]
        self.assertIn("/etc/systemd/system/auto-update-apt.service", opened_paths)
        self.assertIn("/etc/systemd/system/auto-update-apt.timer", opened_paths)

    @patch("security.security_steps.run")
    @patch("security.security_steps.cleanup_service")
    @patch("security.security_steps.open", new_callable=mock_open)
    @patch("security.security_steps.os.path.exists", return_value=False)
    def test_enables_and_starts_timer(self, _exists, mock_file, _cleanup, mock_run):
        mock_run.return_value = SimpleNamespace(returncode=0)
        configure_auto_updates(SetupConfig(username="u", host="h", system_type="server_lite"))

        run_commands = [args[0] for args, _ in mock_run.call_args_list]
        self.assertIn("systemctl daemon-reload", run_commands)
        self.assertIn("systemctl enable auto-update-apt.timer", run_commands)
        self.assertIn("systemctl start auto-update-apt.timer", run_commands)

    @patch("security.security_steps.run")
    @patch("security.security_steps.cleanup_service")
    @patch("security.security_steps.open", new_callable=mock_open)
    @patch("security.security_steps.os.path.exists", return_value=False)
    def test_service_references_auto_update_apt_script(self, _exists, mock_file, _cleanup, mock_run):
        mock_run.return_value = SimpleNamespace(returncode=0)
        configure_auto_updates(SetupConfig(username="u", host="h", system_type="server_lite"))

        written_text = "".join(call.args[0] for call in mock_file().write.call_args_list)
        self.assertIn("/opt/infra_tools/common/service_tools/auto_update_apt.py", written_text)
        # No hardcoded origins should be present
        self.assertNotIn("distro_id", written_text)
        self.assertNotIn("distro_codename", written_text)

    @patch("security.security_steps.run")
    @patch("security.security_steps.cleanup_service")
    @patch("security.security_steps.open", new_callable=mock_open)
    @patch("security.security_steps.os.path.exists", return_value=True)
    def test_cleans_up_legacy_unattended_upgrades(self, mock_exists, mock_file, _cleanup, mock_run):
        mock_run.return_value = SimpleNamespace(returncode=0)
        removed_paths = []
        with patch("security.security_steps.os.remove", side_effect=lambda p: removed_paths.append(p)):
            configure_auto_updates(SetupConfig(username="u", host="h", system_type="server_lite"))
        self.assertIn("/etc/apt/apt.conf.d/52infra-tools-unattended-upgrades", removed_paths)
        self.assertIn("/etc/infra_tools/unattended_upgrades_origins.list", removed_paths)

    @patch("security.security_steps.run")
    @patch("security.security_steps.cleanup_service")
    @patch("security.security_steps.open", new_callable=mock_open)
    @patch("security.security_steps.os.path.exists", return_value=False)
    def test_stops_and_disables_unattended_upgrades(self, _exists, mock_file, _cleanup, mock_run):
        mock_run.return_value = SimpleNamespace(returncode=0)
        configure_auto_updates(SetupConfig(username="u", host="h", system_type="server_lite"))

        run_commands = [args[0] for args, _ in mock_run.call_args_list]
        self.assertIn("systemctl stop unattended-upgrades", run_commands)
        self.assertIn("systemctl disable unattended-upgrades", run_commands)


class TestConfigureCleanupMaintenance(unittest.TestCase):
    @patch("security.security_steps.run")
    @patch("security.security_steps.cleanup_service")
    @patch("security.security_steps.open", new_callable=mock_open)
    @patch("security.security_steps.os.makedirs")
    def test_creates_service_timer_and_journal_limit(self, mock_makedirs, mock_file, _cleanup, mock_run):
        mock_run.return_value = SimpleNamespace(returncode=0)
        configure_cleanup_maintenance(SetupConfig(username="u", host="h", system_type="server_lite"))

        mock_makedirs.assert_called_once_with("/etc/systemd/journald.conf.d", exist_ok=True)
        opened_paths = [args[0] for args, _ in mock_file.call_args_list]
        self.assertIn("/etc/systemd/journald.conf.d/infra-tools.conf", opened_paths)
        self.assertIn("/etc/systemd/system/cleanup-maintenance.service", opened_paths)
        self.assertIn("/etc/systemd/system/cleanup-maintenance.timer", opened_paths)

    @patch("security.security_steps.run")
    @patch("security.security_steps.cleanup_service")
    @patch("security.security_steps.open", new_callable=mock_open)
    @patch("security.security_steps.os.makedirs")
    def test_enables_timer_and_restarts_journald(self, _makedirs, mock_file, _cleanup, mock_run):
        mock_run.return_value = SimpleNamespace(returncode=0)
        configure_cleanup_maintenance(SetupConfig(username="u", host="h", system_type="server_lite"))

        run_commands = [args[0] for args, _ in mock_run.call_args_list]
        self.assertIn("systemctl daemon-reload", run_commands)
        self.assertIn("systemctl restart systemd-journald", run_commands)
        self.assertIn("systemctl enable cleanup-maintenance.timer", run_commands)
        self.assertIn("systemctl start cleanup-maintenance.timer", run_commands)

    @patch("security.security_steps.run")
    @patch("security.security_steps.cleanup_service")
    @patch("security.security_steps.open", new_callable=mock_open)
    @patch("security.security_steps.os.makedirs")
    def test_service_references_cleanup_script_and_100m_journal_limit(self, _makedirs, mock_file, _cleanup, mock_run):
        mock_run.return_value = SimpleNamespace(returncode=0)
        configure_cleanup_maintenance(SetupConfig(username="u", host="h", system_type="server_lite"))

        written_text = "".join(call.args[0] for call in mock_file().write.call_args_list)
        self.assertIn("/opt/infra_tools/common/service_tools/cleanup_maintenance.py", written_text)
        self.assertIn("OnCalendar=Sun *-*-* 03:30:00", written_text)
        self.assertIn("SystemMaxUse=100M", written_text)
        self.assertIn("RuntimeMaxUse=100M", written_text)


class TestCleanupMaintenanceStepWiring(unittest.TestCase):
    def test_server_lite_includes_cleanup_maintenance_step(self):
        config = SetupConfig(username="u", host="h", system_type="server_lite")
        step_names = [name for name, _ in get_steps_for_system_type(config)]
        self.assertIn("Configuring cleanup maintenance service", step_names)

    def test_server_proxmox_includes_cleanup_maintenance_step(self):
        config = SetupConfig(username="u", host="h", system_type="server_proxmox")
        step_names = [name for name, _ in get_steps_for_system_type(config)]
        self.assertIn("Configuring cleanup maintenance service", step_names)


if __name__ == "__main__":
    unittest.main()
