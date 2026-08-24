"""Tests for setup summary security-policy output."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout

from lib.config import SetupConfig
from lib.display import (
    print_rdp_info,
    print_service_access_summary,
    print_setup_summary,
)


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

    def test_access_summary_lists_web_interfaces_and_services(self) -> None:
        config = SetupConfig(
            host="192.168.0.41",
            username="agent",
            system_type="server_web",
            agent_tools=["codex"],
            web_interfaces=["t3code"],
            web_interface_sources=["192.168.0.0/24"],
            device_pairing_providers=["t3code"],
            gogs=["git.example.com:3000", "/srv/gogs"],
            antistatic_server="lobby.example.com",
            antistatic_db=":8081",
            enable_rdp=True,
            enable_samba=True,
        )

        output = io.StringIO()
        with redirect_stdout(output):
            print_service_access_summary(config)

        rendered = output.getvalue()
        self.assertIn(
            "T3 Code (HTTPS): see the HTTPS endpoint printed by target setup",
            rendered,
        )
        self.assertIn(
            "T3 Code HTTP compatibility: port 3773",
            rendered,
        )
        self.assertIn(
            "T3 Code device pairing (HTTPS): see the HTTPS endpoint printed by target setup",
            rendered,
        )
        self.assertIn(
            "T3 Code device-pairing HTTP compatibility: port 3774",
            rendered,
        )
        self.assertNotIn("http://192.168.0.41:3773/", rendered)
        self.assertNotIn("http://192.168.0.41:3774/", rendered)
        self.assertIn("Gogs web: http://git.example.com/", rendered)
        self.assertIn("Gogs Git over SSH: git@git.example.com", rendered)
        self.assertIn("TCP 22", rendered)
        self.assertIn("Antistatic lobby: http://lobby.example.com/", rendered)
        self.assertIn("Antistatic DB: http://192.168.0.41:8081/", rendered)
        self.assertIn("RDP: 192.168.0.41:3389", rendered)
        self.assertIn("Samba/SMB: //192.168.0.41", rendered)

    def test_access_summary_marks_loopback_web_interfaces(self) -> None:
        config = SetupConfig(
            host="agent-vm",
            username="agent",
            system_type="server_dev",
            agent_tools=["codex"],
            web_interfaces=["t3code"],
        )

        output = io.StringIO()
        with redirect_stdout(output):
            print_service_access_summary(config)

        rendered = output.getvalue()
        self.assertIn(
            "T3 Code (HTTPS): see the HTTPS endpoint printed by target setup",
            rendered,
        )
        self.assertIn(
            "T3 Code HTTP compatibility: port 3773",
            rendered,
        )
        self.assertNotIn("http://127.0.0.1:3773/", rendered)
        self.assertIn("loopback-only, use an SSH tunnel", rendered)
        self.assertIn(
            "T3 Code pairing: infra-tools agent web pair agent-vm agent",
            rendered,
        )

    def test_access_summary_lists_managed_godot_https_origin(self) -> None:
        config = SetupConfig(
            host="192.168.0.42",
            username="agent",
            system_type="agent_vm",
            godot_bundles=["web"],
        )

        output = io.StringIO()
        with redirect_stdout(output):
            print_service_access_summary(config)

        rendered = output.getvalue()
        self.assertIn(
            "Godot web exports: https://192.168.0.42:8443/games/agent/",
            rendered,
        )
        self.assertIn("godot-web-publish GAME_NAME", rendered)


if __name__ == "__main__":
    unittest.main()
