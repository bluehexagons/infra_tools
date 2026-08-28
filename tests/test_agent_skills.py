"""Tests for base workflow skills installed on agent VMs."""

from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from common.agent_steps import (
    AGENT_SKILLS_ROOT,
    BASE_AGENT_SKILL_NAMES,
    install_managed_agent_skills,
)
from common.godot_web_steps import GODOT_AGENT_SKILLS
from common.t3code_steps import T3_AGENT_SKILL_NAMES
from lib.config import SetupConfig
from lib.types import StepFunc
from plugins.common import extend_agent_steps


class ManagedAgentSkillTests(unittest.TestCase):
    def _account(self, home: str) -> SimpleNamespace:
        return SimpleNamespace(
            pw_dir=home,
            pw_uid=os.getuid(),
            pw_gid=os.getgid(),
        )

    def test_installs_and_refreshes_the_base_managed_skill_set(self) -> None:
        expected = {
            "infra-tools-agent-operations",
            "infra-tools-agent-workspace",
            "infra-tools-browser-testing",
            "infra-tools-deploy-smoke",
            "infra-tools-shared-assets",
            "infra-tools-vm-triage",
        }
        self.assertEqual(set(BASE_AGENT_SKILL_NAMES), expected)

        with tempfile.TemporaryDirectory() as home:
            with (
                patch(
                    "common.agent_steps.pwd.getpwnam",
                    return_value=self._account(home),
                ),
                patch("common.agent_steps.os.chown"),
            ):
                self.assertTrue(
                    install_managed_agent_skills(
                        "agent",
                        ["codex"],
                        source_root=AGENT_SKILLS_ROOT,
                    )
                )
                self.assertFalse(
                    install_managed_agent_skills(
                        "agent",
                        ["codex"],
                        source_root=AGENT_SKILLS_ROOT,
                    )
                )

            for skill_name in BASE_AGENT_SKILL_NAMES:
                path = os.path.join(
                    home,
                    ".agents",
                    "skills",
                    skill_name,
                    "SKILL.md",
                )
                with open(path, encoding="utf-8") as file_obj:
                    content = file_obj.read()
                self.assertIn(f"name: {skill_name}", content)
                self.assertIn("managed-by: infra_tools", content)

    def test_every_managed_skill_belongs_to_an_installer_catalog(self) -> None:
        source_names = {
            entry.name
            for entry in os.scandir(AGENT_SKILLS_ROOT)
            if entry.is_dir(follow_symlinks=False)
        }
        installed_names = {
            *BASE_AGENT_SKILL_NAMES,
            *T3_AGENT_SKILL_NAMES,
            *GODOT_AGENT_SKILLS,
        }

        self.assertEqual(source_names, installed_names)

    def test_skips_shared_skills_for_an_unsupported_agent(self) -> None:
        with patch("common.agent_steps.pwd.getpwnam") as getpwnam:
            self.assertFalse(install_managed_agent_skills("agent", ["claude"]))

        getpwnam.assert_not_called()

    def test_refuses_to_replace_an_unmanaged_skill(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            skill_name = BASE_AGENT_SKILL_NAMES[0]
            skill_dir = os.path.join(home, ".agents", "skills", skill_name)
            os.makedirs(skill_dir)
            with open(
                os.path.join(skill_dir, "SKILL.md"),
                "w",
                encoding="utf-8",
            ) as file_obj:
                file_obj.write("name: user-owned\n")

            with (
                patch(
                    "common.agent_steps.pwd.getpwnam",
                    return_value=self._account(home),
                ),
                patch("common.agent_steps.os.chown"),
            ):
                with self.assertRaisesRegex(RuntimeError, "unmanaged agent skill"):
                    install_managed_agent_skills(
                        "agent",
                        ["opencode"],
                        (skill_name,),
                        source_root=AGENT_SKILLS_ROOT,
                    )

    def test_standard_agent_steps_install_base_skills_for_compatible_tools(
        self,
    ) -> None:
        config = SetupConfig(
            host="host",
            username="agent",
            system_type="agent_vm",
            agent_tools=["codex"],
            install_codex=True,
        )
        steps: list[tuple[str, StepFunc]] = []

        extend_agent_steps(config, steps)

        names = [name for name, _step in steps]
        self.assertLess(
            names.index("Installing agent VM management command"),
            names.index("Installing managed agent workflow skills"),
        )

    def test_standard_agent_steps_skip_shared_skills_for_claude_only(self) -> None:
        config = SetupConfig(
            host="host",
            username="agent",
            system_type="agent_vm",
            agent_tools=["claude"],
            install_claude=True,
        )
        steps: list[tuple[str, StepFunc]] = []

        extend_agent_steps(config, steps)

        names = [name for name, _step in steps]
        self.assertIn("Installing agent VM management command", names)
        self.assertNotIn("Installing managed agent workflow skills", names)


if __name__ == "__main__":
    unittest.main()
