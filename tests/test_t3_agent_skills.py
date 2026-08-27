"""Tests for the managed workflow skills installed with T3 Code."""

from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from common.t3code_steps import T3_AGENT_SKILL_NAMES, _ensure_t3_agent_skill
from lib.agent_cli import _t3_agent_skills_ready


class ManagedT3AgentSkillTests(unittest.TestCase):
    def test_installs_all_self_contained_managed_skills(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            account = SimpleNamespace(
                pw_dir=home,
                pw_uid=os.getuid(),
                pw_gid=os.getgid(),
            )
            with (
                patch("common.t3code_steps.pwd.getpwnam", return_value=account),
                patch("common.t3code_steps.os.chown"),
            ):
                self.assertTrue(_ensure_t3_agent_skill("agent", ["codex"]))

            self.assertEqual(
                set(T3_AGENT_SKILL_NAMES),
                {
                    "infra-tools-agent-workspace",
                    "infra-tools-deploy-smoke",
                    "infra-tools-t3code",
                    "infra-tools-vm-triage",
                    "infra-tools-web-gateway",
                },
            )
            for skill_name in T3_AGENT_SKILL_NAMES:
                path = os.path.join(home, ".agents", "skills", skill_name, "SKILL.md")
                with open(path, encoding="utf-8") as file_obj:
                    content = file_obj.read()
                self.assertIn(f"name: {skill_name}", content)
                self.assertIn("managed-by: infra_tools", content)

    def test_skips_skill_install_without_a_supported_agent(self) -> None:
        with patch("common.t3code_steps.pwd.getpwnam") as account:
            self.assertFalse(_ensure_t3_agent_skill("agent", ["gh"]))
        account.assert_not_called()

    def test_doctor_requires_the_complete_managed_skill_set(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            for skill_name in T3_AGENT_SKILL_NAMES:
                directory = os.path.join(home, ".agents", "skills", skill_name)
                os.makedirs(directory)
                with open(os.path.join(directory, "SKILL.md"), "w", encoding="utf-8") as file_obj:
                    file_obj.write("metadata:\n  managed-by: infra_tools\n")

            self.assertTrue(_t3_agent_skills_ready(home))
            os.unlink(
                os.path.join(
                    home,
                    ".agents",
                    "skills",
                    T3_AGENT_SKILL_NAMES[0],
                    "SKILL.md",
                )
            )
            self.assertFalse(_t3_agent_skills_ready(home))


if __name__ == "__main__":
    unittest.main()
