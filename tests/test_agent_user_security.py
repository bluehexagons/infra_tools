"""Tests for reversible Linux-account hardening on agent machines."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import call, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from common.agent_security_steps import configure_agent_user_security
from lib.config import SetupConfig


class TestAgentUserSecurity(unittest.TestCase):
    def _config(
        self,
        *,
        harden_agent: bool = False,
        harden_user: bool = False,
    ) -> SetupConfig:
        return SetupConfig(
            host="testhost",
            username="agent",
            system_type="agent_vm",
            machine_type="vm",
            harden_agent=harden_agent,
            harden_user=harden_user,
        )

    def _account(self, home: str) -> SimpleNamespace:
        return SimpleNamespace(
            pw_name="agent",
            pw_uid=os.getuid(),
            pw_gid=os.getgid(),
            pw_dir=home,
        )

    def test_refuses_symlinked_security_state_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = os.path.join(temporary, "home")
            real_state_dir = os.path.join(temporary, "real-state")
            state_dir = os.path.join(temporary, "state")
            os.mkdir(home)
            os.mkdir(real_state_dir)
            os.symlink(real_state_dir, state_dir)
            account = self._account(home)

            with patch(
                "common.agent_security_steps.AGENT_USER_SECURITY_STATE_DIR",
                state_dir,
            ), patch(
                "common.agent_security_steps.pwd.getpwnam",
                return_value=account,
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "Refusing unsafe agent user security state directory",
                ):
                    configure_agent_user_security(self._config())

    def test_harden_agent_removes_and_later_restores_privileged_groups(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = os.path.join(temporary, "home")
            state_dir = os.path.join(temporary, "state")
            os.mkdir(home)
            account = self._account(home)
            docker_gid = account.pw_gid + 1000
            current_group_ids = [account.pw_gid, docker_gid]

            def group_by_gid(group_id: int) -> SimpleNamespace:
                name = "agent" if group_id == account.pw_gid else "docker"
                return SimpleNamespace(gr_name=name)

            with patch(
                "common.agent_security_steps.AGENT_USER_SECURITY_STATE_DIR",
                state_dir,
            ), patch(
                "common.agent_security_steps.pwd.getpwnam",
                return_value=account,
            ), patch(
                "common.agent_security_steps.os.getgrouplist",
                side_effect=lambda _user, _gid: list(current_group_ids),
            ), patch(
                "common.agent_security_steps.grp.getgrgid",
                side_effect=group_by_gid,
            ), patch(
                "common.agent_security_steps.grp.getgrnam",
                return_value=SimpleNamespace(gr_name="docker"),
            ), patch(
                "common.agent_security_steps.os.chown"
            ), patch(
                "common.agent_security_steps.run"
            ) as mock_run:
                configure_agent_user_security(self._config(harden_agent=True))

                state_path = os.path.join(state_dir, f"{account.pw_uid}.json")
                with open(state_path, "r", encoding="utf-8") as file_obj:
                    state = json.load(file_obj)
                self.assertEqual(state["removed_groups"], ["docker"])
                mock_run.assert_any_call(
                    ["gpasswd", "--delete", "agent", "docker"]
                )

                mock_run.reset_mock()
                current_group_ids[:] = [account.pw_gid]
                configure_agent_user_security(self._config())

                mock_run.assert_called_once_with(
                    [
                        "usermod",
                        "--append",
                        "--groups",
                        "docker",
                        "agent",
                    ]
                )
                self.assertFalse(os.path.exists(state_path))

    def test_harden_user_locks_password_home_and_lingering_then_restores(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = os.path.join(temporary, "home")
            state_dir = os.path.join(temporary, "state")
            linger_dir = os.path.join(temporary, "linger")
            os.mkdir(home)
            os.chmod(home, 0o750)
            os.mkdir(linger_dir)
            linger_path = os.path.join(linger_dir, "agent")
            with open(linger_path, "w", encoding="utf-8"):
                pass
            account = self._account(home)
            password_statuses = iter(("P", "P", "L"))

            def run_command(
                command: list[str],
                **_kwargs: object,
            ) -> subprocess.CompletedProcess[str]:
                stdout = ""
                if command[:2] == ["passwd", "--status"]:
                    stdout = f"agent {next(password_statuses)} 2026-01-01 0 99999 7 -1\n"
                return subprocess.CompletedProcess(command, 0, stdout, "")

            with patch(
                "common.agent_security_steps.AGENT_USER_SECURITY_STATE_DIR",
                state_dir,
            ), patch(
                "common.agent_security_steps.SYSTEMD_LINGER_DIR",
                linger_dir,
            ), patch(
                "common.agent_security_steps.pwd.getpwnam",
                return_value=account,
            ), patch(
                "common.agent_security_steps.os.getgrouplist",
                return_value=[account.pw_gid],
            ), patch(
                "common.agent_security_steps.grp.getgrgid",
                return_value=SimpleNamespace(gr_name="agent"),
            ), patch(
                "common.agent_security_steps.can_manage_system_services",
                return_value=True,
            ), patch(
                "common.agent_security_steps.os.chown"
            ), patch(
                "common.agent_security_steps.run",
                side_effect=run_command,
            ) as mock_run:
                configure_agent_user_security(self._config(harden_user=True))

                self.assertEqual(stat.S_IMODE(os.stat(home).st_mode), 0o700)
                mock_run.assert_has_calls(
                    [
                        call(["usermod", "--lock", "agent"]),
                        call(["loginctl", "disable-linger", "agent"]),
                    ]
                )
                state_path = os.path.join(state_dir, f"{account.pw_uid}.json")
                with open(state_path, "r", encoding="utf-8") as file_obj:
                    state = json.load(file_obj)
                self.assertEqual(state["user_controls"]["home_mode"], 0o750)
                self.assertEqual(state["user_controls"]["password_status"], "P")
                self.assertTrue(state["user_controls"]["linger_enabled"])

                os.unlink(linger_path)
                mock_run.reset_mock()
                configure_agent_user_security(self._config())

                self.assertEqual(stat.S_IMODE(os.stat(home).st_mode), 0o750)
                mock_run.assert_has_calls(
                    [
                        call(["usermod", "--unlock", "agent"]),
                        call(["loginctl", "enable-linger", "agent"]),
                    ]
                )
                self.assertFalse(os.path.exists(state_path))


if __name__ == "__main__":
    unittest.main()
