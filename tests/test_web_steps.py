"""Regression tests for transactional Nginx base-configuration steps."""

from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import mock_open, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.config import SetupConfig
from web import web_steps


def _config() -> SetupConfig:
    return SetupConfig(host="web", username="admin", system_type="server_web")


class TestNginxBaseConfiguration(unittest.TestCase):
    @patch("web.web_steps.file_contains", return_value=False)
    @patch("web.web_steps.os.path.exists", return_value=True)
    @patch("web.web_steps.open", new_callable=mock_open, read_data="previous config")
    @patch("web.web_steps.run")
    def test_security_config_restores_previous_content_when_validation_fails(
        self, mock_run, mock_file, _exists, _contains
    ) -> None:
        mock_run.side_effect = lambda command, **_kwargs: SimpleNamespace(
            returncode=1 if command == "nginx -t" else 0
        )

        with self.assertRaisesRegex(RuntimeError, "failed validation"):
            web_steps.configure_nginx_security(_config())

        commands = [call.args[0] for call in mock_run.call_args_list]
        self.assertIn("nginx -t", commands)
        self.assertNotIn("systemctl reload nginx", commands)
        self.assertGreaterEqual(mock_file().write.call_count, 2)
        self.assertEqual(mock_file().write.call_args_list[-1].args[0], "previous config")

    @patch("web.web_steps.os.path.exists", return_value=True)
    @patch("web.web_steps.open", new_callable=mock_open, read_data="previous site")
    @patch("web.web_steps.run")
    def test_default_site_restores_its_own_content_when_validation_fails(
        self, mock_run, mock_file, _exists
    ) -> None:
        mock_run.side_effect = lambda command, **_kwargs: SimpleNamespace(
            returncode=1 if command == "nginx -t" else 0
        )

        with self.assertRaisesRegex(RuntimeError, "failed validation"):
            web_steps.configure_default_site(_config())

        commands = [call.args[0] for call in mock_run.call_args_list]
        self.assertIn("nginx -t", commands)
        self.assertNotIn("systemctl reload nginx", commands)
        self.assertEqual(mock_file().write.call_args_list[-1].args[0], "previous site")

    @patch("web.web_steps.file_contains", return_value=False)
    @patch("web.web_steps.os.path.exists", return_value=True)
    @patch("web.web_steps.open", new_callable=mock_open, read_data="previous config")
    @patch("web.web_steps.run", return_value=SimpleNamespace(returncode=0))
    def test_security_config_reloads_only_after_validation(
        self, mock_run, _file, _exists, _contains
    ) -> None:
        web_steps.configure_nginx_security(_config())

        commands = [call.args[0] for call in mock_run.call_args_list]
        self.assertLess(commands.index("nginx -t"), commands.index("systemctl reload nginx"))

    @patch("web.web_steps.run")
    @patch("web.web_steps.install_package", return_value=False)
    @patch("web.web_steps.is_service_active", return_value=False)
    @patch("web.web_steps.is_package_installed", return_value=False)
    def test_install_failure_stops_nginx_setup(
        self, _installed, _active, _install, mock_run
    ) -> None:
        with self.assertRaisesRegex(RuntimeError, "required nginx package"):
            web_steps.install_nginx(_config())

        mock_run.assert_not_called()

    @patch("web.web_steps.run")
    @patch("web.web_steps.install_package", return_value=True)
    @patch("web.web_steps.is_service_active", return_value=False)
    @patch("web.web_steps.is_package_installed", return_value=False)
    def test_inactive_service_stops_nginx_setup(
        self, _installed, _active, _install, mock_run
    ) -> None:
        with self.assertRaisesRegex(RuntimeError, "did not become active"):
            web_steps.install_nginx(_config())

        mock_run.assert_any_call("systemctl enable nginx", check=True)
        mock_run.assert_any_call("systemctl start nginx", check=True)


if __name__ == "__main__":
    unittest.main()
