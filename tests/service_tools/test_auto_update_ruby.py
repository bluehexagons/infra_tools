"""Tests for common.service_tools.auto_update_ruby."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from common.service_tools import auto_update_ruby
from lib.update_policy import ECOSYSTEM_AUTO_UPGRADE_ENV


class TestAutoUpdateRuby(unittest.TestCase):
    @patch("common.service_tools.auto_update_ruby.send_notification_safe")
    @patch("common.service_tools.auto_update_ruby.update_gem", side_effect=[(True, "ok"), (True, "ok")])
    @patch("common.service_tools.auto_update_ruby.gem_installed", side_effect=[True, True])
    @patch("common.service_tools.auto_update_ruby.load_notification_configs_from_state", return_value=[])
    @patch("common.service_tools.auto_update_ruby.shutil.which", return_value="/usr/bin/gem")
    def test_updates_managed_global_gems(
        self,
        _which,
        _configs,
        mock_installed,
        mock_update,
        mock_notify,
    ):
        with patch.dict(os.environ, {ECOSYSTEM_AUTO_UPGRADE_ENV: "1"}):
            with self.assertLogs(auto_update_ruby.logger, level="INFO") as logs:
                result = auto_update_ruby.main()
        self.assertEqual(result, 0)
        self.assertEqual(mock_installed.call_count, 2)
        self.assertEqual(mock_update.call_count, 2)
        mock_notify.assert_not_called()
        self.assertIn("Updated Ruby gems | gems='bundler, rails'", "\n".join(logs.output))

    @patch("common.service_tools.auto_update_ruby.send_notification_safe")
    @patch("common.service_tools.auto_update_ruby.update_gem", side_effect=[(False, "permission denied"), (True, "ok")])
    @patch("common.service_tools.auto_update_ruby.gem_installed", side_effect=[True, True])
    @patch("common.service_tools.auto_update_ruby.load_notification_configs_from_state", return_value=["cfg"])
    @patch("common.service_tools.auto_update_ruby.shutil.which", return_value="/usr/bin/gem")
    def test_notifies_on_gem_update_failure(
        self,
        _which,
        _configs,
        _installed,
        _update,
        mock_notify,
    ):
        with patch.dict(os.environ, {ECOSYSTEM_AUTO_UPGRADE_ENV: "1"}):
            result = auto_update_ruby.main()
        self.assertEqual(result, 1)
        mock_notify.assert_called_once()
        self.assertIn("Ruby gem update failed", mock_notify.call_args.kwargs["subject"])

    @patch("common.service_tools.auto_update_ruby.update_gem")
    @patch("common.service_tools.auto_update_ruby.gem_installed")
    @patch("common.service_tools.auto_update_ruby.load_notification_configs_from_state", return_value=[])
    @patch("common.service_tools.auto_update_ruby.shutil.which", return_value="/usr/bin/gem")
    def test_skips_gem_updates_by_default(
        self,
        _which,
        _configs,
        mock_installed,
        mock_update,
    ):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertLogs(auto_update_ruby.logger, level="INFO") as logs:
                result = auto_update_ruby.main()

        self.assertEqual(result, 0)
        mock_installed.assert_not_called()
        mock_update.assert_not_called()
        self.assertIn("Ruby gem auto-upgrades disabled by policy", "\n".join(logs.output))

    @patch("common.service_tools.auto_update_ruby.run_gem_command")
    def test_update_gem_logs_structured_failure(self, mock_run_command):
        mock_run_command.return_value = unittest.mock.Mock(
            returncode=1,
            stdout="",
            stderr="permission denied",
        )

        with self.assertLogs(auto_update_ruby.logger, level="ERROR") as logs:
            success, details = auto_update_ruby.update_gem("bundler")

        self.assertFalse(success)
        self.assertEqual(details, "permission denied")
        self.assertIn("gem update failed | gem_name='bundler' stderr='permission denied'", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
