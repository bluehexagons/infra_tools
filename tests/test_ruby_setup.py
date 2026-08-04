"""Tests for Ruby setup behavior."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.config import SetupConfig
from lib.system_types import get_steps_for_system_type
from lib.update_policy import ECOSYSTEM_AUTO_UPGRADE_ENV
import common.common_steps as common_steps


class TestRubySetup(unittest.TestCase):
    @patch("common.common_steps.shutil.which", side_effect=["/usr/bin/ruby", None, "/usr/bin/bundler"])
    @patch("common.common_steps.run")
    def test_install_ruby_skips_when_already_installed(self, mock_run, _which):
        config = SetupConfig(host="host", username="user", system_type="server_dev", install_ruby=True)
        common_steps.install_ruby(config)
        mock_run.assert_not_called()

    @patch("common.common_steps.shutil.which", side_effect=[None, "/usr/bin/ruby", "/usr/bin/bundle"])
    @patch("common.common_steps.run")
    def test_install_ruby_uses_apt_packages(self, mock_run, _which):
        config = SetupConfig(host="host", username="user", system_type="server_dev", install_ruby=True)
        common_steps.install_ruby(config)
        mock_run.assert_called_once_with(
            "apt-get -o DPkg::Lock::Timeout=60 install -y -qq ruby ruby-dev bundler",
            check=False,
        )

    @patch("common.common_steps.shutil.which", side_effect=[
        "/usr/bin/ruby",
        None,
        None,
        "/usr/bin/ruby",
        None,
        None,
        "/usr/bin/ruby",
    ])
    @patch("common.common_steps.run")
    def test_install_ruby_reinstalls_when_bundler_missing(self, mock_run, _which):
        config = SetupConfig(host="host", username="user", system_type="server_dev", install_ruby=True)
        common_steps.install_ruby(config)
        mock_run.assert_called_once_with(
            "apt-get -o DPkg::Lock::Timeout=60 install -y -qq ruby ruby-dev bundler",
            check=False,
        )

    @patch("common.common_steps.configure_auto_update_timer")
    @patch("common.common_steps.shutil.which", return_value="/usr/bin/gem")
    def test_configure_auto_update_ruby_configures_gem_update_service(self, _which, mock_configure):
        config = SetupConfig(host="host", username="user", system_type="server_dev", install_ruby=True)
        common_steps.configure_auto_update_ruby(config)
        mock_configure.assert_called_once_with(
            service_name="auto-update-ruby",
            service_desc="Auto-update global Ruby gems",
            timer_desc="Auto-update Ruby gems weekly",
            script_path="/opt/infra_tools/common/service_tools/auto_update_ruby.py",
            schedule="Sun *-*-* 04:00:00",
            check_path="/usr/bin/gem",
            check_name="Ruby gems",
            environment={ECOSYSTEM_AUTO_UPGRADE_ENV: "0"},
        )

    def test_ruby_auto_update_step_uses_common_cleanup_implementation(self):
        config = SetupConfig(host="host", username="user", system_type="server_dev", install_ruby=True)
        ruby_steps = [(name, func) for name, func in get_steps_for_system_type(config) if "Ruby" in name]
        self.assertIn(
            ("Configuring Ruby auto-update", common_steps.configure_auto_update_ruby),
            ruby_steps,
        )


if __name__ == "__main__":
    unittest.main()
