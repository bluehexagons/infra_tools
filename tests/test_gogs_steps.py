"""Tests for web.gogs_steps."""

from __future__ import annotations

import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import common.common_steps as common_steps
from lib.config import SetupConfig
from web import gogs_steps


class TestParseGogsSpec(unittest.TestCase):
    def test_domain_defaults_port(self):
        domain, port = gogs_steps.parse_gogs_spec("git.example.com")
        self.assertEqual((domain, port), ("git.example.com", 3000))

    def test_domain_and_port(self):
        domain, port = gogs_steps.parse_gogs_spec("git.example.com:8080", strict=True)
        self.assertEqual((domain, port), ("git.example.com", 8080))

    def test_hostless_port(self):
        domain, port = gogs_steps.parse_gogs_spec("8080", strict=True)
        self.assertEqual((domain, port), ("", 8080))

    def test_invalid_port_rejected_in_strict_mode(self):
        with self.assertRaisesRegex(ValueError, "Invalid Gogs port: nope"):
            gogs_steps.parse_gogs_spec("git.example.com:nope", strict=True)


class TestFetchPreferredGogsRelease(unittest.TestCase):
    @patch("web.gogs_steps.run")
    def test_prefers_aged_release_when_available(self, mock_run):
        payload = [
            {
                "tag_name": "v2.0.0",
                "published_at": "2026-05-17T12:00:00Z",
                "draft": False,
                "prerelease": False,
                "assets": [
                    {
                        "name": "gogs_v2.0.0_linux_amd64.tar.gz",
                        "browser_download_url": "https://example.com/v2.0.0.tgz",
                    }
                ],
            },
            {
                "tag_name": "v1.9.0",
                "published_at": "2026-05-01T12:00:00Z",
                "draft": False,
                "prerelease": False,
                "assets": [
                    {
                        "name": "gogs_v1.9.0_linux_amd64.tar.gz",
                        "browser_download_url": "https://example.com/v1.9.0.tgz",
                    }
                ],
            },
        ]
        mock_run.return_value = SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

        with patch.dict(os.environ, {"INFRA_TOOLS_DEPENDENCY_MIN_AGE_DAYS": "7"}):
            tag_name, download_url = gogs_steps.fetch_preferred_gogs_release("amd64")

        self.assertEqual(tag_name, "v1.9.0")
        self.assertEqual(download_url, "https://example.com/v1.9.0.tgz")


class TestGenerateGogsConfig(unittest.TestCase):
    def test_generate_app_ini_enables_external_ssh(self):
        config = SetupConfig(
            host="host.example.com",
            username="admin",
            system_type="server_web",
            enable_ssl=True,
            gogs=["git.example.com:3000", "/srv/gogs"],
        )

        with patch("web.gogs_steps._load_or_create_gogs_secret_key", return_value="secret-key"):
            content = gogs_steps.generate_gogs_app_ini(
                config,
                git_home="/home/git",
                data_path="/srv/gogs",
                domain="git.example.com",
                port=3000,
            )

        self.assertIn("EXTERNAL_URL = https://git.example.com/", content)
        self.assertIn("SSH_DOMAIN = git.example.com", content)
        self.assertIn("SSH_ROOT_PATH = /home/git/.ssh", content)
        self.assertIn("ROOT = /srv/gogs/repositories", content)
        self.assertIn("PATH = /srv/gogs/data/gogs.db", content)
        self.assertIn("DISABLE_REGISTRATION = true", content)

    def test_generate_service_uses_explicit_config_path(self):
        content = gogs_steps.generate_gogs_service("/srv/gogs/custom/conf/app.ini")
        self.assertIn("WorkingDirectory=/opt/gogs/current", content)
        self.assertIn("ExecStart=/opt/gogs/current/gogs web --config /srv/gogs/custom/conf/app.ini", content)
        self.assertIn("User=git", content)

    def test_redacted_admin_create_user_command_hides_password(self):
        command = gogs_steps._redacted_admin_create_user_command(
            "/srv/gogs/custom/conf/app.ini",
            "admin",
            "admin@localhost",
        )
        self.assertIn("[REDACTED]", command)
        self.assertNotIn("supersecret", command)


class TestConfigureAutoUpdateGogs(unittest.TestCase):
    @patch("common.common_steps._configure_auto_update_systemd")
    def test_configures_gogs_auto_update_timer(self, mock_configure):
        config = SetupConfig(host="host", username="user", system_type="server_web", gogs=["git.example.com"])
        common_steps.configure_auto_update_gogs(config)
        mock_configure.assert_called_once_with(
            service_name="auto-update-gogs",
            service_desc="Auto-update Gogs service",
            timer_desc="Auto-update Gogs weekly",
            script_name="auto_update_gogs.py",
            schedule="Sun *-*-* 05:30:00",
            check_path="/usr/local/bin/gogs",
            check_name="Gogs",
        )


if __name__ == "__main__":
    unittest.main()
