"""Tests for common setup steps."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from common.common_steps import update_and_upgrade_packages
from lib.config import SetupConfig


class TestUpdateAndUpgradePackages(unittest.TestCase):
    @patch("common.common_steps.run")
    @patch(
        "common.common_steps.disable_duplicate_vivaldi_source",
        return_value="/etc/apt/sources.list.d/vivaldi.list.disabled-by-infra-tools",
    )
    def test_cleans_duplicate_vivaldi_source_before_apt_update(self, mock_cleanup, mock_run):
        order = []

        def cleanup_side_effect():
            order.append("cleanup")
            return mock_cleanup.return_value

        def run_side_effect(command, *_args, **_kwargs):
            order.append(command)
            return MagicMock(returncode=0)

        mock_cleanup.side_effect = cleanup_side_effect
        mock_run.side_effect = run_side_effect

        update_and_upgrade_packages(SetupConfig(host="testhost", username="testuser", system_type="server_lite"))

        self.assertEqual(order[0], "cleanup")
        self.assertEqual(order[1], "apt-get update -qq")
        self.assertEqual(order[2], "apt-get upgrade -y -qq")
        self.assertEqual(order[3], "apt-get autoremove -y -qq")


if __name__ == "__main__":
    unittest.main()
