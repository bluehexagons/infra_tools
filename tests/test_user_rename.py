"""Focused tests for the target-side user migration helper."""

from __future__ import annotations

import json
import os
import pwd
import tempfile
import unittest
from unittest.mock import patch

from lib import user_rename


class TestUserRenameHelpers(unittest.TestCase):
    def test_rewrite_setup_config_updates_username_and_home_paths(self):
        config = {
            "username": "olduser",
            "agent_workspace": "/home/olduser/repos",
            "sync_specs": [["/home/olduser/data", "/srv/backup", "daily"]],
            "share_credentials": [["olduser", "secret"]],
            "notify_specs": [["webhook", "/home/olduser/should-not-change"]],
            "gogs": ["git.example.com:3000", "/home/olduser/gogs"],
        }

        updated = user_rename._rewrite_setup_config(
            config,
            "olduser",
            "newuser",
            "/home/olduser",
            "/home/newuser",
        )

        self.assertEqual(updated["username"], "newuser")
        self.assertEqual(updated["agent_workspace"], "/home/newuser/repos")
        self.assertEqual(updated["sync_specs"][0][0], "/home/newuser/data")
        self.assertEqual(updated["share_credentials"][0][0], "olduser")
        self.assertEqual(updated["notify_specs"][0][1], "/home/olduser/should-not-change")
        self.assertEqual(updated["gogs"][1], "/home/newuser/gogs")

    def test_managed_unit_detection_rejects_unknown_references(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            managed = os.path.join(tmpdir, "auto-update-node.service")
            unmanaged = os.path.join(tmpdir, "custom.service")
            with open(managed, "w", encoding="utf-8") as file_obj:
                file_obj.write("User=olduser\n")
            with open(unmanaged, "w", encoding="utf-8") as file_obj:
                file_obj.write("User=olduser\n")
            with patch.object(user_rename, "SYSTEMD_DIR", tmpdir):
                managed_paths, unmanaged_paths = user_rename._managed_unit_files(
                    "olduser",
                    "/home/olduser",
                )

        self.assertEqual(managed_paths, [managed])
        self.assertEqual(unmanaged_paths, [unmanaged])

    def test_managed_unit_rewrite_protects_old_username_in_new_home(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            unit_path = os.path.join(tmpdir, "auto-update-node.service")
            with open(unit_path, "w", encoding="utf-8") as file_obj:
                file_obj.write("WorkingDirectory=/srv/olduser-data\nUser=olduser\n")
            manifest = {
                "old_username": "olduser",
                "new_username": "newuser",
                "new_home": "/srv/olduser-data",
                "managed_units": [{"path": unit_path}],
            }

            user_rename._rewrite_managed_units(
                manifest,
                "/home/olduser",
                "/srv/olduser-data",
            )
            with open(unit_path, encoding="utf-8") as file_obj:
                content = file_obj.read()
            user_rename._verify_managed_rewrites(manifest, "/home/olduser")

        self.assertIn("WorkingDirectory=/srv/olduser-data", content)
        self.assertIn("User=newuser", content)

    def test_preflight_rejects_root(self):
        account = pwd.struct_passwd(
            ("root", "x", 0, 0, "root", "/root", "/bin/bash")
        )
        with patch.object(user_rename, "_account", return_value=account):
            with self.assertRaisesRegex(user_rename.RenameError, "root"):
                user_rename._preflight(
                    {
                        "operation_id": "0123456789abcdef",
                        "old_username": "root",
                        "new_username": "newuser",
                    }
                )

    def test_status_is_atomic_and_non_secret(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(user_rename, "RENAME_ROOT", tmpdir):
                user_rename._write_status(
                    "0123456789abcdef",
                    "prepared",
                    "in_progress",
                    details={"old_home": "/home/olduser"},
                )
                status_path = os.path.join(
                    tmpdir,
                    "0123456789abcdef",
                    "status.json",
                )
                with open(status_path, encoding="utf-8") as file_obj:
                    status = json.load(file_obj)

        self.assertEqual(status["phase"], "prepared")
        self.assertNotIn("password", status)

    def test_linger_marker_moves_and_resume_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(user_rename, "LINGER_DIR", tmpdir):
                open(os.path.join(tmpdir, "olduser"), "w", encoding="utf-8").close()
                user_rename._rename_linger("olduser", "newuser", True)
                user_rename._rename_linger("olduser", "newuser", True)
                self.assertTrue(os.path.isfile(os.path.join(tmpdir, "newuser")))
                self.assertFalse(os.path.exists(os.path.join(tmpdir, "olduser")))

    def test_concurrent_operation_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            operation_id = "0123456789abcdef"
            other_id = "fedcba9876543210"
            other_dir = os.path.join(tmpdir, other_id)
            os.makedirs(other_dir)
            with open(os.path.join(other_dir, "status.json"), "w", encoding="utf-8") as file_obj:
                json.dump({"status": "in_progress"}, file_obj)
            with patch.object(user_rename, "RENAME_ROOT", tmpdir):
                with self.assertRaisesRegex(user_rename.RenameError, "unfinished"):
                    user_rename._reject_concurrent_operation(operation_id)

    def test_target_lock_serializes_jobs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(user_rename, "RENAME_ROOT", tmpdir):
                first = user_rename._acquire_target_lock()
                try:
                    with self.assertRaisesRegex(user_rename.RenameError, "already running"):
                        user_rename._acquire_target_lock()
                finally:
                    user_rename._release_target_lock(first)


if __name__ == "__main__":
    unittest.main()
