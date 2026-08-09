"""Tests for hosted/container CLI flag parsing in lib/arg_parser.py."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.arg_parser import create_setup_argument_parser


class TestHostedFlagParsing(unittest.TestCase):
    def setUp(self):
        self.parser = create_setup_argument_parser("Test", for_remote=False)

    def test_hosted_flag(self):
        args = self.parser.parse_args(["10.0.0.50", "--hosted", "10.0.0.1"])
        self.assertEqual(args.hosted_node, "10.0.0.1")

    def test_hosted_user_default_root(self):
        args = self.parser.parse_args(["10.0.0.50", "--hosted", "10.0.0.1"])
        self.assertEqual(args.hosted_user, "root")

    def test_hosted_user_override(self):
        args = self.parser.parse_args([
            "10.0.0.50", "--hosted", "10.0.0.1",
            "--hosted-user", "admin"
        ])
        self.assertEqual(args.hosted_user, "admin")

    def test_hosted_key(self):
        args = self.parser.parse_args([
            "10.0.0.50", "--hosted", "10.0.0.1",
            "--hosted-key", "/path/to/key"
        ])
        self.assertEqual(args.hosted_key, "/path/to/key")

    def test_memory_flag(self):
        args = self.parser.parse_args([
            "10.0.0.50", "--memory", "2G"
        ])
        self.assertEqual(args.container_memory, "2G")

    def test_storage_flag_three_args(self):
        args = self.parser.parse_args([
            "10.0.0.50", "--storage", "root", "auto", "10G"
        ])
        self.assertEqual(args.container_storage, [["root", "auto", "10G"]])

    def test_multiple_storage_specs(self):
        args = self.parser.parse_args([
            "10.0.0.50",
            "--storage", "root", "auto", "10G",
            "--storage", "template", "local"
        ])
        self.assertEqual(
            args.container_storage,
            [["root", "auto", "10G"], ["template", "local"]]
        )

    def test_cores_default_1(self):
        args = self.parser.parse_args(["10.0.0.50"])
        self.assertEqual(args.container_cores, 1)

    def test_cores_override(self):
        args = self.parser.parse_args([
            "10.0.0.50", "--cores", "4"
        ])
        self.assertEqual(args.container_cores, 4)

    def test_base_default_debian(self):
        args = self.parser.parse_args(["10.0.0.50"])
        self.assertEqual(args.container_base, "debian")

    def test_base_override(self):
        args = self.parser.parse_args([
            "10.0.0.50", "--base", "ubuntu"
        ])
        self.assertEqual(args.container_base, "ubuntu")

    def test_full_hosted_command(self):
        args = self.parser.parse_args([
            "10.0.0.50", "--hosted", "10.0.0.1",
            "--memory", "2G", "--storage", "root", "auto", "10G",
            "--cores", "2", "--base", "debian",
            "--name", "web-01"
        ])
        self.assertEqual(args.hosted_node, "10.0.0.1")
        self.assertEqual(args.container_memory, "2G")
        self.assertEqual(args.container_storage, [["root", "auto", "10G"]])
        self.assertEqual(args.container_cores, 2)
        self.assertEqual(args.container_base, "debian")
        self.assertEqual(args.friendly_name, "web-01")

    def test_node_flag_still_installs_nodejs(self):
        """Ensure --node still means install Node.js, not proxmox node."""
        args = self.parser.parse_args(["10.0.0.50", "--node"])
        self.assertTrue(args.install_node)
        self.assertIsNone(args.hosted_node)

    def test_agent_tool_flags(self):
        args = self.parser.parse_args([
            "10.0.0.50",
            "--gh",
            "--codex",
            "--claude",
            "--opencode",
            "--t3code",
            "--copy-keys",
            "--copy-config",
            "--repo", "https://github.com/user/one.git",
            "--repo", "git@github.com:user/two.git",
        ])
        self.assertTrue(args.install_gh)
        self.assertTrue(args.install_codex)
        self.assertTrue(args.install_claude)
        self.assertTrue(args.install_opencode)
        self.assertTrue(args.install_t3code)
        self.assertTrue(args.copy_agent_keys)
        self.assertTrue(args.copy_agent_config)
        self.assertEqual(args.agent_repos, [
            "https://github.com/user/one.git",
            "git@github.com:user/two.git",
        ])

    def test_agent_suite_flag(self):
        args = self.parser.parse_args([
            "10.0.0.50",
            "--agent-suite",
            "terminal",
        ])
        self.assertEqual(args.agent_suite, "terminal")

    def test_rdp_policy_flags(self):
        args = self.parser.parse_args([
            "10.0.0.50",
            "--rdp",
            "--rdp-bind-address", "10.0.0.50",
            "--rdp-source", "10.0.0.0/24",
            "--rdp-source", "2001:db8::/64",
            "--no-rdp-clipboard",
            "--rdp-drive-redirection",
            "--rdp-audio",
            "--rdp-max-sessions", "2",
            "--rdp-kill-disconnected",
            "--rdp-disconnected-timeout", "86400",
            "--rdp-idle-timeout", "14400",
        ])
        self.assertEqual(args.rdp_bind_address, "10.0.0.50")
        self.assertEqual(args.rdp_allowed_sources, ["10.0.0.0/24", "2001:db8::/64"])
        self.assertFalse(args.rdp_clipboard)
        self.assertTrue(args.rdp_drive_redirection)
        self.assertTrue(args.rdp_audio)
        self.assertEqual(args.rdp_max_sessions, 2)
        self.assertTrue(args.rdp_kill_disconnected)
        self.assertEqual(args.rdp_disconnected_timeout, 86400)
        self.assertEqual(args.rdp_idle_timeout, 14400)

    def test_antistatic_flags(self):
        args = self.parser.parse_args([
            "10.0.0.50",
            "--antistatic-server",
            "lobby.example.com:9090",
            "--antistatic-admin",
            "operator",
            "--antistatic-db",
            "db.example.com:9091",
        ])
        self.assertEqual(args.antistatic_server, "lobby.example.com:9090")
        self.assertEqual(args.antistatic_admin, "operator")
        self.assertEqual(args.antistatic_db, "db.example.com:9091")

    def test_antistatic_admin_can_be_disabled(self):
        args = self.parser.parse_args(["10.0.0.50", "--no-antistatic-admin"])
        self.assertEqual(args.antistatic_admin, "")

    def test_gogs_flag_with_domain_only(self):
        args = self.parser.parse_args([
            "10.0.0.50",
            "--gogs",
            "git.example.com:3000",
        ])
        self.assertEqual(args.gogs, ["git.example.com:3000"])

    def test_gogs_flag_with_optional_data_path(self):
        args = self.parser.parse_args([
            "10.0.0.50",
            "--gogs",
            "git.example.com:3000",
            "/srv/gogs",
        ])
        self.assertEqual(args.gogs, ["git.example.com:3000", "/srv/gogs"])


class TestHostedFlagsNotInRemoteParser(unittest.TestCase):
    def setUp(self):
        self.parser = create_setup_argument_parser(
            "Remote", for_remote=True
        )

    def test_no_hosted_flag(self):
        """The --hosted flag should not exist in the remote parser."""
        args = self.parser.parse_args([
            "--system-type", "server_lite", "--username", "root"
        ])
        self.assertFalse(hasattr(args, 'hosted_node'))

    def test_no_memory_flag(self):
        args = self.parser.parse_args([
            "--system-type", "server_lite", "--username", "root"
        ])
        self.assertFalse(hasattr(args, 'container_memory'))

    def test_agent_tool_flags_exist_remotely(self):
        args = self.parser.parse_args([
            "--system-type", "server_dev",
            "--username", "agentuser",
            "--gh",
            "--codex",
            "--claude",
            "--opencode",
            "--t3code",
            "--copy-keys",
            "--copy-config",
            "--repo", "https://github.com/user/repo.git",
        ])
        self.assertTrue(args.install_gh)
        self.assertTrue(args.install_codex)
        self.assertTrue(args.install_claude)
        self.assertTrue(args.install_opencode)
        self.assertTrue(args.install_t3code)
        self.assertTrue(args.copy_agent_keys)
        self.assertTrue(args.copy_agent_config)
        self.assertEqual(args.agent_repos, ["https://github.com/user/repo.git"])


if __name__ == '__main__':
    unittest.main()
