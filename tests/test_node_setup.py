"""Tests for Node.js setup behavior."""

from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import mock_open, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import common.common_steps as common_steps
from lib.config import SetupConfig
from lib.update_policy import (
    DEPENDENCY_MIN_AGE_DAYS_ENV,
    ECOSYSTEM_AUTO_UPGRADE_ENV,
    NODE_LATEST_AUTO_UPDATE_ENV,
)
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

    @patch("common.common_steps.open", new_callable=mock_open, read_data="")
    @patch("common.common_steps.os.path.exists")
    @patch("common.common_steps.run")
    def test_install_node_uses_npm_freshness_cutoff(self, mock_run, mock_exists, _open):
        def exists(path: str) -> bool:
            return path in {"/home/user/.nvm/nvm.sh", "/home/user/.bashrc"}

        mock_exists.side_effect = exists
        mock_run.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")
        config = SetupConfig(host="host", username="user", system_type="server_web", install_node=True)

        with patch.dict(os.environ, {DEPENDENCY_MIN_AGE_DAYS_ENV: "2"}):
            common_steps.install_node(config)

        commands = [args[0] for args, _ in mock_run.call_args_list]
        npm_commands = [command for command in commands if "npm install -g" in command]
        self.assertEqual(len(npm_commands), 2)
        self.assertTrue(all("--before=" in command for command in npm_commands))


if __name__ == "__main__":
    unittest.main()
