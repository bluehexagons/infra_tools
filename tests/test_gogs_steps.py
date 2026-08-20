"""Tests for web.gogs_steps."""

from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
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
    @patch("lib.release_management.run")
    def test_unknown_release_architecture_is_rejected(self, mock_run):
        mock_run.return_value = SimpleNamespace(returncode=0, stdout="riscv64\n", stderr="")
        with self.assertRaisesRegex(RuntimeError, "Unsupported release architecture: riscv64"):
            gogs_steps.detect_release_arch()

    @patch("lib.release_management.run")
    def test_prefers_aged_release_when_available(self, mock_run):
        # Dates are relative to now so the test stays stable over time: the
        # newest release is within the 7-day min-age window (too fresh) and
        # the older one is well past it (aged, hence preferred).
        now = datetime.now(timezone.utc)
        fresh = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        aged = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload = [
            {
                "tag_name": "v2.0.0",
                "published_at": fresh,
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
                "published_at": aged,
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


class TestInstallGogsRelease(unittest.TestCase):
    @patch("web.gogs_steps.run")
    @patch(
        "web.gogs_steps.fetch_preferred_gogs_release",
        return_value=("../../escape", "https://example.com/gogs.tar.gz"),
    )
    @patch("web.gogs_steps.detect_release_arch", return_value="amd64")
    def test_rejects_release_tag_path_traversal(self, _arch, _fetch, mock_run):
        with self.assertRaisesRegex(ValueError, "Invalid release tag"):
            gogs_steps.install_or_update_gogs_release()

        mock_run.assert_not_called()

    @patch("web.gogs_steps.run")
    @patch("web.gogs_steps.os.path.exists", return_value=False)
    @patch("web.gogs_steps.read_installed_gogs_release", return_value="v1.2.3")
    @patch(
        "web.gogs_steps.fetch_preferred_gogs_release",
        return_value=("v1.2.4", "https://example.com/gogs-v1.2.4.tar.gz"),
    )
    @patch("web.gogs_steps.detect_release_arch", return_value="amd64")
    def test_validates_extracted_binary_before_activating_release(
        self,
        _arch,
        _fetch,
        _installed,
        _exists,
        mock_run,
    ):
        mock_run.return_value = SimpleNamespace(returncode=0, stdout="v1.2.4", stderr="")

        tag_name, changed = gogs_steps.install_or_update_gogs_release()

        self.assertEqual((tag_name, changed), ("v1.2.4", True))
        calls = mock_run.call_args_list
        version_index = next(
            index for index, call in enumerate(calls) if call.args[0].endswith("/gogs --version")
        )
        activate_index = next(
            index
            for index, call in enumerate(calls)
            if call.args[0].startswith("ln -sfn /opt/gogs/releases/v1.2.4 /opt/gogs/current")
        )
        self.assertLess(version_index, activate_index)
        self.assertTrue(calls[version_index].kwargs["check"])
        self.assertTrue(calls[version_index].kwargs["capture_output"])
        download_command = next(
            call.args[0]
            for call in calls
            if call.args[0].startswith("curl -fL ")
        )
        self.assertIn("/infra-tools-gogs-release-", download_command)
        self.assertNotIn("-o /tmp/gogs_", download_command)
        self.assertIn("--proto-redir '=https'", download_command)


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
    @patch("common.common_steps.configure_maintenance_timer")
    def test_configures_gogs_auto_update_timer(self, mock_configure):
        config = SetupConfig(host="host", username="user", system_type="server_web", gogs=["git.example.com"])
        common_steps.configure_auto_update_gogs(config)
        mock_configure.assert_called_once_with(
            service_name="auto-update-gogs",
            service_desc="Auto-update Gogs service",
            timer_desc="Auto-update Gogs weekly",
            script_path="/opt/infra_tools/common/service_tools/auto_update_gogs.py",
            schedule="Sun *-*-* 05:30:00",
            check_path="/usr/local/bin/gogs",
            check_name="Gogs",
            purpose="auto-update",
        )


if __name__ == "__main__":
    unittest.main()
