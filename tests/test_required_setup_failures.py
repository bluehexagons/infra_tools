"""Tests that required setup mutations cannot fail silently."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from lib.config import SetupConfig
from security.security_steps import configure_firewall
from web.cicd_steps import create_cicd_directories, install_cicd_dependencies


def _config() -> SetupConfig:
    return SetupConfig(host="target", username="admin", system_type="server_lite")


class TestRequiredCICDMutations(unittest.TestCase):
    @patch("web.cicd_steps.run")
    @patch("web.cicd_steps.is_package_installed", return_value=False)
    def test_missing_dependency_after_install_stops_setup(
        self, _installed, mock_run
    ) -> None:
        with self.assertRaisesRegex(RuntimeError, "not present after installation"):
            install_cicd_dependencies(_config())

        mock_run.assert_called_once_with(
            ["apt-get", "install", "-y", "-qq", "git"],
        )

    @patch("web.cicd_steps.os.makedirs")
    @patch("web.cicd_steps.run", return_value=SimpleNamespace(returncode=1))
    def test_missing_service_user_stops_directory_setup(
        self, _run, _makedirs
    ) -> None:
        with self.assertRaisesRegex(RuntimeError, "user 'webhook' does not exist"):
            create_cicd_directories(_config())

    @patch("web.cicd_steps.os.makedirs")
    @patch("web.cicd_steps.run")
    def test_directory_permission_failure_reaches_caller(
        self, mock_run, _makedirs
    ) -> None:
        def run_side_effect(
            command: str | list[str],
            **_kwargs: object,
        ) -> SimpleNamespace:
            if command == ["id", "webhook"]:
                return SimpleNamespace(returncode=0)
            raise RuntimeError("permission mutation failed")

        mock_run.side_effect = run_side_effect

        with self.assertRaisesRegex(RuntimeError, "permission mutation failed"):
            create_cicd_directories(_config())


class TestRequiredFirewallMutations(unittest.TestCase):
    @patch("security.security_steps.is_container", return_value=False)
    @patch("security.security_steps.run")
    def test_default_policy_failure_reaches_caller(
        self, mock_run, _container
    ) -> None:
        def run_side_effect(command: str, **kwargs: object) -> SimpleNamespace:
            if command.startswith("ufw status 2>"):
                return SimpleNamespace(returncode=1, stdout="")
            if command == "ufw default deny incoming":
                self.assertTrue(kwargs["check"])
                raise RuntimeError("default policy failed")
            return SimpleNamespace(returncode=0, stdout="")

        mock_run.side_effect = run_side_effect

        with self.assertRaisesRegex(RuntimeError, "default policy failed"):
            configure_firewall(_config())

    @patch("security.security_steps.is_container", return_value=False)
    @patch("security.security_steps.run")
    def test_enable_failure_stops_non_container_setup(
        self, mock_run, _container
    ) -> None:
        def run_side_effect(command: str, **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(
                returncode=(
                    1
                    if command.startswith("ufw status 2>")
                    or command == "ufw --force enable"
                    else 0
                ),
                stdout="",
            )

        mock_run.side_effect = run_side_effect

        with self.assertRaisesRegex(RuntimeError, "Firewall could not be enabled"):
            configure_firewall(_config())

    @patch("security.security_steps.is_container", return_value=True)
    @patch("security.security_steps.run")
    def test_enable_failure_remains_best_effort_in_container(
        self, mock_run, _container
    ) -> None:
        def run_side_effect(command: str, **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(
                returncode=(
                    1
                    if command.startswith("ufw status 2>")
                    or command == "ufw --force enable"
                    else 0
                ),
                stdout="",
            )

        mock_run.side_effect = run_side_effect

        with patch("builtins.print") as mock_print:
            configure_firewall(_config())

        mock_print.assert_any_call(
            "  ⚠ Firewall could not be enabled (container may lack capabilities)"
        )


if __name__ == "__main__":
    unittest.main()
