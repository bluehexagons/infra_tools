"""Regression tests for SMB client mount hardening defaults."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.config import SetupConfig
from smb import smb_mount_steps


class TestConfigureSmbMountUnit(unittest.TestCase):
    def test_unit_pins_smb3_and_uses_safe_file_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            etc_systemd = os.path.join(tmp, 'etc-systemd')
            creds_dir = os.path.join(tmp, 'creds')
            mountpoint = os.path.join(tmp, 'mnt-share')
            os.makedirs(etc_systemd)
            os.makedirs(creds_dir)

            real_open = open
            real_makedirs = os.makedirs

            def fake_open(path, mode='r', *args, **kwargs):
                if path.startswith('/etc/systemd/system/'):
                    target = os.path.join(etc_systemd, os.path.basename(path))
                    return real_open(target, mode, *args, **kwargs)
                if path.startswith('/root/.smb/'):
                    target = os.path.join(creds_dir, os.path.basename(path))
                    return real_open(target, mode, *args, **kwargs)
                return real_open(path, mode, *args, **kwargs)

            def fake_makedirs(path, *args, **kwargs):
                # Redirect privileged paths into the temp tree; let other
                # paths fall through to the real implementation so the
                # configured mountpoint actually exists.
                if path == '/root/.smb':
                    return real_makedirs(creds_dir, exist_ok=True)
                return real_makedirs(path, *args, **kwargs)

            def fake_run(cmd, **kwargs):
                res = MagicMock()
                res.returncode = 0
                if 'systemd-escape' in cmd:
                    escaped = mountpoint.lstrip('/').replace('/', '-')
                    res.stdout = escaped + '\n'
                else:
                    res.stdout = ''
                return res

            config = SetupConfig(host='h', username='alice', system_type='server_lite')

            with patch.object(smb_mount_steps, 'run', side_effect=fake_run), \
                 patch.object(smb_mount_steps, 'open', side_effect=fake_open, create=True), \
                 patch.object(smb_mount_steps, 'cleanup_systemd_unit'), \
                 patch.object(smb_mount_steps, 'validate_smb_mount_specs'), \
                 patch.object(smb_mount_steps.os, 'makedirs', side_effect=fake_makedirs):
                smb_mount_steps.configure_smb_mount(
                    config,
                    mount_spec=[mountpoint, '192.168.1.10', 'svc:hunter2', 'docs', '/sub'],
                )

            unit_files = os.listdir(etc_systemd)
            self.assertEqual(len(unit_files), 1, f"unexpected units: {unit_files}")
            with real_open(os.path.join(etc_systemd, unit_files[0])) as f:
                unit_body = f.read()

            cred_files = os.listdir(creds_dir)
            self.assertEqual(len(cred_files), 1, f"unexpected creds: {cred_files}")
            with real_open(os.path.join(creds_dir, cred_files[0])) as f:
                cred_body = f.read()

        # Pinned to SMB3+ minimum and request encryption-on-the-wire.
        self.assertIn("vers=3.0", unit_body)
        self.assertIn("seal", unit_body)
        # Files should not be world-executable by default.
        self.assertIn("file_mode=0644", unit_body)
        self.assertIn("dir_mode=0755", unit_body)
        # Defensive defaults for boot-time behaviour are preserved.
        self.assertIn("nofail", unit_body)
        self.assertIn("x-systemd.automount", unit_body)
        # Credentials still contain the username/password lines.
        self.assertIn("username=svc", cred_body)
        self.assertIn("password=hunter2", cred_body)

    def test_distinct_mountpoints_use_distinct_credential_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            etc_systemd = os.path.join(tmp, "etc-systemd")
            creds_dir = os.path.join(tmp, "creds")
            first_mountpoint = os.path.join(tmp, "a_b")
            second_mountpoint = os.path.join(tmp, "a", "b")
            os.makedirs(etc_systemd)
            os.makedirs(creds_dir)

            real_open = open
            real_makedirs = os.makedirs
            escaped_names = iter(("tmp-a_5fb", "tmp-a-b"))

            def fake_open(path, mode="r", *args, **kwargs):
                if path.startswith("/etc/systemd/system/"):
                    return real_open(os.path.join(etc_systemd, os.path.basename(path)), mode, *args, **kwargs)
                if path.startswith("/root/.smb/"):
                    return real_open(os.path.join(creds_dir, os.path.basename(path)), mode, *args, **kwargs)
                return real_open(path, mode, *args, **kwargs)

            def fake_makedirs(path, *args, **kwargs):
                if path == "/root/.smb":
                    return real_makedirs(creds_dir, exist_ok=True)
                return real_makedirs(path, *args, **kwargs)

            def fake_run(command, **_kwargs):
                result = MagicMock(returncode=0, stdout="")
                if "systemd-escape" in command:
                    result.stdout = next(escaped_names) + "\n"
                return result

            config = SetupConfig(host="h", username="alice", system_type="server_lite")
            with patch.object(smb_mount_steps, "run", side_effect=fake_run), \
                 patch.object(smb_mount_steps, "open", side_effect=fake_open, create=True), \
                 patch.object(smb_mount_steps, "cleanup_systemd_unit"), \
                 patch.object(smb_mount_steps, "validate_smb_mount_specs"), \
                 patch.object(smb_mount_steps.os, "makedirs", side_effect=fake_makedirs):
                smb_mount_steps.configure_smb_mount(
                    config,
                    mount_spec=[first_mountpoint, "192.168.1.10", "first:one", "docs", "/"],
                )
                smb_mount_steps.configure_smb_mount(
                    config,
                    mount_spec=[second_mountpoint, "192.168.1.11", "second:two", "docs", "/"],
                )

            credential_files = sorted(os.listdir(creds_dir))
            self.assertEqual(
                credential_files,
                ["credentials-tmp-a-b", "credentials-tmp-a_5fb"],
            )

            with real_open(os.path.join(creds_dir, "credentials-tmp-a_5fb")) as file_obj:
                self.assertIn("username=first", file_obj.read())
            with real_open(os.path.join(creds_dir, "credentials-tmp-a-b")) as file_obj:
                self.assertIn("username=second", file_obj.read())

    def test_invalid_spec_is_rejected_before_filesystem_changes(self) -> None:
        config = SetupConfig(host="h", username="alice", system_type="server_lite")

        with patch.object(smb_mount_steps.os, "makedirs") as mock_makedirs, \
             patch.object(smb_mount_steps, "run") as mock_run:
            with self.assertRaisesRegex(ValueError, "control characters"):
                smb_mount_steps.configure_smb_mount(
                    config,
                    mount_spec=["/mnt/share", "192.168.1.10", "svc:secret\nvalue", "docs", "/"],
                )

        mock_makedirs.assert_not_called()
        mock_run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
