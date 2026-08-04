"""Tests for security.security_steps auto-update configuration."""

from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import mock_open, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.config import SetupConfig
from lib.maintenance_defaults import JOURNAL_MAX_USE
from lib.system_types import get_steps_for_system_type
from security.security_steps import (
    configure_auto_restart,
    configure_auto_updates,
    configure_cleanup_maintenance,
    configure_fail2ban,
    configure_firewall,
    configure_security_monitor,
    harden_kernel,
    harden_ssh,
)


class TestHardenSSH(unittest.TestCase):
    @patch("security.security_steps.run")
    @patch("security.security_steps.os.makedirs")
    @patch("security.security_steps.open", new_callable=mock_open)
    @patch("security.security_steps.os.path.exists", return_value=False)
    def test_writes_dropin_with_hardening_directives(self, _exists, mock_file, _md, mock_run):
        mock_run.return_value = SimpleNamespace(returncode=0)
        harden_ssh(SetupConfig(username="u", host="h", system_type="server_lite"))

        opened_paths = [args[0] for args, _ in mock_file.call_args_list]
        self.assertIn("/etc/ssh/sshd_config.d/99-infra-tools-hardening.conf", opened_paths)
        written = "".join(call.args[0] for call in mock_file().write.call_args_list)
        for directive in (
            "PermitRootLogin prohibit-password",
            "PasswordAuthentication no",
            "MaxAuthTries 3",
            "AllowGroups remoteusers",
            "ClientAliveInterval 300",
        ):
            self.assertIn(directive, written)

    @patch("security.security_steps.run")
    @patch("security.security_steps.os.makedirs")
    @patch("security.security_steps.open", new_callable=mock_open)
    @patch("security.security_steps.os.path.exists", return_value=False)
    def test_validates_sshd_before_reload(self, _exists, _file, _md, mock_run):
        mock_run.return_value = SimpleNamespace(returncode=0)
        harden_ssh(SetupConfig(username="u", host="h", system_type="server_lite"))
        run_commands = [args[0] for args, _ in mock_run.call_args_list]
        self.assertIn("sshd -t", run_commands)
        self.assertTrue(any(cmd.startswith("systemctl reload sshd") for cmd in run_commands))

    @patch("security.security_steps.run")
    @patch("security.security_steps.os.makedirs")
    @patch("security.security_steps.open", new_callable=mock_open)
    @patch("security.security_steps.os.path.exists", return_value=False)
    def test_skips_reload_when_validation_fails(self, _exists, _file, _md, mock_run):
        mock_run.return_value = SimpleNamespace(returncode=1)
        harden_ssh(SetupConfig(username="u", host="h", system_type="server_lite"))
        run_commands = [args[0] for args, _ in mock_run.call_args_list]
        self.assertIn("sshd -t", run_commands)
        self.assertFalse(any(cmd.startswith("systemctl reload sshd") for cmd in run_commands))


class TestHardenKernel(unittest.TestCase):
    @patch("security.security_steps.can_modify_kernel", return_value=True)
    @patch("security.security_steps.run")
    @patch("security.security_steps.open", new_callable=mock_open)
    @patch("security.security_steps.os.path.exists", return_value=False)
    def test_writes_sysctl_file_with_modern_protections(self, _exists, mock_file, mock_run, _ckm):
        mock_run.return_value = SimpleNamespace(returncode=0)
        harden_kernel(SetupConfig(username="u", host="h", system_type="server_lite"))
        written = "".join(call.args[0] for call in mock_file().write.call_args_list)
        for directive in (
            "kernel.kptr_restrict=2",
            "kernel.unprivileged_bpf_disabled=1",
            "fs.protected_symlinks=1",
            "net.ipv4.tcp_syncookies=1",
        ):
            self.assertIn(directive, written)

    @patch("security.security_steps.can_modify_kernel", return_value=True)
    @patch("security.security_steps.run")
    @patch("security.security_steps.os.path.exists", return_value=True)
    def test_skips_when_existing_content_matches(self, _exists, mock_run, _ckm):
        # Read the bytes the function would write, then mock open() to return them.
        from security.security_steps import _SYSCTL_HARDENING_FILE  # noqa: F401
        # Import inside function to avoid leaking; we re-run the function once
        # to produce expected content.
        mock_run.return_value = SimpleNamespace(returncode=0)
        captured = {}
        m = mock_open()
        # First call: prime with the expected content by running once with non-existent file
        with patch("security.security_steps.os.path.exists", return_value=False), \
             patch("security.security_steps.open", m):
            harden_kernel(SetupConfig(username="u", host="h", system_type="server_lite"))
        expected = "".join(call.args[0] for call in m().write.call_args_list)

        m2 = mock_open(read_data=expected)
        with patch("security.security_steps.open", m2):
            harden_kernel(SetupConfig(username="u", host="h", system_type="server_lite"))
        # No write should have happened because content matched.
        self.assertEqual(m2().write.call_count, 0)
        captured["ok"] = True
        self.assertTrue(captured["ok"])


class TestConfigureFail2Ban(unittest.TestCase):
    @patch("security.security_steps.is_container", return_value=False)
    @patch("security.security_steps.run")
    @patch("security.security_steps.os.makedirs")
    @patch("security.security_steps.open", new_callable=mock_open)
    def test_writes_sshd_jail_when_rdp_disabled(self, mock_file, _md, mock_run, _ic):
        mock_run.return_value = SimpleNamespace(returncode=0)
        configure_fail2ban(SetupConfig(username="u", host="h", system_type="server_lite"))
        opened_paths = [args[0] for args, _ in mock_file.call_args_list]
        self.assertIn("/etc/fail2ban/jail.d/sshd.local", opened_paths)
        self.assertNotIn("/etc/fail2ban/jail.d/xrdp.local", opened_paths)

    @patch("security.security_steps.is_container", return_value=False)
    @patch("security.security_steps.run")
    @patch("security.security_steps.os.makedirs")
    @patch("security.security_steps.open", new_callable=mock_open)
    def test_writes_xrdp_jail_and_filter_when_rdp_enabled(self, mock_file, _md, mock_run, _ic):
        mock_run.return_value = SimpleNamespace(returncode=0)
        cfg = SetupConfig(username="u", host="h", system_type="workstation_dev")
        cfg.enable_rdp = True
        configure_fail2ban(cfg)
        opened_paths = [args[0] for args, _ in mock_file.call_args_list]
        self.assertIn("/etc/fail2ban/jail.d/sshd.local", opened_paths)
        self.assertIn("/etc/fail2ban/jail.d/xrdp.local", opened_paths)
        self.assertIn("/etc/fail2ban/filter.d/xrdp.conf", opened_paths)
        # The filter should target AUTHFAIL to avoid false positives on
        # informational connection lines.
        written = "".join(call.args[0] for call in mock_file().write.call_args_list)
        self.assertIn("AUTHFAIL", written)

    @patch("security.security_steps.is_container", return_value=True)
    def test_skipped_in_container(self, _ic):
        with patch("builtins.print") as mock_print:
            configure_fail2ban(SetupConfig(username="u", host="h", system_type="server_lite"))
        mock_print.assert_any_call("  ✓ Skipping fail2ban configuration (limited functionality in containers)")


class TestConfigureFirewall(unittest.TestCase):
    @patch("security.security_steps.is_container", return_value=False)
    @patch("security.security_steps.run")
    def test_rate_limits_ssh_and_rdp_when_rdp_enabled(self, mock_run, _ic):
        mock_run.return_value = SimpleNamespace(returncode=1)  # ufw not yet active
        cfg = SetupConfig(username="u", host="h", system_type="workstation_dev")
        cfg.enable_rdp = True
        configure_firewall(cfg)
        run_commands = [args[0] for args, _ in mock_run.call_args_list]
        self.assertIn("ufw limit ssh", run_commands)
        self.assertIn("ufw limit 3389/tcp", run_commands)
        self.assertNotIn("ufw allow 3389/tcp", run_commands)


class TestConfigureAutoUpdates(unittest.TestCase):
    @patch("security.security_steps.configure_maintenance_timer")
    @patch("security.security_steps.run")
    @patch("security.security_steps.os.path.exists", return_value=False)
    def test_configures_shared_systemd_timer(self, _exists, mock_run, mock_configure):
        mock_run.return_value = SimpleNamespace(returncode=0)
        configure_auto_updates(SetupConfig(username="u", host="h", system_type="server_lite"))

        mock_configure.assert_called_once_with(
            service_name="auto-update-apt",
            service_desc="Auto-update APT packages",
            timer_desc="Auto-update APT packages daily",
            script_path="/opt/infra_tools/common/service_tools/auto_update_apt.py",
            schedule="*-*-* 06:00:00",
            check_name="APT packages",
            purpose="auto-update",
        )

    @patch("security.security_steps.configure_maintenance_timer")
    @patch("security.security_steps.run")
    @patch("security.security_steps.os.path.exists", return_value=True)
    def test_cleans_up_legacy_unattended_upgrades(self, _exists, mock_run, _configure):
        mock_run.return_value = SimpleNamespace(returncode=0)
        removed_paths = []
        with patch("security.security_steps.os.remove", side_effect=lambda p: removed_paths.append(p)):
            configure_auto_updates(SetupConfig(username="u", host="h", system_type="server_lite"))
        self.assertIn("/etc/apt/apt.conf.d/52infra-tools-unattended-upgrades", removed_paths)
        self.assertIn("/etc/infra_tools/unattended_upgrades_origins.list", removed_paths)

    @patch("security.security_steps.configure_maintenance_timer")
    @patch("security.security_steps.run")
    @patch("security.security_steps.os.path.exists", return_value=False)
    def test_stops_and_disables_competing_apt_timers(self, _exists, mock_run, _configure):
        mock_run.return_value = SimpleNamespace(returncode=0)
        configure_auto_updates(SetupConfig(username="u", host="h", system_type="server_lite"))

        run_commands = [args[0] for args, _ in mock_run.call_args_list]
        for unit in (
            "unattended-upgrades.service",
            "apt-daily.timer",
            "apt-daily-upgrade.timer",
        ):
            self.assertIn(f"systemctl stop {unit}", run_commands)
            self.assertIn(f"systemctl disable {unit}", run_commands)


class TestConfigureMaintenanceTimers(unittest.TestCase):
    @patch("security.security_steps.configure_maintenance_timer")
    @patch("security.security_steps.is_hardware", return_value=False)
    @patch("security.security_steps.is_vm", return_value=True)
    def test_security_monitor_uses_shared_timer(self, _vm, _hardware, mock_configure):
        configure_security_monitor(SetupConfig(username="u", host="h", system_type="server_lite"))

        mock_configure.assert_called_once_with(
            service_name="security-monitor",
            service_desc="Security event monitor",
            timer_desc="Security event monitor (every 15 minutes)",
            script_path="/opt/infra_tools/security/service_tools/security_monitor.py",
            schedule="*:0/15",
            check_name="Security event monitor",
            randomized_delay="2min",
            timeout="10min",
            purpose="monitor",
        )

    @patch("security.security_steps.configure_maintenance_timer")
    @patch("security.security_steps.can_modify_kernel", return_value=True)
    def test_auto_restart_uses_shared_timer(self, _kernel, mock_configure):
        configure_auto_restart(SetupConfig(username="u", host="h", system_type="server_lite"))

        mock_configure.assert_called_once_with(
            service_name="auto-restart-if-needed",
            service_desc="Auto-restart system if needed",
            timer_desc="Auto-restart system if needed (daily at 2 AM)",
            script_path="/opt/infra_tools/common/service_tools/auto_restart_if_needed.py",
            schedule="*-*-* 02:00:00",
            on_boot_sec="30min",
            check_name="Automatic restart",
            randomized_delay="10min",
            timeout="10min",
            network_online=False,
            purpose="check",
        )

    @patch("security.security_steps.configure_maintenance_timer")
    @patch("security.security_steps.run")
    @patch("security.security_steps.open", new_callable=mock_open)
    @patch("security.security_steps.os.makedirs")
    def test_cleanup_sets_journal_limit_and_uses_shared_timer(
        self, mock_makedirs, mock_file, mock_run, mock_configure
    ):
        mock_run.return_value = SimpleNamespace(returncode=0)
        configure_cleanup_maintenance(SetupConfig(username="u", host="h", system_type="server_lite"))

        mock_makedirs.assert_called_once_with("/etc/systemd/journald.conf.d", exist_ok=True)
        mock_file.assert_called_once_with("/etc/systemd/journald.conf.d/infra-tools.conf", "w")
        written_text = "".join(call.args[0] for call in mock_file().write.call_args_list)
        self.assertIn(f"SystemMaxUse={JOURNAL_MAX_USE}", written_text)
        self.assertIn(f"RuntimeMaxUse={JOURNAL_MAX_USE}", written_text)
        mock_run.assert_called_once_with("systemctl restart systemd-journald", check=False)
        mock_configure.assert_called_once_with(
            service_name="cleanup-maintenance",
            service_desc="Cleanup temporary files and package caches",
            timer_desc="Cleanup temporary files and package caches (weekly)",
            script_path="/opt/infra_tools/common/service_tools/cleanup_maintenance.py",
            schedule="Sun *-*-* 03:30:00",
            check_name="Cleanup maintenance",
            randomized_delay="30min",
            timeout="1h",
            network_online=False,
            purpose="job",
        )


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
