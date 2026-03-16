"""Tests for Ruby setup behavior."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import call, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.config import SetupConfig
from lib.system_types import get_steps_for_system_type
import common.common_steps as common_steps


class TestRubySetup(unittest.TestCase):
    @patch("common.common_steps.shutil.which", side_effect=["/usr/bin/ruby", None, "/usr/bin/bundler"])
    @patch("common.common_steps.run")
    def test_install_ruby_skips_when_already_installed(self, mock_run, _which):
        config = SetupConfig(host="host", username="user", system_type="server_dev", install_ruby=True)
        common_steps.install_ruby(config)
        mock_run.assert_not_called()

    @patch("common.common_steps.shutil.which", side_effect=[None, None, None])
    @patch("common.common_steps.run")
    def test_install_ruby_uses_apt_packages(self, mock_run, _which):
        config = SetupConfig(host="host", username="user", system_type="server_dev", install_ruby=True)
        common_steps.install_ruby(config)
        mock_run.assert_has_calls([
            call("apt-get -o DPkg::Lock::Timeout=60 install -y -qq ruby ruby-dev bundler"),
            call("gem install bundler", check=False),
        ])

    @patch("common.common_steps.shutil.which", side_effect=["/usr/bin/ruby", None, None])
    @patch("common.common_steps.run")
    def test_install_ruby_reinstalls_when_bundler_missing(self, mock_run, _which):
        config = SetupConfig(host="host", username="user", system_type="server_dev", install_ruby=True)
        common_steps.install_ruby(config)
        mock_run.assert_has_calls([
            call("apt-get -o DPkg::Lock::Timeout=60 install -y -qq ruby ruby-dev bundler"),
            call("gem install bundler", check=False),
        ])

    def test_configure_auto_update_ruby_uses_apt_auto_update(self):
        """Ruby updates are handled by the apt auto-update service, no cleanup needed."""
        config = SetupConfig(host="host", username="user", system_type="server_dev", install_ruby=True)
        with patch("common.common_steps.print") as mock_print:
            common_steps.configure_auto_update_ruby(config)
            mock_print.assert_called_once()
            args = mock_print.call_args[0][0]
            self.assertIn("auto-update", args)

    def test_ruby_auto_update_step_uses_common_cleanup_implementation(self):
        config = SetupConfig(host="host", username="user", system_type="server_dev", install_ruby=True)
        ruby_steps = [(name, func) for name, func in get_steps_for_system_type(config) if "Ruby" in name]
        self.assertIn(
            ("Configuring Ruby auto-update", common_steps.configure_auto_update_ruby),
            ruby_steps,
        )


if __name__ == "__main__":
    unittest.main()
