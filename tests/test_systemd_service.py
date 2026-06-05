"""Tests for lib/systemd_service.py: service config generation."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import call, mock_open, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.systemd_service import (
    cleanup_all_infra_services,
    cleanup_service,
    create_rails_service,
    generate_node_service,
    generate_rails_service,
)


class TestGenerateNodeService(unittest.TestCase):
    def test_contains_unit_section(self):
        content = generate_node_service('myapp', '/var/www/myapp')
        self.assertIn('[Unit]', content)
        self.assertIn('[Service]', content)
        self.assertIn('[Install]', content)

    def test_app_name_in_description(self):
        content = generate_node_service('myapp', '/var/www/myapp')
        self.assertIn('myapp', content)

    def test_default_port(self):
        content = generate_node_service('myapp', '/var/www/myapp')
        self.assertIn('PORT=4000', content)

    def test_custom_port(self):
        content = generate_node_service('myapp', '/var/www/myapp', port=5000)
        self.assertIn('PORT=5000', content)

    def test_web_user(self):
        content = generate_node_service('myapp', '/var/www/myapp', web_user='deploy')
        self.assertIn('User=deploy', content)

    def test_working_directory(self):
        content = generate_node_service('myapp', '/var/www/myapp')
        self.assertIn('WorkingDirectory=/var/www/myapp', content)

    def test_build_dir(self):
        content = generate_node_service('myapp', '/var/www/myapp', build_dir='build')
        self.assertIn('build', content)

    def test_node_env_production(self):
        content = generate_node_service('myapp', '/var/www/myapp')
        self.assertIn('NODE_ENV=production', content)


class TestGenerateRailsService(unittest.TestCase):
    def test_contains_sections(self):
        content = generate_rails_service('myapp', '/var/www/myapp', 'secret123')
        self.assertIn('[Unit]', content)
        self.assertIn('[Service]', content)
        self.assertIn('[Install]', content)

    def test_app_name_in_description(self):
        content = generate_rails_service('myapp', '/var/www/myapp', 'secret')
        self.assertIn('myapp', content)

    def test_secret_key_base(self):
        content = generate_rails_service('myapp', '/var/www/myapp', 'my_secret_key')
        self.assertIn('SECRET_KEY_BASE=my_secret_key', content)

    def test_default_port(self):
        content = generate_rails_service('myapp', '/var/www/myapp', 'secret')
        self.assertIn('-p 3000', content)

    def test_custom_port(self):
        content = generate_rails_service('myapp', '/var/www/myapp', 'secret', port=4000)
        self.assertIn('-p 4000', content)

    def test_rails_env_production(self):
        content = generate_rails_service('myapp', '/var/www/myapp', 'secret')
        self.assertIn('RAILS_ENV=production', content)

    def test_extra_env(self):
        content = generate_rails_service('myapp', '/var/www/myapp', 'secret',
                                        extra_env={'DATABASE_URL': 'sqlite3:db/prod.sqlite3'})
        self.assertIn('DATABASE_URL=sqlite3:db/prod.sqlite3', content)

    def test_web_user(self):
        content = generate_rails_service('myapp', '/var/www/myapp', 'secret', web_user='deploy')
        self.assertIn('User=deploy', content)


class TestCleanupFunctions(unittest.TestCase):
    @patch("lib.systemd_service.os.remove")
    @patch("lib.systemd_service.run")
    @patch("lib.systemd_service.os.path.exists", return_value=True)
    @patch(
        "lib.systemd_service.open",
        new_callable=mock_open,
        read_data="[Unit]\nDescription=Demo\n[Service]\nExecStart=/bin/true\n[Install]\nWantedBy=multi-user.target\n",
    )
    def test_cleanup_service_disables_service_with_install(self, _open, _exists, mock_run, mock_remove):
        cleanup_service("demo")

        mock_run.assert_has_calls(
            [
                call("systemctl stop demo.timer", check=False),
                call("systemctl disable demo.timer", check=False),
                call("systemctl stop demo.path", check=False),
                call("systemctl disable demo.path", check=False),
                call("systemctl stop demo.service", check=False),
                call("systemctl disable demo.service", check=False),
                call("systemctl daemon-reload", check=False),
            ]
        )
        mock_remove.assert_has_calls(
            [
                call("/etc/systemd/system/demo.timer"),
                call("/etc/systemd/system/demo.path"),
                call("/etc/systemd/system/demo.service"),
            ]
        )

    @patch("lib.systemd_service.os.remove")
    @patch("lib.systemd_service.run")
    @patch("lib.systemd_service.os.path.exists", return_value=True)
    @patch("lib.systemd_service.open", new_callable=mock_open, read_data="[Unit]\n[Service]\n")
    def test_cleanup_service_skips_disable_without_install(self, _open, _exists, mock_run, _remove):
        cleanup_service("demo")
        run_commands = [args[0] for args, _ in mock_run.call_args_list]
        self.assertNotIn("systemctl disable demo.service", run_commands)

    @patch("lib.systemd_service.os.remove")
    @patch("lib.systemd_service.run")
    @patch("lib.systemd_service.os.path.exists", return_value=False)
    def test_cleanup_service_handles_missing_files(self, _exists, mock_run, mock_remove):
        cleanup_service("demo")
        mock_run.assert_not_called()
        mock_remove.assert_not_called()

    @patch("lib.systemd_service.os.remove", side_effect=OSError("permission denied"))
    @patch("lib.systemd_service._unit_has_install_section", return_value=True)
    @patch("lib.systemd_service.run")
    @patch("lib.systemd_service.os.listdir", return_value=["auto-update-node.timer", "node-api.service"])
    @patch("lib.systemd_service.os.path.exists", return_value=True)
    def test_cleanup_all_infra_services_handles_remove_failures(
        self, _exists, _listdir, mock_run, _has_install, _remove
    ):
        cleanup_all_infra_services()
        run_commands = [args[0] for args, _ in mock_run.call_args_list]
        self.assertIn("systemctl disable auto-update-node.timer", run_commands)
        self.assertIn("systemctl disable node-api.service", run_commands)
        self.assertIn("systemctl daemon-reload", run_commands)
        self.assertIn("systemctl reset-failed", run_commands)

    @patch("lib.systemd_service.run")
    def test_cleanup_all_persists_rails_secret_before_removing_service(self, mock_run):
        with tempfile.TemporaryDirectory() as temp_dir:
            systemd_dir = os.path.join(temp_dir, "systemd")
            app_path = os.path.join(temp_dir, "apps", "example_com")
            os.makedirs(systemd_dir)
            os.makedirs(app_path)

            service_path = os.path.join(systemd_dir, "rails-example_com.service")
            with open(service_path, "w", encoding="utf-8") as handle:
                handle.write(generate_rails_service("example_com", app_path, "stable-secret"))

            mock_run.return_value.returncode = 0

            with patch("lib.systemd_service.SYSTEMD_DIR", systemd_dir):
                cleanup_all_infra_services()

            secret_path = os.path.join(temp_dir, "apps", ".infra_tools_shared", "example_com", "secret_key_base")
            with open(secret_path, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read().strip(), "stable-secret")
            self.assertFalse(os.path.exists(service_path))

    @patch("lib.systemd_service.os.remove")
    @patch("lib.systemd_service.run")
    @patch("lib.systemd_service.os.listdir", return_value=["auto-update-apt.service", "auto-update-apt.timer"])
    @patch("lib.systemd_service.os.path.exists", return_value=True)
    def test_cleanup_all_infra_services_dry_run(self, _exists, _listdir, mock_run, mock_remove):
        cleanup_all_infra_services(dry_run=True)
        mock_run.assert_not_called()
        mock_remove.assert_not_called()

    @patch("time.sleep")
    @patch("lib.systemd_service.run")
    def test_create_rails_service_restores_persisted_secret(self, mock_run, _sleep):
        with tempfile.TemporaryDirectory() as temp_dir:
            systemd_dir = os.path.join(temp_dir, "systemd")
            app_path = os.path.join(temp_dir, "apps", "example_com")
            secret_dir = os.path.join(temp_dir, "apps", ".infra_tools_shared", "example_com")
            os.makedirs(systemd_dir)
            os.makedirs(app_path)
            os.makedirs(secret_dir)

            with open(os.path.join(secret_dir, "secret_key_base"), "w", encoding="utf-8") as handle:
                handle.write("persisted-secret\n")

            mock_run.return_value.returncode = 0

            with patch("lib.systemd_service.SYSTEMD_DIR", systemd_dir):
                create_rails_service("example_com", app_path, 3000, "rails-example_com", "rails-example_com")

            service_path = os.path.join(systemd_dir, "rails-example_com.service")
            with open(service_path, "r", encoding="utf-8") as handle:
                self.assertIn("SECRET_KEY_BASE=persisted-secret", handle.read())


if __name__ == '__main__':
    unittest.main()
