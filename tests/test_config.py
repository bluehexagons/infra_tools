"""Tests for lib/config.py: SetupConfig serialization, to_remote_args, to_dict, from_dict."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.config import SetupConfig, DEFAULT_MACHINE_TYPE


class TestSetupConfigDefaults(unittest.TestCase):
    def _make_config(self, **kwargs):
        defaults = dict(host='testhost', username='testuser', system_type='server_lite')
        defaults.update(kwargs)
        return SetupConfig(**defaults)

    def test_default_values(self):
        config = self._make_config()
        self.assertEqual(config.machine_type, DEFAULT_MACHINE_TYPE)
        self.assertEqual(config.timezone, 'UTC')
        self.assertFalse(config.enable_rdp)
        self.assertFalse(config.dry_run)
        self.assertEqual(config.desktop, 'xfce')

    def test_custom_values(self):
        config = self._make_config(timezone='America/New_York', enable_rdp=True, dry_run=True)
        self.assertEqual(config.timezone, 'America/New_York')
        self.assertTrue(config.enable_rdp)
        self.assertTrue(config.dry_run)


class TestSetupConfigToDict(unittest.TestCase):
    def _make_config(self, **kwargs):
        defaults = dict(host='testhost', username='testuser', system_type='server_lite')
        defaults.update(kwargs)
        return SetupConfig(**defaults)

    def test_to_dict_excludes_host_and_system_type(self):
        config = self._make_config()
        d = config.to_dict()
        self.assertNotIn('host', d)
        self.assertNotIn('system_type', d)

    def test_to_dict_includes_username(self):
        config = self._make_config()
        d = config.to_dict()
        self.assertEqual(d['username'], 'testuser')

    def test_to_dict_tags_joined(self):
        config = self._make_config(tags=['web', 'prod'])
        d = config.to_dict()
        self.assertEqual(d['tags'], 'web,prod')


class TestSetupConfigFromDict(unittest.TestCase):
    def test_from_dict_basic(self):
        data = {'username': 'testuser', 'timezone': 'UTC'}
        config = SetupConfig.from_dict('host1', 'server_lite', data)
        self.assertEqual(config.host, 'host1')
        self.assertEqual(config.system_type, 'server_lite')
        self.assertEqual(config.username, 'testuser')

    def test_from_dict_tags_string(self):
        data = {'username': 'u', 'tags': 'web,prod'}
        config = SetupConfig.from_dict('h', 'server_lite', data)
        self.assertEqual(config.tags, ['web', 'prod'])

    def test_from_dict_tags_empty(self):
        data = {'username': 'u', 'tags': ''}
        config = SetupConfig.from_dict('h', 'server_lite', data)
        self.assertIsNone(config.tags)

    def test_from_dict_friendly_name_missing(self):
        data = {'username': 'u'}
        config = SetupConfig.from_dict('h', 'server_lite', data)
        self.assertIsNone(config.friendly_name)


class TestSetupConfigToRemoteArgs(unittest.TestCase):
    def _make_config(self, **kwargs):
        defaults = dict(host='testhost', username='testuser', system_type='server_lite')
        defaults.update(kwargs)
        return SetupConfig(**defaults)

    def test_basic_args(self):
        config = self._make_config()
        args = config.to_remote_args()
        args_str = ' '.join(args)
        self.assertIn('--system-type', args_str)
        self.assertIn('--username', args_str)
        self.assertIn('--machine', args_str)

    def test_rdp_flag(self):
        config = self._make_config(enable_rdp=True)
        args = config.to_remote_args()
        self.assertIn('--rdp', args)

    def test_browser_single(self):
        config = self._make_config(browser='firefox', browsers=None)
        args = config.to_remote_args()
        args_str = ' '.join(args)
        self.assertIn('--browser firefox', args_str)

    def test_browsers_list(self):
        config = self._make_config(browsers=['firefox', 'brave'])
        args = config.to_remote_args()
        args_str = ' '.join(args)
        self.assertEqual(args_str.count('--browser'), 2)

    def test_dry_run_flag(self):
        config = self._make_config(dry_run=True)
        args = config.to_remote_args()
        self.assertIn('--dry-run', args)

    def test_deploy_specs(self):
        config = self._make_config(deploy_specs=[['example.com/', 'https://github.com/user/repo.git']])
        args = config.to_remote_args()
        args_str = ' '.join(args)
        self.assertIn('--lite-deploy', args_str)
        self.assertIn('--deploy', args_str)

    def test_sync_specs(self):
        config = self._make_config(sync_specs=[['/src', '/dst', 'daily']])
        args = config.to_remote_args()
        args_str = ' '.join(args)
        self.assertIn('--sync', args_str)

    def test_scrub_specs(self):
        config = self._make_config(scrub_specs=[['/data', '/db', '5%', 'weekly']])
        args = config.to_remote_args()
        args_str = ' '.join(args)
        self.assertIn('--scrub', args_str)

    def test_samba_shares(self):
        config = self._make_config(enable_samba=True, samba_shares=[['read', 'share', '/mnt/data', 'u:p']])
        args = config.to_remote_args()
        args_str = ' '.join(args)
        self.assertIn('--samba', args_str)
        self.assertIn('--share', args_str)

    def test_smb_mounts(self):
        config = self._make_config(enable_smbclient=True, smb_mounts=[['/mnt/share', '1.2.3.4', 'u:p', 'share', '/']])
        args = config.to_remote_args()
        args_str = ' '.join(args)
        self.assertIn('--smbclient', args_str)
        self.assertIn('--mount-smb', args_str)

    def test_notify_specs(self):
        config = self._make_config(notify_specs=[['webhook', 'https://example.com/hook']])
        args = config.to_remote_args()
        args_str = ' '.join(args)
        self.assertIn('--notify', args_str)

    def test_friendly_name_included(self):
        config = self._make_config(friendly_name='scrapbox')
        args = config.to_remote_args()
        args_str = ' '.join(args)
        self.assertIn('--name scrapbox', args_str)

    def test_friendly_name_none_omitted(self):
        config = self._make_config(friendly_name=None)
        args = config.to_remote_args()
        args_str = ' '.join(args)
        self.assertNotIn('--name', args_str)


class TestSetupConfigToSetupCommand(unittest.TestCase):
    def _make_config(self, **kwargs):
        defaults = dict(host='testhost', username='testuser', system_type='server_lite')
        defaults.update(kwargs)
        return SetupConfig(**defaults)

    def test_basic_command(self):
        config = self._make_config()
        parts = config.to_setup_command()
        self.assertIn('python3 setup_server_lite.py', parts[0])
        self.assertIn('testhost', parts)

    def test_includes_username(self):
        config = self._make_config()
        parts = config.to_setup_command(include_username=True)
        self.assertIn('testuser', parts)

    def test_excludes_username(self):
        config = self._make_config()
        parts = config.to_setup_command(include_username=False)
        self.assertNotIn('testuser', parts)

    def test_ssh_key(self):
        config = self._make_config(ssh_key='/path/to/key')
        parts = config.to_setup_command()
        self.assertTrue(any('-k' in p for p in parts))

    def test_non_default_timezone(self):
        config = self._make_config(timezone='America/New_York')
        parts = config.to_setup_command()
        self.assertTrue(any('-t' in p for p in parts))

    def test_default_timezone_omitted(self):
        config = self._make_config(timezone='UTC')
        parts = config.to_setup_command()
        self.assertFalse(any('-t' in p for p in parts))

    def test_non_default_machine_type(self):
        config = self._make_config(machine_type='hardware')
        parts = config.to_setup_command()
        self.assertTrue(any('--machine' in p for p in parts))

    def test_password_not_included(self):
        config = self._make_config(password='secret')
        parts = config.to_setup_command()
        cmd = ' '.join(parts)
        self.assertNotIn('secret', cmd)


if __name__ == '__main__':
    unittest.main()
