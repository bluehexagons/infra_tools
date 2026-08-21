"""Tests for opinionated agent-host system type defaults."""

from __future__ import annotations

import unittest
from argparse import Namespace

from lib.config import SetupConfig
from lib.system_types import get_steps_for_system_type


def _setup_args(**overrides: object) -> Namespace:
    values: dict[str, object] = {
        "host": "192.0.2.10",
        "username": "agent",
        "timezone": "UTC",
        "desktop": None,
        "install_office": None,
        "enable_rdp": None,
    }
    values.update(overrides)
    return Namespace(**values)


class TestAgentProfiles(unittest.TestCase):
    def test_agent_vm_defaults_to_github_cli_and_codex(self) -> None:
        config = SetupConfig.from_args(_setup_args(), "agent_vm")

        self.assertEqual(config.selected_agent_tools(), ["gh", "codex"])
        self.assertTrue(config.include_cli_tools)
        self.assertFalse(config.include_desktop)
        self.assertNotIn("--agent-tool", " ".join(config.to_setup_command()))
        self.assertIn("--agent-tool gh", config.to_remote_args())
        self.assertIn("--agent-tool codex", config.to_remote_args())

        step_names = [name for name, _step in get_steps_for_system_type(config)]
        self.assertIn("Installing CLI tools", step_names)
        self.assertIn("Installing GitHub CLI", step_names)
        self.assertIn("Installing Codex CLI", step_names)
        self.assertNotIn("Installing desktop environment", step_names)

    def test_agent_workstation_adds_firefox_desktop(self) -> None:
        config = SetupConfig.from_args(_setup_args(), "agent_workstation")

        self.assertEqual(config.selected_agent_tools(), ["gh", "codex"])
        self.assertEqual(config.browser, "firefox")
        self.assertTrue(config.include_desktop)

        step_names = [name for name, _step in get_steps_for_system_type(config)]
        self.assertIn("Installing desktop environment", step_names)
        self.assertIn("Installing browser", step_names)
        self.assertIn("Installing GitHub CLI", step_names)
        self.assertIn("Installing Codex CLI", step_names)

    def test_explicit_agent_tool_list_replaces_profile_defaults(self) -> None:
        config = SetupConfig.from_args(
            _setup_args(agent_tools=["claude", "opencode"]),
            "agent_vm",
        )

        self.assertEqual(config.selected_agent_tools(), ["claude", "opencode"])
        command = " ".join(config.to_setup_command())
        self.assertIn("--agent-tool claude", command)
        self.assertIn("--agent-tool opencode", command)
        self.assertNotIn("--agent-tool gh", command)
        self.assertNotIn("--agent-tool codex", command)

    def test_empty_agent_tool_list_keeps_profile_defaults(self) -> None:
        config = SetupConfig.from_args(
            _setup_args(agent_tools=[]),
            "agent_vm",
        )

        self.assertEqual(config.selected_agent_tools(), ["gh", "codex"])

    def test_saved_agent_profile_restores_defaults_when_tools_are_missing(self) -> None:
        config = SetupConfig.from_dict(
            "192.0.2.10",
            "agent_vm",
            {"username": "agent"},
        )

        self.assertEqual(config.selected_agent_tools(), ["gh", "codex"])


if __name__ == "__main__":
    unittest.main()
