"""Tests for shared SSH/SCP/rsync command builders."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.ssh_utils import (
    build_rsync_ssh_transport,
    build_scp_command,
    build_ssh_command,
    chain_remote_commands,
    shell_join,
)


class TestSshUtils(unittest.TestCase):
    def test_shell_join_quotes_spaces(self):
        self.assertEqual(shell_join(["cat", "/tmp/file name.txt"]), "cat '/tmp/file name.txt'")

    def test_chain_remote_commands_quotes_each_command(self):
        command = chain_remote_commands(
            [
                ["mkdir", "-p", "/tmp/infra tools"],
                ["python3", "/opt/infra_tools/remote_setup.py", "--name", "web node"],
            ]
        )
        self.assertEqual(
            command,
            "mkdir -p '/tmp/infra tools' && python3 /opt/infra_tools/remote_setup.py --name 'web node'",
        )

    @patch("lib.ssh_utils.ensure_workspace_dir")
    @patch("lib.ssh_utils.get_known_hosts_path", return_value="/tmp/workspace/known_hosts")
    def test_build_ssh_command_with_remote_command(self, _mock_known_hosts, _mock_ensure_workspace):
        command = build_ssh_command(
            "example.com",
            "deploy",
            "/tmp/key",
            port=2222,
            remote_command="echo ok",
            batch_mode=True,
            server_alive_interval=None,
        )
        self.assertEqual(
            command,
            [
                "ssh",
                "-i",
                "/tmp/key",
                "-p",
                "2222",
                "-o",
                "UserKnownHostsFile=/tmp/workspace/known_hosts",
                "-o",
                "StrictHostKeyChecking=accept-new",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=30",
                "deploy@example.com",
                "echo ok",
            ],
        )

    @patch("lib.ssh_utils.ensure_workspace_dir")
    @patch("lib.ssh_utils.get_known_hosts_path", return_value="/tmp/workspace/known_hosts")
    def test_build_scp_command(self, _mock_known_hosts, _mock_ensure_workspace):
        command = build_scp_command(
            "example.com",
            "deploy",
            "/tmp/local file",
            "/tmp/remote file",
            "/tmp/key",
            port=2222,
        )
        self.assertEqual(
            command,
            [
                "scp",
                "-i",
                "/tmp/key",
                "-P",
                "2222",
                "-o",
                "UserKnownHostsFile=/tmp/workspace/known_hosts",
                "-o",
                "StrictHostKeyChecking=accept-new",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=30",
                "/tmp/local file",
                "deploy@example.com:/tmp/remote file",
            ],
        )

    @patch("lib.ssh_utils.ensure_workspace_dir")
    @patch("lib.ssh_utils.get_known_hosts_path", return_value="/tmp/workspace/known_hosts")
    def test_build_rsync_ssh_transport_quotes_key_path(self, _mock_known_hosts, _mock_ensure_workspace):
        transport = build_rsync_ssh_transport(ssh_key="/tmp/key file", port=2222)
        self.assertIn("ssh", transport)
        self.assertIn("'/tmp/key file'", transport)
        self.assertIn("-p 2222", transport)
        self.assertIn("UserKnownHostsFile=/tmp/workspace/known_hosts", transport)


if __name__ == "__main__":
    unittest.main()
