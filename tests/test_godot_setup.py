"""Tests for verified Godot installation, configuration, and maintenance."""

from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
import zipfile
from unittest.mock import call, patch

from common import godot_steps
from common.service_tools import auto_update_godot
from lib.arg_parser import create_setup_argument_parser
from lib.config import SetupConfig
from lib.system_types import get_steps_for_system_type


class TestGodotSetup(unittest.TestCase):
    def test_parser_and_config_commands_preserve_godot_selection(self):
        parser = create_setup_argument_parser("test")
        args = parser.parse_args(["example.com", "--godot"])
        self.assertTrue(args.install_godot)

        config = SetupConfig(
            host="example.com",
            username="agent",
            system_type="agent_vm",
            install_godot=True,
        )
        self.assertIn("--godot", config.to_remote_args())
        self.assertIn("--godot", config.to_setup_command())
        self.assertTrue(config.to_dict()["install_godot"])
        restored = SetupConfig.from_dict(
            "example.com",
            "agent_vm",
            config.to_dict(),
        )
        self.assertTrue(restored.install_godot)

    def test_agent_profile_can_add_graphical_and_headless_godot_steps(self):
        for system_type in ("agent_vm", "agent_workstation"):
            with self.subTest(system_type=system_type):
                config = SetupConfig(
                    host="host",
                    username="agent",
                    system_type=system_type,
                    install_godot=True,
                )
                step_names = [
                    name for name, _step in get_steps_for_system_type(config)
                ]
                self.assertIn("Installing Godot Engine (latest stable)", step_names)
                self.assertIn("Configuring Godot auto-update", step_names)

    @patch("common.godot_steps.fetch_latest_verified_github_release_asset")
    def test_release_selector_matches_official_linux_asset(self, mock_fetch):
        mock_fetch.return_value = (
            "4.7.2-stable",
            "https://github.com/godotengine/godot/releases/download/4.7.2-stable/godot.zip",
            "a" * 64,
        )

        self.assertEqual(
            godot_steps.fetch_latest_godot_release("x86_64"),
            mock_fetch.return_value,
        )
        matcher = mock_fetch.call_args.kwargs["asset_matches"]
        self.assertTrue(
            matcher(
                "4.7.2-stable",
                "Godot_v4.7.2-stable_linux.x86_64.zip",
            )
        )
        self.assertFalse(
            matcher(
                "4.7.2-stable",
                "Godot_v4.7.2-stable_linux.x86_64_mono.zip",
            )
        )

    def test_verified_archive_extracts_only_expected_binary(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            archive_path = os.path.join(temporary_dir, "godot.zip")
            release_dir = os.path.join(temporary_dir, "release")
            member_name = "Godot_v4.7.2-stable_linux.x86_64"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(member_name, b"godot-binary")
                archive.writestr("unrelated", b"not-installed")
            with open(archive_path, "rb") as archive_file:
                expected_sha256 = hashlib.sha256(archive_file.read()).hexdigest()

            binary_path = godot_steps._extract_verified_binary(
                archive_path,
                expected_sha256=expected_sha256,
                binary_member=member_name,
                release_dir=release_dir,
            )

            with open(binary_path, "rb") as binary_file:
                self.assertEqual(binary_file.read(), b"godot-binary")
            self.assertTrue(os.stat(binary_path).st_mode & 0o111)
            self.assertFalse(os.path.exists(os.path.join(release_dir, "unrelated")))

    @patch("common.godot_steps.configure_maintenance_timer", return_value=True)
    def test_auto_update_timer_tracks_non_apt_release(self, mock_configure):
        config = SetupConfig(host="host", username="agent", system_type="agent_vm")
        godot_steps.configure_auto_update_godot(config)
        mock_configure.assert_called_once_with(
            service_name="auto-update-godot",
            service_desc="Auto-update Godot Engine",
            timer_desc="Auto-update Godot Engine weekly",
            script_path="/opt/infra_tools/common/service_tools/auto_update_godot.py",
            schedule="Sun *-*-* 06:30:00",
            check_path="/usr/local/bin/godot",
            check_name="Godot",
            purpose="auto-update",
        )

    @patch("common.godot_steps.run")
    def test_systemwide_links_make_godot_available_to_agent_users(self, mock_run):
        godot_steps._install_godot_links("/opt/godot/releases/4.7.2-stable-digest")
        self.assertEqual(
            mock_run.call_args_list,
            [
                call(
                    "ln -sfn /opt/godot/releases/4.7.2-stable-digest /opt/godot/current",
                    check=True,
                ),
                call(
                    "ln -sfn /opt/godot/current/godot /usr/local/bin/godot",
                    check=True,
                ),
                call(
                    "ln -sfn /opt/godot/current/godot /usr/local/bin/godot4",
                    check=True,
                ),
            ],
        )


class TestGodotAutoUpdater(unittest.TestCase):
    @patch("common.service_tools.auto_update_godot.send_notification_safe")
    @patch("common.service_tools.auto_update_godot.log_event")
    @patch(
        "common.service_tools.auto_update_godot.load_notification_configs_from_state",
        return_value=[],
    )
    @patch("common.service_tools.auto_update_godot.os.path.exists", return_value=True)
    @patch(
        "common.service_tools.auto_update_godot.install_or_update_godot_release",
        return_value=("4.7.2-stable", True, "a" * 64),
    )
    def test_successful_update_notifies(
        self,
        _install_release,
        _exists,
        _load_notifications,
        _log_event,
        mock_notify,
    ):
        self.assertEqual(auto_update_godot.main(), 0)
        self.assertEqual(mock_notify.call_args.kwargs["status"], "success")

    @patch("common.service_tools.auto_update_godot.send_notification_safe")
    @patch("common.service_tools.auto_update_godot.log_event")
    @patch(
        "common.service_tools.auto_update_godot.load_notification_configs_from_state",
        return_value=["notification"],
    )
    @patch("common.service_tools.auto_update_godot.os.path.exists", return_value=True)
    @patch(
        "common.service_tools.auto_update_godot.install_or_update_godot_release",
        side_effect=RuntimeError("download failed"),
    )
    def test_failed_update_notifies_and_returns_failure(
        self,
        _install_release,
        _exists,
        _load_notifications,
        _log_event,
        mock_notify,
    ):
        self.assertEqual(auto_update_godot.main(), 1)
        self.assertEqual(mock_notify.call_args.kwargs["status"], "error")


if __name__ == "__main__":
    unittest.main()
