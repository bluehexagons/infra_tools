"""Controller-side tests for the remote target-user rename workflow."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from lib import sysadmin_user


class TestSysadminUser(unittest.TestCase):
    def test_unit_start_is_detached_from_the_renamed_users_session(self):
        completed = subprocess.CompletedProcess([], 0, "", "")
        with (
            patch.object(sysadmin_user, "build_scp_command", return_value=["scp"]),
            patch.object(sysadmin_user.subprocess, "run", return_value=completed),
            patch.object(sysadmin_user, "_run_ssh", return_value=completed) as run_ssh,
        ):
            sysadmin_user._stage_unit(
                "host.example",
                "olduser",
                None,
                "0123456789abcdef",
            )

        remote_command = run_ssh.call_args.args[3]
        self.assertIn("systemctl enable --now --no-block", remote_command)

    def test_resume_unit_start_is_non_blocking(self):
        completed = subprocess.CompletedProcess([], 0, "", "")
        with patch.object(
            sysadmin_user,
            "_run_ssh",
            return_value=completed,
        ) as run_ssh:
            sysadmin_user._start_resume_unit(
                "host.example",
                "newuser",
                None,
                "0123456789abcdef",
            )

        remote_command = run_ssh.call_args.args[3]
        self.assertIn("systemctl enable --now --no-block", remote_command)

    def test_host_lock_serializes_operations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = f"{tmpdir}/host.json"
            with patch.object(sysadmin_user, "get_cache_path_for_host", return_value=cache_path):
                first = sysadmin_user._acquire_host_lock("host.example")
                try:
                    with self.assertRaisesRegex(RuntimeError, "already running"):
                        sysadmin_user._acquire_host_lock("host.example")
                finally:
                    sysadmin_user._release_host_lock(first)

    def test_invalid_destination_does_not_contact_target(self):
        with patch.object(sysadmin_user, "_resolve_credentials") as resolve:
            result = sysadmin_user.run_user_rename("host.example", "bad name")

        self.assertEqual(result, 1)
        resolve.assert_not_called()

    def test_success_updates_controller_cache_only_after_ssh_verification(self):
        config = SimpleNamespace(username="olduser", ssh_key=None)
        status = {
            "status": "success",
            "phase": "complete",
            "details": {
                "old_home": "/home/olduser",
                "old_username": "olduser",
                "username": "newuser",
                "home": "/home/newuser",
            },
        }
        with (
            patch.object(sysadmin_user, "_resolve_credentials", return_value=("root", None, config)),
            patch.object(sysadmin_user, "_acquire_host_lock", return_value=object()),
            patch.object(sysadmin_user, "_release_host_lock"),
            patch.object(sysadmin_user, "ensure_remote_sudo", return_value=True),
            patch.object(sysadmin_user, "_stage_manifest"),
            patch.object(sysadmin_user, "_preflight", return_value={
                "old_home": "/home/olduser",
                "new_home": "/home/newuser",
            }),
            patch.object(sysadmin_user, "_stage_unit"),
            patch.object(sysadmin_user, "_wait_for_completion", return_value=status),
            patch.object(sysadmin_user, "_verify_new_login", return_value=True),
            patch.object(sysadmin_user, "_read_status", return_value=status),
            patch.object(sysadmin_user, "rename_setup_command") as rename_cache,
        ):
            result = sysadmin_user.run_user_rename(
                "host.example",
                "newuser",
                assume_yes=True,
            )

        self.assertEqual(result, 0)
        rename_cache.assert_called_once_with(
            "host.example",
            old_username="olduser",
            new_username="newuser",
            old_home="/home/olduser",
            new_home="/home/newuser",
        )

    def test_preflight_failure_discards_staged_manifest(self):
        config = SimpleNamespace(username="olduser", ssh_key=None)
        with (
            patch.object(sysadmin_user, "_resolve_credentials", return_value=("root", None, config)),
            patch.object(sysadmin_user, "_acquire_host_lock", return_value=object()),
            patch.object(sysadmin_user, "_release_host_lock"),
            patch.object(sysadmin_user, "ensure_remote_sudo", return_value=True),
            patch.object(sysadmin_user, "_stage_manifest"),
            patch.object(sysadmin_user, "_preflight", side_effect=RuntimeError("blocked")),
            patch.object(sysadmin_user, "_discard_remote_operation") as discard,
        ):
            result = sysadmin_user.run_user_rename(
                "host.example",
                "newuser",
                assume_yes=True,
            )

        self.assertEqual(result, 1)
        discard.assert_called_once()

    def test_resume_uses_new_login_after_identity_cutover(self):
        operation_id = "0123456789abcdef"
        config = SimpleNamespace(username="olduser", ssh_key=None)
        failed_status = {"status": "failed", "phase": "identity-renamed"}
        success_status = {
            "status": "success",
            "phase": "complete",
            "details": {
                "old_home": "/home/olduser",
                "old_username": "olduser",
                "username": "newuser",
                "home": "/home/newuser",
            },
        }
        manifest = {
            "old_username": "olduser",
            "new_username": "newuser",
        }

        def read_status(_host, username, _key, _operation_id):
            return failed_status if username == "newuser" else None

        def read_manifest(_host, username, _key, _operation_id):
            return manifest if username == "newuser" else None

        with (
            patch.object(
                sysadmin_user,
                "_resolve_credentials",
                return_value=("olduser", None, config),
            ),
            patch.object(sysadmin_user, "_acquire_host_lock", return_value=object()),
            patch.object(sysadmin_user, "_release_host_lock"),
            patch.object(sysadmin_user, "ensure_remote_sudo") as ensure_sudo,
            patch.object(sysadmin_user, "_read_status", side_effect=read_status),
            patch.object(sysadmin_user, "_read_manifest", side_effect=read_manifest),
            patch.object(sysadmin_user, "_start_resume_unit") as start_resume,
            patch.object(
                sysadmin_user,
                "_wait_for_completion",
                return_value=success_status,
            ),
            patch.object(sysadmin_user, "_verify_new_login", return_value=True),
            patch.object(sysadmin_user, "rename_setup_command") as rename_cache,
        ):
            result = sysadmin_user.run_user_rename(
                "host.example",
                "newuser",
                resume=operation_id,
            )

        self.assertEqual(result, 0)
        ensure_sudo.assert_not_called()
        start_resume.assert_called_once_with(
            "host.example",
            "newuser",
            None,
            operation_id,
        )
        rename_cache.assert_called_once()

    def test_success_without_completion_paths_does_not_update_cache(self):
        config = SimpleNamespace(username="olduser", ssh_key=None)
        status = {
            "status": "success",
            "phase": "complete",
            "details": {
                "old_username": "olduser",
                "username": "newuser",
            },
        }
        with (
            patch.object(
                sysadmin_user,
                "_resolve_credentials",
                return_value=("root", None, config),
            ),
            patch.object(sysadmin_user, "_acquire_host_lock", return_value=object()),
            patch.object(sysadmin_user, "_release_host_lock"),
            patch.object(sysadmin_user, "ensure_remote_sudo", return_value=True),
            patch.object(sysadmin_user, "_stage_manifest"),
            patch.object(
                sysadmin_user,
                "_preflight",
                return_value={
                    "old_home": "/home/olduser",
                    "new_home": "/home/newuser",
                },
            ),
            patch.object(sysadmin_user, "_stage_unit"),
            patch.object(sysadmin_user, "_wait_for_completion", return_value=status),
            patch.object(sysadmin_user, "_verify_new_login", return_value=True),
            patch.object(sysadmin_user, "rename_setup_command") as rename_cache,
        ):
            result = sysadmin_user.run_user_rename(
                "host.example",
                "newuser",
                assume_yes=True,
            )

        self.assertEqual(result, 1)
        rename_cache.assert_not_called()


if __name__ == "__main__":
    unittest.main()
