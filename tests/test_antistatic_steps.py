"""Tests for game/antistatic_steps.py."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from game.antistatic_steps import (
    parse_antistatic_spec,
    generate_antistatic_service,
    generate_antistatic_nginx_config,
    ANTISTATIC_USER,
    ANTISTATIC_BINARY,
    ANTISTATIC_SERVICE,
    DEFAULT_INTERNAL_PORT,
)


class TestParseAntistaticSpec(unittest.TestCase):
    def test_domain_only(self):
        domain, port = parse_antistatic_spec("lobby.example.com")
        self.assertEqual(domain, "lobby.example.com")
        self.assertEqual(port, DEFAULT_INTERNAL_PORT)

    def test_domain_with_port(self):
        domain, port = parse_antistatic_spec("lobby.example.com:9090")
        self.assertEqual(domain, "lobby.example.com")
        self.assertEqual(port, 9090)

    def test_domain_with_invalid_port_falls_back(self):
        domain, port = parse_antistatic_spec("lobby.example.com:notaport")
        self.assertEqual(domain, "lobby.example.com")
        self.assertEqual(port, DEFAULT_INTERNAL_PORT)

    def test_subdomain_with_port(self):
        domain, port = parse_antistatic_spec("game.lobby.mysite.io:8181")
        self.assertEqual(domain, "game.lobby.mysite.io")
        self.assertEqual(port, 8181)


class TestGenerateAntistaticService(unittest.TestCase):
    def test_contains_required_sections(self):
        content = generate_antistatic_service(8080)
        self.assertIn("[Unit]", content)
        self.assertIn("[Service]", content)
        self.assertIn("[Install]", content)
        self.assertIn("WantedBy=multi-user.target", content)

    def test_port_substituted(self):
        content = generate_antistatic_service(9999)
        self.assertIn("-port 9999", content)

    def test_trust_proxy_flag_present(self):
        content = generate_antistatic_service(8080)
        self.assertIn("-trust-proxy", content)

    def test_correct_user(self):
        content = generate_antistatic_service(8080)
        self.assertIn(f"User={ANTISTATIC_USER}", content)
        self.assertIn(f"Group={ANTISTATIC_USER}", content)

    def test_binary_path(self):
        content = generate_antistatic_service(8080)
        self.assertIn(f"ExecStart={ANTISTATIC_BINARY}", content)

    def test_restart_on_failure(self):
        content = generate_antistatic_service(8080)
        self.assertIn("Restart=on-failure", content)

    def test_security_hardening_directives(self):
        content = generate_antistatic_service(8080)
        self.assertIn("NoNewPrivileges=yes", content)
        self.assertIn("PrivateTmp=yes", content)
        self.assertIn("ProtectSystem=strict", content)
        self.assertIn("ProtectHome=yes", content)

    def test_start_limit_burst(self):
        content = generate_antistatic_service(8080)
        self.assertIn("StartLimitBurst=3", content)


class TestGenerateAntistaticNginxConfig(unittest.TestCase):
    def _make_config(self, domain: str = "lobby.example.com", port: int = 8080) -> str:
        with patch(
            "lib.nginx_config.get_ssl_cert_path",
            return_value=(
                f"/etc/nginx/ssl/{domain}.crt",
                f"/etc/nginx/ssl/{domain}.key",
            ),
        ):
            return generate_antistatic_nginx_config(domain, port)

    def test_server_name(self):
        config = self._make_config("lobby.example.com", 8080)
        self.assertIn("server_name lobby.example.com;", config)

    def test_proxy_pass(self):
        config = self._make_config("lobby.example.com", 8080)
        self.assertIn("proxy_pass http://127.0.0.1:8080;", config)

    def test_acme_challenge_location(self):
        config = self._make_config()
        self.assertIn("/.well-known/acme-challenge/", config)

    def test_forwarded_headers(self):
        config = self._make_config()
        self.assertIn("X-Forwarded-For", config)
        self.assertIn("X-Forwarded-Proto", config)
        self.assertIn("X-Real-IP", config)

    def test_http2_enabled(self):
        config = self._make_config()
        self.assertIn("http2 on;", config)

    def test_listens_on_80_and_443(self):
        config = self._make_config()
        self.assertIn("listen 80;", config)
        self.assertIn("listen 443 ssl;", config)


if __name__ == "__main__":
    unittest.main()
