"""Tests for workspace credential storage and runtime resolution."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.config import SetupConfig
from lib.credentials import (
    list_workspace_credentials,
    load_workspace_credentials,
    prepare_runtime_config,
    remove_workspace_credential,
    set_workspace_credential,
    store_cli_credentials,
)
from lib.workspace import get_credentials_path


class TestWorkspaceCredentials(unittest.TestCase):
    def test_set_list_and_remove_credentials(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            set_workspace_credential("alice", "secret1", tmpdir)
            set_workspace_credential("bob", "secret2", tmpdir)

            self.assertEqual(list_workspace_credentials(tmpdir), ["alice", "bob"])
            self.assertEqual(load_workspace_credentials(tmpdir), {"alice": "secret1", "bob": "secret2"})

            self.assertTrue(remove_workspace_credential("alice", tmpdir))
            self.assertFalse(remove_workspace_credential("missing", tmpdir))
            self.assertEqual(list_workspace_credentials(tmpdir), ["bob"])

    def test_load_workspace_credentials_fixes_permissions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            credentials_path = get_credentials_path(tmpdir)
            os.makedirs(tmpdir, exist_ok=True)
            with open(credentials_path, "w", encoding="utf-8") as file_obj:
                json.dump({"version": 1, "credentials": {"alice": {"password": "secret1"}}}, file_obj)
            os.chmod(credentials_path, 0o644)

            self.assertEqual(load_workspace_credentials(tmpdir), {"alice": "secret1"})
            self.assertEqual(os.stat(credentials_path).st_mode & 0o777, 0o600)

    def test_store_cli_credentials_saves_inline_passwords(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = SetupConfig(
                host="host",
                username="user",
                system_type="server_lite",
                share_credentials=[["guest", "secret1"]],
                samba_shares=[["read", "media", "/mnt/media", "shareuser:secret2"]],
                smb_mounts=[["/mnt/share", "1.2.3.4", "mountuser:secret3", "docs", "/"]],
            )

            store_cli_credentials(config, tmpdir)

            self.assertEqual(
                load_workspace_credentials(tmpdir),
                {"guest": "secret1", "mountuser": "secret3", "shareuser": "secret2"},
            )

    def test_prepare_runtime_config_resolves_workspace_credentials(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            set_workspace_credential("guest", "secret1", tmpdir)
            set_workspace_credential("mountuser", "secret2", tmpdir)
            config = SetupConfig(
                host="host",
                username="user",
                system_type="server_lite",
                samba_shares=[["read", "media", "/mnt/media", "guest"]],
                smb_mounts=[["/mnt/share", "1.2.3.4", "mountuser", "docs", "/"]],
            )

            runtime_config = prepare_runtime_config(config, tmpdir)

            self.assertIsNone(config.share_credentials)
            self.assertEqual(config.smb_mounts, [["/mnt/share", "1.2.3.4", "mountuser", "docs", "/"]])
            self.assertEqual(runtime_config.share_credentials, [["guest", "secret1"]])
            self.assertEqual(
                runtime_config.smb_mounts,
                [["/mnt/share", "1.2.3.4", "mountuser:secret2", "docs", "/"]],
            )

    def test_prepare_runtime_config_rejects_missing_mount_credentials(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = SetupConfig(
                host="host",
                username="user",
                system_type="server_lite",
                smb_mounts=[["/mnt/share", "1.2.3.4", "mountuser", "docs", "/"]],
            )

            with self.assertRaisesRegex(ValueError, "Missing credential for SMB mount user: mountuser"):
                prepare_runtime_config(config, tmpdir)


if __name__ == "__main__":
    unittest.main()
