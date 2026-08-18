"""Tests for desktop application setup helpers."""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from lib.config import SetupConfig


class TestDesktopApps(unittest.TestCase):
    @patch("desktop.apps_steps.install_office_apps")
    @patch("desktop.apps_steps.install_browser")
    @patch("desktop.apps_steps.run")
    @patch("desktop.apps_steps.is_package_installed")
    def test_desktop_apps_do_not_install_vscodium(self, mock_package, mock_run, mock_browser, mock_office):
        """Default desktop app bundle should not install VSCodium."""
        from desktop.apps_steps import install_desktop_apps

        mock_package.side_effect = lambda package: package == "discord"
        config = SetupConfig(
            host="test.example.com",
            username="testuser",
            system_type="workstation_desktop",
            use_flatpak=False,
        )

        install_desktop_apps(config)

        commands = " ".join(call.args[0] for call in mock_run.call_args_list)
        self.assertNotIn("codium", commands)
        self.assertNotIn("vscodium", commands.lower())

    def test_desktop_steps_exports_librewolf_default_browser_config(self):
        """desktop.steps should expose the browser implementation with LibreWolf support."""
        from desktop import steps
        from desktop.browser_steps import configure_default_browser

        self.assertIs(steps.configure_default_browser, configure_default_browser)


class TestBrowserSteps(unittest.TestCase):
    def setUp(self):
        home_patcher = patch(
            "desktop.browser_steps.get_user_home",
            return_value="/home/testuser",
        )
        self.addCleanup(home_patcher.stop)
        home_patcher.start()

    @patch("desktop.browser_steps.run")
    @patch("desktop.browser_steps.os.makedirs")
    @patch("desktop.browser_steps.os.path.exists")
    @patch("desktop.browser_steps.file_contains")
    @patch("builtins.open", new_callable=unittest.mock.mock_open)
    def test_configures_librewolf_as_default_browser(
        self,
        mock_open,
        mock_file_contains,
        mock_exists,
        mock_makedirs,
        mock_run,
    ):
        """LibreWolf is the default browser for workstation setups and should be configurable."""
        from desktop.browser_steps import configure_default_browser

        mock_exists.return_value = False
        mock_file_contains.return_value = False
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
        config = SetupConfig(
            host="test.example.com",
            username="testuser",
            system_type="workstation_desktop",
            browser="librewolf",
        )

        configure_default_browser(config)

        write_calls = [call.args[0] for call in mock_open().write.call_args_list]
        self.assertIn("librewolf.desktop", "".join(write_calls))
        run_commands = [call.args[0] for call in mock_run.call_args_list]
        self.assertTrue(
            any(
                "xdg-mime default librewolf.desktop x-scheme-handler/http" in command
                for command in run_commands
            )
        )
        self.assertTrue(
            any(
                "xdg-mime default librewolf.desktop x-scheme-handler/https" in command
                for command in run_commands
            )
        )
        self.assertTrue(
            any(
                "xdg-settings set default-web-browser librewolf.desktop" in command
                for command in run_commands
            )
        )
        self.assertIn("WebBrowser=librewolf", "".join(write_calls))

    @patch("desktop.browser_steps._install_via_extrepo")
    @patch("desktop.browser_steps.is_package_installed")
    def test_librewolf_install_does_not_remove_legacy_repo_files(self, mock_package, mock_extrepo):
        """Legacy LibreWolf repo cleanup has been removed from the install path."""
        from desktop.browser_steps import install_single_browser

        mock_package.return_value = False
        mock_extrepo.return_value = True

        install_single_browser("librewolf", use_flatpak=False)

        mock_extrepo.assert_called_once_with("LibreWolf", "librewolf", "librewolf")

    @patch("desktop.browser_steps._install_helium_browser")
    def test_installs_helium_browser(self, mock_install_helium):
        """Helium should be accepted by the browser installer."""
        from desktop.browser_steps import install_single_browser

        install_single_browser("helium", use_flatpak=False)

        mock_install_helium.assert_called_once_with()

    @patch("desktop.browser_steps.run")
    @patch("desktop.browser_steps.os.makedirs")
    @patch("desktop.browser_steps.os.path.exists")
    @patch("desktop.browser_steps.file_contains")
    @patch("builtins.open", new_callable=unittest.mock.mock_open)
    def test_configures_helium_as_default_browser(
        self,
        mock_open,
        mock_file_contains,
        mock_exists,
        mock_makedirs,
        mock_run,
    ):
        """Helium should be configurable as the default browser."""
        from desktop.browser_steps import configure_default_browser

        mock_exists.return_value = False
        mock_file_contains.return_value = False
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
        config = SetupConfig(
            host="test.example.com",
            username="testuser",
            system_type="workstation_desktop",
            browser="helium",
        )

        configure_default_browser(config)

        write_calls = [call.args[0] for call in mock_open().write.call_args_list]
        self.assertIn("helium.desktop", "".join(write_calls))
        run_commands = [call.args[0] for call in mock_run.call_args_list]
        self.assertTrue(
            any(
                "xdg-mime default helium.desktop x-scheme-handler/http" in command
                for command in run_commands
            )
        )
        self.assertTrue(
            any(
                "xdg-mime default helium.desktop x-scheme-handler/https" in command
                for command in run_commands
            )
        )

    @patch("desktop.browser_steps.os.path.exists")
    @patch("desktop.browser_steps.is_package_installed")
    @patch("desktop.browser_steps.run")
    def test_helium_installer_uses_latest_release_deb(self, mock_run, mock_package, mock_exists):
        """Helium installer should resolve and install the latest Debian package."""
        from desktop.browser_steps import _install_helium_browser

        mock_package.side_effect = [False, True]
        mock_exists.return_value = False
        mock_run.side_effect = [
            Mock(returncode=0, stdout="https://example.test/helium-bin_1.0-1_amd64.deb\n", stderr=""),
            Mock(returncode=0, stdout="", stderr=""),
            Mock(returncode=0, stdout="", stderr=""),
            Mock(returncode=0, stdout="", stderr=""),
        ]

        _install_helium_browser()

        commands = [call.args[0] for call in mock_run.call_args_list]
        self.assertIn("wget -qO /tmp/helium.deb https://example.test/helium-bin_1.0-1_amd64.deb", commands)
        self.assertIn("apt-get install -y -qq /tmp/helium.deb", commands)
        self.assertIn("rm -f /tmp/helium.deb", commands)


if __name__ == "__main__":
    unittest.main()
