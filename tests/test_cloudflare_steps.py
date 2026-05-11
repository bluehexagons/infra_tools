"""Tests for web/cloudflare_steps.py."""

from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import call, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.config import SetupConfig
from web.cloudflare_steps import configure_cloudflare_firewall


def _make_config(antistatic_server: str | None = None) -> SetupConfig:
    return SetupConfig(
        host="example-host",
        username="alice",
        system_type="server_web",
        enable_cloudflare=True,
        antistatic_server=antistatic_server,
    )


class TestConfigureCloudflareFirewall(unittest.TestCase):
    @patch("web.cloudflare_steps.run")
    def test_domain_antistatic_keeps_stun_direct_access(self, mock_run):
        mock_run.return_value = SimpleNamespace(returncode=0)

        configure_cloudflare_firewall(_make_config("lobby.example.com"))

        mock_run.assert_has_calls(
            [
                call("ufw status 2>/dev/null | grep -q 'Status: active'", check=False),
                call("ufw default deny incoming"),
                call("ufw default allow outgoing"),
                call("ufw allow ssh"),
                call("ufw delete allow 80/tcp", check=False),
                call("ufw delete allow 443/tcp", check=False),
                call("ufw delete allow 80", check=False),
                call("ufw delete allow 443", check=False),
                call("ufw allow 3478/udp comment 'antistatic STUN'", check=False),
                call("ufw --force enable"),
            ]
        )
        commands = [call_args.args[0] for call_args in mock_run.call_args_list]
        self.assertNotIn("ufw allow 8080/tcp comment 'antistatic direct port'", commands)

    @patch("web.cloudflare_steps.run")
    def test_hostless_antistatic_keeps_direct_tcp_and_stun_access(self, mock_run):
        mock_run.return_value = SimpleNamespace(returncode=0)

        configure_cloudflare_firewall(_make_config(":8080"))

        mock_run.assert_has_calls(
            [
                call("ufw status 2>/dev/null | grep -q 'Status: active'", check=False),
                call("ufw default deny incoming"),
                call("ufw default allow outgoing"),
                call("ufw allow ssh"),
                call("ufw delete allow 80/tcp", check=False),
                call("ufw delete allow 443/tcp", check=False),
                call("ufw delete allow 80", check=False),
                call("ufw delete allow 443", check=False),
                call("ufw allow 8080/tcp comment 'antistatic direct port'", check=False),
                call("ufw allow 3478/udp comment 'antistatic STUN'", check=False),
                call("ufw --force enable"),
            ]
        )


if __name__ == "__main__":
    unittest.main()
