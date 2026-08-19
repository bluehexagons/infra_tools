"""Tests for the Cloudflare Tunnel provisioning helper."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from web.service_tools import setup_cloudflare_tunnel as tunnel_setup


class TestCloudflareTunnelState(unittest.TestCase):
    def test_malformed_state_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, "tunnel-state.json")
            with open(state_path, "w", encoding="utf-8") as state_file:
                state_file.write("not-json")
            with patch.object(tunnel_setup, "STATE_FILE", state_path):
                with self.assertRaisesRegex(ValueError, "Could not load"):
                    tunnel_setup.load_state()

    def test_generated_yaml_quotes_values_and_validates_hosts(self):
        content = tunnel_setup.generate_config_yml(
            {
                "name": "infra-tools",
                "id": "tunnel-id",
                "credentials_file": "/etc/cloudflared/tunnel.json",
            },
            [{"hostname": "example.com", "service": "http://localhost:80"}],
        )
        self.assertIn('tunnel: "tunnel-id"', content)
        self.assertIn('credentials-file: "/etc/cloudflared/tunnel.json"', content)
        self.assertIn('hostname: "example.com"', content)

        with self.assertRaisesRegex(ValueError, "Invalid tunnel hostname"):
            tunnel_setup.generate_config_yml(
                {
                    "id": "tunnel-id",
                    "credentials_file": "/etc/cloudflared/tunnel.json",
                },
                [{"hostname": "bad;hostname", "service": "http://localhost:80"}],
            )

    def test_discovery_deduplicates_and_skips_invalid_hosts(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "site.conf"), "w", encoding="utf-8") as config:
                config.write(
                    "server_name example.com example.com invalid_host _;\n"
                )
            with patch.object(tunnel_setup, "NGINX_SITES_DIR", tmp):
                sites = tunnel_setup.discover_nginx_sites()
        self.assertEqual(
            sites,
            [{"hostname": "example.com", "service": "http://localhost:80"}],
        )


class TestCloudflareTunnelRefresh(unittest.TestCase):
    def test_non_interactive_refresh_writes_validated_config_and_checks_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = os.path.join(tmp, "cloudflared")
            nginx_dir = os.path.join(tmp, "sites-enabled")
            os.makedirs(nginx_dir)
            with open(os.path.join(nginx_dir, "site.conf"), "w", encoding="utf-8") as config:
                config.write("server_name example.com;\n")
            credentials = os.path.join(config_dir, "tunnel.json")
            os.makedirs(config_dir)
            with open(credentials, "w", encoding="utf-8") as credential_file:
                credential_file.write("{}")
            state_path = os.path.join(config_dir, "tunnel-state.json")
            with open(state_path, "w", encoding="utf-8") as state_file:
                json.dump(
                    {
                        "tunnel": {
                            "name": "infra-tools",
                            "id": "tunnel-id",
                            "credentials_file": credentials,
                        },
                        "sites": [],
                    },
                    state_file,
                )

            command_results = [
                SimpleNamespace(returncode=0, stdout="", stderr=""),
                SimpleNamespace(returncode=0, stdout="", stderr=""),
            ]
            with patch.object(tunnel_setup, "STATE_FILE", state_path), \
                    patch.object(tunnel_setup, "CONFIG_DIR", config_dir), \
                    patch.object(tunnel_setup, "NGINX_SITES_DIR", nginx_dir), \
                    patch.object(tunnel_setup, "check_root"), \
                    patch.object(tunnel_setup, "install_cloudflared"), \
                    patch.object(tunnel_setup, "run_command", side_effect=command_results):
                self.assertTrue(tunnel_setup.main(interactive=False))

            with open(os.path.join(config_dir, "config.yml"), encoding="utf-8") as config:
                self.assertIn("example.com", config.read())
            with open(state_path, encoding="utf-8") as state_file:
                self.assertEqual(json.load(state_file)["sites"][0]["hostname"], "example.com")

    def test_cloudflared_install_uses_signed_apt_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            keyring = os.path.join(tmp, "cloudflare-main.gpg")
            source = os.path.join(tmp, "cloudflared.list")
            with patch.object(tunnel_setup.shutil, "which", return_value=None), \
                    patch.object(tunnel_setup, "CLOUDFLARE_APT_KEYRING", keyring), \
                    patch.object(tunnel_setup, "CLOUDFLARE_APT_SOURCE", source), \
                    patch.object(
                        tunnel_setup,
                        "run_command",
                        return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
                    ) as mock_run:
                tunnel_setup.install_cloudflared()

            commands = [mock_call.args[0] for mock_call in mock_run.call_args_list]
            self.assertIn(["apt-get", "install", "-y", "cloudflared"], commands)
            self.assertFalse(any(command[:1] == ["dpkg"] for command in commands))
            with open(source, encoding="utf-8") as source_file:
                self.assertIn("signed-by=", source_file.read())


if __name__ == "__main__":
    unittest.main()
