"""Tests for coding-agent security options and propagation."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.arg_parser import create_setup_argument_parser
from lib.config import SetupConfig


class TestAgentSecurityConfig(unittest.TestCase):
    def test_security_flags_propagate_to_remote_setup(self):
        config = SetupConfig(
            host="testhost",
            username="agent",
            system_type="agent_vm",
            machine_type="vm",
            nopasswd=True,
        )

        self.assertIn("--nopasswd", config.to_remote_args())
        self.assertIn("--nopasswd", config.to_setup_command())

    def test_harden_agent_propagates_to_remote_setup(self):
        config = SetupConfig(
            host="testhost",
            username="agent",
            system_type="agent_vm",
            harden_agent=True,
        )

        self.assertIn("--harden-agent", config.to_remote_args())
        self.assertIn("--harden-agent", config.to_setup_command())

    def test_nopasswd_and_hardening_are_mutually_exclusive(self):
        with self.assertRaisesRegex(ValueError, "cannot be combined"):
            SetupConfig(
                host="testhost",
                username="agent",
                system_type="agent_vm",
                nopasswd=True,
                harden_agent=True,
            )

    def test_hardening_rejects_root_identity(self):
        with self.assertRaisesRegex(ValueError, "non-root setup user"):
            SetupConfig(
                host="testhost",
                username="root",
                system_type="agent_vm",
                harden_agent=True,
            )

    def test_parser_accepts_security_flags(self):
        parser = create_setup_argument_parser("test")
        args = parser.parse_args(
            ["testhost", "agent", "--nopasswd"]
        )

        self.assertTrue(args.nopasswd)
        self.assertFalse(args.harden_agent)


if __name__ == "__main__":
    unittest.main()
