"""Tests for Node.js setup behavior."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.config import SetupConfig
from lib.update_policy import ECOSYSTEM_AUTO_UPGRADE_ENV, NODE_LATEST_AUTO_UPDATE_ENV
from web import dev_tools_steps


class TestNodeSetup(unittest.TestCase):
    @patch("web.dev_tools_steps._configure_auto_update_systemd")
    def test_configure_auto_update_node_disables_risky_auto_upgrades(self, mock_configure):
        config = SetupConfig(host="host", username="user", system_type="server_web", install_node=True)
        dev_tools_steps.configure_auto_update_node(config)
        mock_configure.assert_called_once_with(
            service_name="auto-update-node",
            service_desc="Auto-update Node.js via nvm",
            timer_desc="Auto-update Node.js weekly",
            script_name="auto_update_node.py",
            schedule="Sun *-*-* 03:00:00",
            check_path="/home/user/.nvm",
            check_name="Node.js",
            user="user",
            environment={
                ECOSYSTEM_AUTO_UPGRADE_ENV: "0",
                NODE_LATEST_AUTO_UPDATE_ENV: "0",
            },
        )


if __name__ == "__main__":
    unittest.main()
