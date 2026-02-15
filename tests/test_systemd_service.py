"""Tests for lib/systemd_service.py: service config generation."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import call, mock_open, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.systemd_service import (
    cleanup_all_infra_services,
    cleanup_service,
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
    @patch("lib.systemd_service.open", new_callable=mock_open, read_data="[Unit]\n[Install]\n")
    def test_cleanup_service_disables_service_with_install(self, _open, _exists, mock_run, mock_remove):
        cleanup_service("demo")

        mock_run.assert_has_calls(
            [
                call("systemctl stop demo.timer", check=False),
                call("systemctl disable demo.timer", check=False),
                call("systemctl stop demo.service", check=False),
                call("systemctl disable demo.service", check=False),
                call("systemctl daemon-reload", check=False),
            ]
        )
        mock_remove.assert_has_calls(
            [
                call("/etc/systemd/system/demo.timer"),
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

    @patch("lib.systemd_service.os.remove")
    @patch("lib.systemd_service.run")
    @patch("lib.systemd_service.os.listdir", return_value=["auto-update-ruby.service", "auto-update-ruby.timer"])
    @patch("lib.systemd_service.os.path.exists", return_value=True)
    def test_cleanup_all_infra_services_dry_run(self, _exists, _listdir, mock_run, mock_remove):
        cleanup_all_infra_services(dry_run=True)
        mock_run.assert_not_called()
        mock_remove.assert_not_called()


if __name__ == '__main__':
    unittest.main()
