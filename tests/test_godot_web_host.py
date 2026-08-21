"""Tests for the managed Godot HTTPS publishing origin."""

from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from common import godot_web_steps
from common.service_tools import godot_web_publish


class TestGodotWebHost(unittest.TestCase):
    def test_nginx_host_supplies_secure_context_and_isolation_headers(self) -> None:
        content = godot_web_steps.render_nginx_config(
            "/certs/server.crt",
            "/certs/server.key",
        )

        self.assertIn("listen 8443 ssl", content)
        self.assertIn("Cross-Origin-Opener-Policy \"same-origin\"", content)
        self.assertIn("Cross-Origin-Embedder-Policy \"require-corp\"", content)
        self.assertIn("application/x-x509-ca-cert", content)
        self.assertIn("autoindex on", content)

    def test_certificate_identities_include_remote_and_loopback_access(self) -> None:
        self.assertEqual(
            godot_web_steps.identities_for_config("Games.Example", "godot-vm"),
            ["games.example", "godot-vm", "localhost", "127.0.0.1", "::1"],
        )

    def test_invalid_certificate_identity_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Invalid internal HTTPS identity"):
            godot_web_steps.validate_web_identities(["bad host name"])

    def test_configure_host_creates_user_publish_root_and_landing_page(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            web_root = os.path.join(temporary_dir, "web")
            games_root = os.path.join(web_root, "games")
            url_file = os.path.join(temporary_dir, "config", "base-url")
            ca_cert = os.path.join(temporary_dir, "ca.crt")
            with open(ca_cert, "w", encoding="utf-8") as cert_file:
                cert_file.write("test CA\n")

            account = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
            with (
                patch.object(godot_web_steps, "GODOT_WEB_ROOT", web_root),
                patch.object(godot_web_steps, "GODOT_WEB_GAMES_ROOT", games_root),
                patch.object(godot_web_steps, "GODOT_WEB_URL_FILE", url_file),
                patch.object(godot_web_steps, "GODOT_WEB_CA_CERT", ca_cert),
                patch.object(godot_web_steps, "_ensure_nginx"),
                patch.object(
                    godot_web_steps,
                    "_certificate_for_identities",
                    return_value=("/cert", "/key", True, True),
                ),
                patch.object(godot_web_steps, "_install_publisher_link", return_value=True),
                patch.object(godot_web_steps, "_configure_nginx_site", return_value=True) as nginx,
                patch.object(godot_web_steps.pwd, "getpwnam", return_value=account),
            ):
                changed = godot_web_steps.configure_godot_web_host(
                    ["192.0.2.10", "localhost"],
                    ["agent"],
                )

            self.assertTrue(changed)
            self.assertTrue(os.path.isdir(os.path.join(games_root, "agent")))
            with open(os.path.join(web_root, "index.html"), encoding="utf-8") as page:
                self.assertIn("godot-web-publish", page.read())
            with open(url_file, encoding="utf-8") as base_url:
                self.assertEqual(base_url.read(), "https://192.0.2.10:8443\n")
            nginx.assert_called_once()


class TestGodotWebPublisher(unittest.TestCase):
    def test_failed_activation_restores_previous_export(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            destination_dir = os.path.join(temporary_dir, "demo")
            staging_dir = os.path.join(temporary_dir, ".demo-staging")
            os.mkdir(destination_dir)
            os.mkdir(staging_dir)
            previous_file = os.path.join(destination_dir, "index.html")
            with open(previous_file, "w", encoding="utf-8") as file_obj:
                file_obj.write("previous")

            real_replace = os.replace

            def fail_activation(source: str, destination: str) -> None:
                if source == staging_dir and destination == destination_dir:
                    raise OSError("activation failed")
                real_replace(source, destination)

            with patch.object(
                godot_web_publish.os,
                "replace",
                side_effect=fail_activation,
            ):
                with self.assertRaisesRegex(OSError, "activation failed"):
                    godot_web_publish._replace_export(staging_dir, destination_dir)

            with open(previous_file, encoding="utf-8") as file_obj:
                self.assertEqual(file_obj.read(), "previous")

    def test_publish_uses_release_preset_and_atomically_activates_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            project_dir = os.path.join(temporary_dir, "project")
            games_root = os.path.join(temporary_dir, "games")
            user_root = os.path.join(games_root, "agent")
            os.makedirs(project_dir)
            os.makedirs(user_root)
            with open(os.path.join(project_dir, "project.godot"), "w", encoding="utf-8"):
                pass
            url_file = os.path.join(temporary_dir, "base-url")
            with open(url_file, "w", encoding="utf-8") as file_obj:
                file_obj.write("https://games.example:8443\n")

            account = SimpleNamespace(pw_uid=os.getuid(), pw_name="agent")

            def create_export(command: list[str], **_kwargs: object) -> SimpleNamespace:
                export_path = command[-1]
                with open(export_path, "w", encoding="utf-8") as export_file:
                    export_file.write("game")
                return SimpleNamespace(returncode=0)

            with (
                patch.object(godot_web_publish, "GAMES_ROOT", games_root),
                patch.object(godot_web_publish, "BASE_URL_FILE", url_file),
                patch.object(godot_web_publish, "_current_account", return_value=account),
                patch.object(
                    godot_web_publish.subprocess,
                    "run",
                    side_effect=create_export,
                ) as run_export,
            ):
                result = godot_web_publish.main(["demo", project_dir])

            self.assertEqual(result, 0)
            published_file = os.path.join(user_root, "demo", "index.html")
            self.assertTrue(os.path.isfile(published_file))
            self.assertEqual(os.stat(os.path.dirname(published_file)).st_mode & 0o777, 0o755)
            self.assertEqual(os.stat(published_file).st_mode & 0o777, 0o644)
            command = run_export.call_args.args[0]
            self.assertEqual(command[:2], ["godot", "--headless"])
            self.assertIn("--export-release", command)
            self.assertIn("Web", command)

    def test_publish_rejects_unsafe_game_name_before_running_godot(self) -> None:
        with patch.object(godot_web_publish.subprocess, "run") as run_export:
            result = godot_web_publish.main(["../escape"])

        self.assertEqual(result, 2)
        run_export.assert_not_called()


if __name__ == "__main__":
    unittest.main()
