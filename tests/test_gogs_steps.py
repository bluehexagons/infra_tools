"""Tests for web.gogs_steps."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import common.common_steps as common_steps
from lib.config import SetupConfig
from lib.arg_parser import add_setup_arguments
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

    def test_parser_and_config_preserve_repeatable_sources(self):
        parser = argparse.ArgumentParser()
        add_setup_arguments(parser, for_remote=True, include_host=False)
        args = parser.parse_args(
            [
                "--gogs",
                ":3000",
                "/srv/gogs",
                "--gogs-source",
                "192.168.0.0/24",
                "--gogs-source",
                "10.0.0.5",
            ]
        )
        args.host = "10.0.0.41"
        args.username = "admin"
        config = SetupConfig.from_args(args, "server_web")

        self.assertEqual(config.gogs_sources, ["192.168.0.0/24", "10.0.0.5"])
        self.assertIn("--gogs-source 192.168.0.0/24", config.to_remote_args())
        self.assertIn("--gogs-source 10.0.0.5", config.to_setup_command())


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
    @patch("web.gogs_steps.run")
    def test_data_directory_setup_rejects_symlinked_subpath(self, mock_run):
        with tempfile.TemporaryDirectory() as directory:
            outside = os.path.join(directory, "outside")
            os.mkdir(outside)
            os.symlink(outside, os.path.join(directory, "custom"))

            with self.assertRaisesRegex(RuntimeError, "symlinked Gogs data path"):
                gogs_steps._ensure_gogs_data_dirs(directory)

        self.assertFalse(
            any("custom" in call.args[0] for call in mock_run.call_args_list)
        )

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
        self.assertIn("[lfs]", content)
        self.assertIn("STORAGE = local", content)
        self.assertIn("OBJECTS_PATH = /srv/gogs/data/lfs-objects", content)
        self.assertIn("OBJECTS_TEMP_PATH = /srv/gogs/data/tmp/lfs-objects", content)
        self.assertIn("DISABLE_REGISTRATION = true", content)

    def test_hostless_app_ini_is_loopback_only_by_default(self):
        config = SetupConfig(
            host="10.0.0.41",
            username="admin",
            system_type="server_web",
            gogs=[":3000", "/srv/gogs"],
        )
        with patch("web.gogs_steps._load_or_create_gogs_secret_key", return_value="secret"):
            content = gogs_steps.generate_gogs_app_ini(
                config,
                git_home="/home/git",
                data_path="/srv/gogs",
                domain="",
                port=3000,
            )

        self.assertIn("HTTP_ADDR = 127.0.0.1", content)
        self.assertIn("EXTERNAL_URL = http://127.0.0.1:3000/", content)

    def test_hostless_private_source_app_ini_binds_for_firewalled_access(self):
        config = SetupConfig(
            host="10.0.0.41",
            username="admin",
            system_type="server_web",
            gogs=[":3000", "/srv/gogs"],
            gogs_sources=["192.168.0.0/24"],
        )
        with patch("web.gogs_steps._load_or_create_gogs_secret_key", return_value="secret"):
            content = gogs_steps.generate_gogs_app_ini(
                config,
                git_home="/home/git",
                data_path="/srv/gogs",
                domain="",
                port=3000,
            )

        self.assertIn("HTTP_ADDR = 0.0.0.0", content)
        self.assertIn("EXTERNAL_URL = http://10.0.0.41:3000/", content)

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


class TestGogsHostlessFirewall(unittest.TestCase):
    def test_source_exposure_requires_active_ufw(self):
        config = SetupConfig(
            host="10.0.0.41",
            username="admin",
            system_type="server_web",
            gogs=[":3000"],
            gogs_sources=["192.168.0.0/24"],
        )
        inactive = SimpleNamespace(returncode=1, stdout="", stderr="")
        with patch("web.gogs_steps.run", return_value=inactive):
            with self.assertRaisesRegex(RuntimeError, "requires an active UFW"):
                gogs_steps._configure_hostless_gogs_firewall(config, 3000)

    def test_source_rules_are_verified_before_old_managed_rule_is_removed(self):
        config = SetupConfig(
            host="10.0.0.41",
            username="admin",
            system_type="server_web",
            gogs=[":3000"],
            gogs_sources=["192.168.0.0/24"],
        )
        active = SimpleNamespace(returncode=0, stdout="", stderr="")
        initial = SimpleNamespace(
            returncode=0,
            stdout=(
                "[ 1] 3000/tcp ALLOW IN Anywhere # gogs direct HTTP\n"
                "[ 2] 4000/tcp ALLOW IN 192.168.0.0/24 "
                "# infra_tools Gogs 4000/tcp source 192.168.0.0/24\n"
            ),
            stderr="",
        )
        updated = SimpleNamespace(
            returncode=0,
            stdout=(
                "[ 1] 3000/tcp ALLOW IN Anywhere # gogs direct HTTP\n"
                "[ 2] 4000/tcp ALLOW IN 192.168.0.0/24 "
                "# infra_tools Gogs 4000/tcp source 192.168.0.0/24\n"
                "[ 3] 3000/tcp ALLOW IN 192.168.0.0/24 "
                "# infra_tools Gogs 3000/tcp source 192.168.0.0/24\n"
            ),
            stderr="",
        )
        with patch(
            "web.gogs_steps.run",
            side_effect=[active, initial, active, updated, active, active],
        ) as runner:
            gogs_steps._configure_hostless_gogs_firewall(config, 3000)

        commands = [call.args[0] for call in runner.call_args_list]
        self.assertIn("ufw allow from 192.168.0.0/24", commands[2])
        self.assertEqual(commands[-2:], ["ufw --force delete 2", "ufw --force delete 1"])


class TestGogsStorageHealth(unittest.TestCase):
    def test_reports_local_capacity_and_usage(self):
        with tempfile.TemporaryDirectory() as data_path:
            for relative in (
                "data/lfs-objects",
                "data/tmp/lfs-objects",
                "data/attachments",
                "repositories",
                "log",
            ):
                os.makedirs(os.path.join(data_path, relative), exist_ok=True)
            open(os.path.join(data_path, "data", "gogs.db"), "a", encoding="utf-8").close()

            def result_for(command: str, **_kwargs):
                if command.startswith("findmnt "):
                    stdout = "/dev/vdb1 ext4 /srv/gogs\n"
                elif command.startswith("sqlite3 "):
                    stdout = "ok\n"
                elif command.startswith("df "):
                    stdout = " Avail IAvail\n 1048576 2048\n"
                elif command.startswith("du "):
                    stdout = "4096 path\n"
                else:
                    stdout = ""
                return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

            with patch("web.gogs_steps.run", side_effect=result_for):
                health = gogs_steps.check_gogs_storage_health(data_path)

        self.assertEqual(health["filesystem"], "ext4")
        self.assertEqual(health["free_bytes"], 1048576)
        self.assertEqual(health["usage"]["lfs_objects"], 4096)

    def test_rejects_cifs_live_data(self):
        result = SimpleNamespace(
            returncode=0,
            stdout="//server/share cifs /srv/gogs\n",
            stderr="",
        )
        with patch("web.gogs_steps.run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "cannot use CIFS"):
                gogs_steps.check_gogs_storage_health("/srv/gogs")


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
