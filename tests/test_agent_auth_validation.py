"""Tests for unambiguous agent credential source declarations."""

from __future__ import annotations

import unittest

from lib.config import SetupConfig
from lib.validation import validate_agent_git_settings


class AgentAuthValidationTests(unittest.TestCase):
    def test_rejects_duplicate_agent_auth_file_tools(self) -> None:
        config = SetupConfig(
            host="target",
            username="agent",
            system_type="server_dev",
            agent_tools=["codex"],
            agent_auth_files=[
                ["codex", "/run/secrets/first.json"],
                ["codex", "/run/secrets/second.json"],
            ],
        )

        with self.assertRaisesRegex(ValueError, "Duplicate --agent-auth-file"):
            validate_agent_git_settings(config)

    def test_rejects_duplicate_github_sources(self) -> None:
        config = SetupConfig(
            host="target",
            username="agent",
            system_type="server_dev",
            agent_tools=["gh"],
            git_access="read",
            git_auth_source="active",
            agent_auth_files=[["gh", "/run/secrets/hosts.yml"]],
        )

        with self.assertRaisesRegex(ValueError, "either --git-auth"):
            validate_agent_git_settings(config)


if __name__ == "__main__":
    unittest.main()
