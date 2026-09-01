"""Tests for the managed Codex session security policy."""

from __future__ import annotations

import os
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from common.agent_security_steps import configure_codex_security_policy
from lib.config import SetupConfig
from plugins.common import extend_agent_steps, get_custom_step_functions


class TestCodexSecurityPolicy(unittest.TestCase):
    def _config(self, *, hardened: bool = False) -> SetupConfig:
        return SetupConfig(
            host="testhost",
            username="agent",
            system_type="agent_vm",
            machine_type="vm",
            install_codex=True,
            harden_agent=hardened,
        )

    def _configure(self, directory: str, *, hardened: bool = False) -> None:
        with patch(
            "common.agent_security_steps.CODEX_SYSTEM_CONFIG_DIR", directory
        ), patch("common.agent_security_steps.os.chown"):
            configure_codex_security_policy(self._config(hardened=hardened))

    def test_standard_policy_uses_auto_review_and_workspace_permissions(self):
        with tempfile.TemporaryDirectory() as temporary:
            policy_dir = os.path.join(temporary, "codex")
            self._configure(policy_dir)

            with open(
                os.path.join(policy_dir, "config.toml"), "rb"
            ) as file_obj:
                config = tomllib.load(file_obj)
            requirements_path = os.path.join(policy_dir, "requirements.toml")
            self.assertFalse(os.path.exists(requirements_path))

        self.assertEqual(config["approval_policy"], "on-request")
        self.assertEqual(config["approvals_reviewer"], "auto_review")
        self.assertEqual(config["default_permissions"], ":workspace")
        self.assertFalse(config["sandbox_workspace_write"]["network_access"])

    def test_hardened_policy_disables_approval_escalation_and_active_tools(self):
        with tempfile.TemporaryDirectory() as temporary:
            policy_dir = os.path.join(temporary, "codex")
            self._configure(policy_dir, hardened=True)

            with open(
                os.path.join(policy_dir, "config.toml"), "rb"
            ) as file_obj:
                config = tomllib.load(file_obj)
            with open(
                os.path.join(policy_dir, "requirements.toml"), "rb"
            ) as file_obj:
                requirements = tomllib.load(file_obj)

        self.assertEqual(config["approval_policy"], "never")
        self.assertFalse(config["allow_login_shell"])
        self.assertEqual(requirements["allowed_approval_policies"], ["never"])
        self.assertTrue(requirements["allow_managed_hooks_only"])
        self.assertFalse(requirements["allow_browser_and_computer_use"])
        self.assertFalse(requirements["allow_remote_control"])

    def test_rerun_can_switch_an_infra_tools_owned_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            policy_dir = os.path.join(temporary, "codex")
            self._configure(policy_dir)
            self._configure(policy_dir, hardened=True)
            with open(
                os.path.join(policy_dir, "requirements.toml"), "rb"
            ) as file_obj:
                requirements = tomllib.load(file_obj)

        self.assertEqual(requirements["allowed_approval_policies"], ["never"])

    def test_returning_to_standard_removes_managed_requirements(self):
        with tempfile.TemporaryDirectory() as temporary:
            policy_dir = os.path.join(temporary, "codex")
            self._configure(policy_dir, hardened=True)
            self._configure(policy_dir)

            with open(
                os.path.join(policy_dir, "config.toml"), "rb"
            ) as file_obj:
                config = tomllib.load(file_obj)

            self.assertFalse(
                os.path.exists(os.path.join(policy_dir, "requirements.toml"))
            )

        self.assertEqual(config["approval_policy"], "on-request")

    def test_standard_preserves_unmanaged_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            policy_dir = os.path.join(temporary, "codex")
            os.makedirs(policy_dir)
            with open(
                os.path.join(policy_dir, "config.toml"), "w", encoding="utf-8"
            ) as file_obj:
                file_obj.write('approval_policy = "never"\n')

            self._configure(policy_dir)

            with open(
                os.path.join(policy_dir, "config.toml"),
                "r",
                encoding="utf-8",
            ) as file_obj:
                existing = file_obj.read()

        self.assertEqual(existing, 'approval_policy = "never"\n')

    def test_standard_preserves_unmanaged_requirements(self):
        with tempfile.TemporaryDirectory() as temporary:
            policy_dir = os.path.join(temporary, "codex")
            os.makedirs(policy_dir)
            requirements_path = os.path.join(policy_dir, "requirements.toml")
            with open(requirements_path, "w", encoding="utf-8") as file_obj:
                file_obj.write('allowed_approval_policies = ["never"]\n')

            self._configure(policy_dir)

            with open(requirements_path, "r", encoding="utf-8") as file_obj:
                existing = file_obj.read()

        self.assertEqual(existing, 'allowed_approval_policies = ["never"]\n')

    def test_hardened_refuses_to_replace_unmanaged_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            policy_dir = os.path.join(temporary, "codex")
            os.makedirs(policy_dir)
            with open(
                os.path.join(policy_dir, "config.toml"), "w", encoding="utf-8"
            ) as file_obj:
                file_obj.write('approval_policy = "never"\n')

            with self.assertRaisesRegex(
                RuntimeError, "Refusing to replace unmanaged Codex policy"
            ):
                self._configure(policy_dir, hardened=True)

    def test_preflights_both_policy_files_before_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            policy_dir = os.path.join(temporary, "codex")
            os.makedirs(policy_dir)
            with open(
                os.path.join(policy_dir, "requirements.toml"),
                "w",
                encoding="utf-8",
            ) as file_obj:
                file_obj.write('allowed_approval_policies = ["never"]\n')

            with self.assertRaisesRegex(
                RuntimeError, "Refusing to replace unmanaged Codex policy"
            ):
                self._configure(policy_dir, hardened=True)

            self.assertFalse(
                os.path.exists(os.path.join(policy_dir, "config.toml"))
            )

    def test_refuses_symlinked_policy_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            real_dir = os.path.join(temporary, "real")
            policy_dir = os.path.join(temporary, "codex")
            os.makedirs(real_dir)
            os.symlink(real_dir, policy_dir)

            with self.assertRaisesRegex(
                RuntimeError, "Refusing unsafe Codex policy directory"
            ):
                self._configure(policy_dir)


class TestCodexSecurityPolicySteps(unittest.TestCase):
    def test_policy_is_exported_as_a_custom_step(self):
        self.assertIs(
            get_custom_step_functions()["configure_codex_security_policy"],
            configure_codex_security_policy,
        )

    def test_policy_runs_before_t3_code_starts(self):
        config = SetupConfig(
            host="testhost",
            username="agent",
            system_type="agent_vm",
            machine_type="vm",
            install_codex=True,
            web_interfaces=["t3code"],
        )
        steps = []

        extend_agent_steps(config, steps)

        labels = [label for label, _step in steps]
        self.assertLess(
            labels.index("Configuring Codex security policy"),
            labels.index("Installing T3 Code web interface"),
        )


if __name__ == "__main__":
    unittest.main()
