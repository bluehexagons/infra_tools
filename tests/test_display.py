"""Tests for setup summary security-policy output."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout

from lib.config import SetupConfig
from lib.display import print_rdp_info, print_setup_summary


class TestRdpDisplay(unittest.TestCase):
    def test_setup_summary_makes_global_exposure_visible(self) -> None:
        config = SetupConfig(
            host="agent-vm",
            username="agent",
            system_type="workstation_dev",
            enable_rdp=True,
        )

        output = io.StringIO()
        with redirect_stdout(output):
            print_setup_summary(config)

        rendered = output.getvalue()
        self.assertIn("RDP bind address: 0.0.0.0", rendered)
        self.assertIn("RDP allowed sources: global (rate-limited", rendered)
        self.assertIn("RDP enabled channels: dynamic-resize, clipboard", rendered)
        self.assertIn("RDP maximum sessions: 10", rendered)
        self.assertIn("RDP disconnected session retention: unlimited", rendered)
        self.assertIn("RDP idle disconnect: disabled", rendered)

    def test_setup_summary_shows_restricted_sources_and_opt_in_channels(self) -> None:
        config = SetupConfig(
            host="agent-vm",
            username="agent",
            system_type="workstation_dev",
            enable_rdp=True,
            rdp_bind_address="10.0.0.25",
            rdp_allowed_sources=["10.0.0.0/24", "100.64.0.0/10"],
            rdp_clipboard=False,
            rdp_drive_redirection=True,
            rdp_audio=True,
            rdp_max_sessions=2,
            rdp_kill_disconnected=True,
            rdp_disconnected_timeout=86400,
            rdp_idle_timeout=14400,
        )

        output = io.StringIO()
        with redirect_stdout(output):
            print_setup_summary(config)

        rendered = output.getvalue()
        self.assertIn("RDP bind address: 10.0.0.25", rendered)
        self.assertIn("RDP allowed sources: 10.0.0.0/24, 100.64.0.0/10", rendered)
        self.assertIn("RDP enabled channels: dynamic-resize, drive/device, audio", rendered)
        self.assertIn("RDP maximum sessions: 2", rendered)
        self.assertIn("RDP disconnected session retention: 86400 seconds", rendered)
        self.assertIn("RDP idle disconnect: 14400 seconds", rendered)

    def test_connection_info_repeats_the_effective_boundary(self) -> None:
        config = SetupConfig(
            host="agent-vm",
            username="agent",
            system_type="workstation_dev",
            enable_rdp=True,
            rdp_allowed_sources=["10.0.0.0/24"],
        )

        output = io.StringIO()
        with redirect_stdout(output):
            print_rdp_info(config)

        self.assertIn("Allowed sources: 10.0.0.0/24", output.getvalue())

    def test_setup_summary_shows_t3_sources_and_backup_jobs(self) -> None:
        config = SetupConfig(
            host="agent-vm",
            username="agent",
            system_type="server_dev",
            agent_tools=["codex"],
            web_interfaces=["t3code"],
            web_interface_sources=["192.168.0.0/24"],
            backup_specs=[["/srv/workspace", "/srv/backups/workspace", "daily"]],
        )

        output = io.StringIO()
        with redirect_stdout(output):
            print_setup_summary(config)

        rendered = output.getvalue()
        self.assertIn("Web interface sources: 192.168.0.0/24", rendered)
        self.assertIn("Backup Jobs: 1 job(s)", rendered)
        self.assertIn("/srv/workspace → /srv/backups/workspace (daily)", rendered)


if __name__ == "__main__":
    unittest.main()
