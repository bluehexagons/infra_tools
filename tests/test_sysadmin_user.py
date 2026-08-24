"""Controller-side tests for the remote target-user rename workflow."""

from __future__ import annotations

import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from lib import sysadmin_user


class TestSysadminUser(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
