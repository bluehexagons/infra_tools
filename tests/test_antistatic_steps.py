"""Tests for game/antistatic_steps.py."""

from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, call, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from game.antistatic_steps import (
    ANTISTATIC_BINARY,
    ANTISTATIC_DB_BINARY,
    ANTISTATIC_DB_DATA_DIR,
    ANTISTATIC_DB_PATH,
    ANTISTATIC_DB_SERVICE,
    ANTISTATIC_DB_USER,
    ANTISTATIC_SERVICE,
    ANTISTATIC_USER,
    DEFAULT_DB_INTERNAL_PORT,
    DEFAULT_INTERNAL_PORT,
    _download_antistatic_binary,
    _download_antistatic_db_binary,
    _fetch_latest_antistatic_db_release,
    _fetch_latest_antistatic_release,
    _maybe_configure_nginx_proxy,
    _remove_empty_domain_nginx_proxy,
    generate_antistatic_db_service,
    generate_antistatic_nginx_config,
    generate_antistatic_service,
    parse_antistatic_db_spec,
    parse_antistatic_spec,
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

    def test_port_only(self):
        domain, port = parse_antistatic_spec(":8080")
        self.assertEqual(domain, "")
        self.assertEqual(port, 8080)

    def test_numeric_spec_is_port_only(self):
        domain, port = parse_antistatic_spec("8080")
        self.assertEqual(domain, "")
        self.assertEqual(port, 8080)


class TestParseAntistaticDbSpec(unittest.TestCase):
    def test_domain_only(self):
        domain, port = parse_antistatic_db_spec("api.example.com")
        self.assertEqual(domain, "api.example.com")
        self.assertEqual(port, DEFAULT_DB_INTERNAL_PORT)

    def test_domain_with_port(self):
        domain, port = parse_antistatic_db_spec("api.example.com:9091")
        self.assertEqual(domain, "api.example.com")
        self.assertEqual(port, 9091)

    def test_domain_with_invalid_port_falls_back(self):
        domain, port = parse_antistatic_db_spec("api.example.com:nope")
        self.assertEqual(domain, "api.example.com")
        self.assertEqual(port, DEFAULT_DB_INTERNAL_PORT)

    def test_port_only(self):
        domain, port = parse_antistatic_db_spec(":8081")
        self.assertEqual(domain, "")
        self.assertEqual(port, 8081)

    def test_numeric_spec_is_port_only(self):
        domain, port = parse_antistatic_db_spec("8081")
        self.assertEqual(domain, "")
        self.assertEqual(port, 8081)


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


class TestGenerateAntistaticDbService(unittest.TestCase):
    def test_contains_required_sections(self):
        content = generate_antistatic_db_service(8081)
        self.assertIn("[Unit]", content)
        self.assertIn("[Service]", content)
        self.assertIn("[Install]", content)
        self.assertIn("WantedBy=multi-user.target", content)

    def test_port_and_db_path_substituted(self):
        content = generate_antistatic_db_service(9091)
        self.assertIn("-port 9091", content)
        self.assertIn(f"-db {ANTISTATIC_DB_PATH}", content)

    def test_binds_to_loopback_and_trusts_proxy(self):
        content = generate_antistatic_db_service(8081)
        self.assertIn("-host 127.0.0.1", content)
        self.assertIn("-trust-proxy", content)

    def test_hostless_db_can_bind_all_interfaces(self):
        content = generate_antistatic_db_service(8081, host="")
        self.assertIn(f"ExecStart={ANTISTATIC_DB_BINARY} -port 8081", content)
        self.assertNotIn("-host", content)

    def test_correct_user_and_binary(self):
        content = generate_antistatic_db_service(8081)
        self.assertIn(f"User={ANTISTATIC_DB_USER}", content)
        self.assertIn(f"Group={ANTISTATIC_DB_USER}", content)
        self.assertIn(f"ExecStart={ANTISTATIC_DB_BINARY}", content)

    def test_state_directory_and_working_directory(self):
        content = generate_antistatic_db_service(8081)
        self.assertIn("StateDirectory=antistatic-db", content)
        self.assertIn(f"WorkingDirectory={ANTISTATIC_DB_DATA_DIR}", content)

    def test_security_hardening_directives(self):
        content = generate_antistatic_db_service(8081)
        self.assertIn("NoNewPrivileges=yes", content)
        self.assertIn("PrivateTmp=yes", content)
        self.assertIn("ProtectSystem=strict", content)
        self.assertIn("ProtectHome=yes", content)


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

    def test_requires_domain(self):
        with self.assertRaises(ValueError):
            generate_antistatic_nginx_config("", 8080)


class TestAntistaticHostlessNginxHandling(unittest.TestCase):
    @patch("game.antistatic_steps.os.remove")
    @patch("game.antistatic_steps.os.path.lexists", return_value=True)
    def test_removes_stale_empty_domain_nginx_config(self, _exists, mock_remove):
        _remove_empty_domain_nginx_proxy()
        mock_remove.assert_has_calls([
            call("/etc/nginx/sites-enabled/antistatic_"),
            call("/etc/nginx/sites-available/antistatic_"),
        ])

    @patch("game.antistatic_steps._remove_empty_domain_nginx_proxy")
    @patch("game.antistatic_steps._configure_nginx_proxy")
    def test_hostless_config_skips_nginx_proxy(self, mock_configure, mock_remove):
        _maybe_configure_nginx_proxy("", 8080, ANTISTATIC_SERVICE)
        mock_configure.assert_not_called()
        mock_remove.assert_called_once_with()

    @patch("game.antistatic_steps._remove_empty_domain_nginx_proxy")
    @patch("game.antistatic_steps._configure_nginx_proxy")
    def test_domain_config_uses_nginx_proxy(self, mock_configure, mock_remove):
        _maybe_configure_nginx_proxy("lobby.example.com", 8080, ANTISTATIC_SERVICE)
        mock_configure.assert_called_once_with("lobby.example.com", 8080)
        mock_remove.assert_not_called()


class TestAntistaticReleaseDownloads(unittest.TestCase):
    def test_fetch_latest_release_returns_tag_and_asset_url(self):
        release_payload = {
            "tag_name": "v1.2.3",
            "assets": [
                {
                    "name": "antistatic-server-linux-amd64",
                    "browser_download_url": "https://example.invalid/antistatic-server-linux-amd64",
                }
            ],
        }

        with patch(
            "game.antistatic_steps.run",
            return_value=MagicMock(returncode=0, stdout=json.dumps(release_payload)),
        ):
            tag_name, download_url = _fetch_latest_antistatic_release("amd64")

        self.assertEqual(tag_name, "v1.2.3")
        self.assertEqual(
            download_url,
            "https://example.invalid/antistatic-server-linux-amd64",
        )

    def test_fetch_latest_release_requires_tag_name(self):
        release_payload = {
            "assets": [
                {
                    "name": "antistatic-server-linux-amd64",
                    "browser_download_url": "https://example.invalid/antistatic-server-linux-amd64",
                }
            ],
        }

        with patch(
            "game.antistatic_steps.run",
            return_value=MagicMock(returncode=0, stdout=json.dumps(release_payload)),
        ):
            with self.assertRaises(RuntimeError):
                _fetch_latest_antistatic_release("amd64")

    @patch("game.antistatic_steps._write_installed_antistatic_release")
    @patch("game.antistatic_steps.run")
    @patch("game.antistatic_steps.os.path.exists", return_value=False)
    @patch("game.antistatic_steps._read_installed_antistatic_release", return_value="v1.2.2")
    @patch(
        "game.antistatic_steps._fetch_latest_antistatic_release",
        return_value=("v1.2.3", "https://example.invalid/antistatic-server-linux-amd64"),
    )
    def test_download_binary_reinstalls_when_new_release_available(
        self,
        _fetch_latest,
        _read_installed,
        _exists,
        mock_run,
        mock_write_release,
    ):
        tag_name = _download_antistatic_binary("amd64")

        self.assertEqual(tag_name, "v1.2.3")
        mock_run.assert_has_calls(
            [
                call(
                    "curl -fL -o /tmp/antistatic-server-linux-amd64.v1.2.3 https://example.invalid/antistatic-server-linux-amd64",
                    check=True,
                    display_cmd="curl -fL -o /tmp/antistatic-server-linux-amd64.v1.2.3 <release URL>",
                ),
                call("chmod +x /tmp/antistatic-server-linux-amd64.v1.2.3", check=True),
                call(
                    "mv /tmp/antistatic-server-linux-amd64.v1.2.3 /usr/local/bin/antistatic-server",
                    check=True,
                ),
            ]
        )
        mock_write_release.assert_called_once_with("v1.2.3")

    @patch("game.antistatic_steps._write_installed_antistatic_release")
    @patch("game.antistatic_steps.run")
    @patch("game.antistatic_steps.os.path.exists", return_value=True)
    @patch("game.antistatic_steps._read_installed_antistatic_release", return_value="v1.2.3")
    @patch(
        "game.antistatic_steps._fetch_latest_antistatic_release",
        return_value=("v1.2.3", "https://example.invalid/antistatic-server-linux-amd64"),
    )
    def test_download_binary_skips_reinstall_when_latest_release_already_present(
        self,
        _fetch_latest,
        _read_installed,
        _exists,
        mock_run,
        mock_write_release,
    ):
        tag_name = _download_antistatic_binary("amd64")

        self.assertEqual(tag_name, "v1.2.3")
        mock_run.assert_not_called()
        mock_write_release.assert_not_called()


class TestAntistaticDbReleaseDownloads(unittest.TestCase):
    def test_fetch_latest_release_returns_tag_and_asset_url(self):
        release_payload = {
            "tag_name": "v0.1.0",
            "assets": [
                {
                    "name": "antistatic-db-linux-amd64",
                    "browser_download_url": "https://example.invalid/antistatic-db-linux-amd64",
                }
            ],
        }

        with patch(
            "game.antistatic_steps.run",
            return_value=MagicMock(returncode=0, stdout=json.dumps(release_payload)),
        ):
            tag_name, download_url = _fetch_latest_antistatic_db_release("amd64")

        self.assertEqual(tag_name, "v0.1.0")
        self.assertEqual(
            download_url,
            "https://example.invalid/antistatic-db-linux-amd64",
        )

    def test_fetch_latest_release_requires_matching_asset(self):
        release_payload = {
            "tag_name": "v0.1.0",
            "assets": [
                {
                    "name": "antistatic-db-linux-arm64",
                    "browser_download_url": "https://example.invalid/antistatic-db-linux-arm64",
                }
            ],
        }

        with patch(
            "game.antistatic_steps.run",
            return_value=MagicMock(returncode=0, stdout=json.dumps(release_payload)),
        ):
            with self.assertRaises(RuntimeError):
                _fetch_latest_antistatic_db_release("amd64")

    @patch("game.antistatic_steps._write_installed_antistatic_db_release")
    @patch("game.antistatic_steps.run")
    @patch("game.antistatic_steps.os.path.exists", return_value=False)
    @patch("game.antistatic_steps._read_installed_antistatic_db_release", return_value="v0.0.9")
    @patch(
        "game.antistatic_steps._fetch_latest_antistatic_db_release",
        return_value=("v0.1.0", "https://example.invalid/antistatic-db-linux-amd64"),
    )
    def test_download_binary_reinstalls_when_new_release_available(
        self,
        _fetch_latest,
        _read_installed,
        _exists,
        mock_run,
        mock_write_release,
    ):
        tag_name = _download_antistatic_db_binary("amd64")

        self.assertEqual(tag_name, "v0.1.0")
        mock_run.assert_has_calls(
            [
                call(
                    "curl -fL -o /tmp/antistatic-db-linux-amd64.v0.1.0 https://example.invalid/antistatic-db-linux-amd64",
                    check=True,
                    display_cmd="curl -fL -o /tmp/antistatic-db-linux-amd64.v0.1.0 <release URL>",
                ),
                call("chmod +x /tmp/antistatic-db-linux-amd64.v0.1.0", check=True),
                call(
                    "mv /tmp/antistatic-db-linux-amd64.v0.1.0 /usr/local/bin/antistatic-db",
                    check=True,
                ),
            ]
        )
        mock_write_release.assert_called_once_with("v0.1.0")

    @patch("game.antistatic_steps._write_installed_antistatic_db_release")
    @patch("game.antistatic_steps.run")
    @patch("game.antistatic_steps.os.path.exists", return_value=True)
    @patch("game.antistatic_steps._read_installed_antistatic_db_release", return_value="v0.1.0")
    @patch(
        "game.antistatic_steps._fetch_latest_antistatic_db_release",
        return_value=("v0.1.0", "https://example.invalid/antistatic-db-linux-amd64"),
    )
    def test_download_binary_skips_reinstall_when_latest_release_already_present(
        self,
        _fetch_latest,
        _read_installed,
        _exists,
        mock_run,
        mock_write_release,
    ):
        tag_name = _download_antistatic_db_binary("amd64")

        self.assertEqual(tag_name, "v0.1.0")
        mock_run.assert_not_called()
        mock_write_release.assert_not_called()


if __name__ == "__main__":
    unittest.main()
