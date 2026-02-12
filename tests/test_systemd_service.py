"""Tests for lib/systemd_service.py: service config generation."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.systemd_service import generate_node_service, generate_rails_service


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


if __name__ == '__main__':
    unittest.main()
