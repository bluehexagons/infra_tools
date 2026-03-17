"""Tests for common.service_tools.auto_update_ruby."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from common.service_tools import auto_update_ruby


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
        result = auto_update_ruby.main()
        self.assertEqual(result, 0)
        self.assertEqual(mock_installed.call_count, 2)
        self.assertEqual(mock_update.call_count, 2)
        mock_notify.assert_not_called()

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
        result = auto_update_ruby.main()
        self.assertEqual(result, 1)
        mock_notify.assert_called_once()
        self.assertIn("Ruby gem update failed", mock_notify.call_args.kwargs["subject"])


if __name__ == "__main__":
    unittest.main()
