"""Security tests for privileged remote deployment operations."""

from __future__ import annotations

import unittest

from lib.remote_deploy import _validate_config_name, _validate_deploy_path
from web.service_tools.deploy_admin import validate_config_name, validate_service_name


class TestDeployAdminValidation(unittest.TestCase):
    def test_nginx_config_name_rejects_path_traversal(self):
        self.assertEqual(validate_config_name("example_com"), "example_com")
        self.assertEqual(_validate_config_name("example.com"), "example_com")
        for invalid in ("../example", "example/name", "example name", ""):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_config_name(invalid)

    def test_service_name_is_limited_to_generated_app_units(self):
        self.assertEqual(validate_service_name("rails-shop.service"), "rails-shop.service")
        self.assertEqual(validate_service_name("node-api.service"), "node-api.service")
        self.assertEqual(validate_service_name("rails-shop"), "rails-shop.service")
        for invalid in (
            "nginx.service",
            "rails-../../ssh.service",
            "rails-shop.service.service",
            "node-.service",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_service_name(invalid)

    def test_deployment_removal_cannot_escape_configured_root(self):
        self.assertEqual(_validate_deploy_path("/var/www/shop", "/var/www"), "/var/www/shop")
        for invalid in ("/var/www", "/var/www/../../etc", "/etc/passwd", "relative/path"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                _validate_deploy_path(invalid, "/var/www")


if __name__ == "__main__":
    unittest.main()
