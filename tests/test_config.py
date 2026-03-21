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

    def test_python_flag(self):
        config = self._make_config(install_python=True)
        args = config.to_remote_args()
        self.assertIn('--python', args)

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

    def test_share_credentials(self):
        config = self._make_config(share_credentials=[['user1', 'pass1']])
        args = config.to_remote_args()
        args_str = ' '.join(args)
        self.assertIn('--credential user1 pass1', args_str)

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

    def test_share_credentials_redacted_for_username_only_shares(self):
        config = self._make_config(
            share_credentials=[['user1', 'secret1']],
            samba_shares=[['read', 'share', '/mnt/data', 'user1']],
        )
        parts = config.to_setup_command()
        cmd = ' '.join(parts)
        self.assertIn('--credential user1 [REDACTED]', cmd)
        self.assertNotIn('secret1', cmd)

    def test_share_credentials_omitted_for_inline_share_passwords(self):
        config = self._make_config(
            share_credentials=[['user1', 'secret1']],
            samba_shares=[['read', 'share', '/mnt/data', 'user1:secret1']],
        )
        parts = config.to_setup_command()
        cmd = ' '.join(parts)
        self.assertNotIn('--credential user1 [REDACTED]', cmd)
        self.assertIn('user1:[REDACTED]', cmd)
        self.assertNotIn('secret1', cmd)

    def test_share_command_handles_incomplete_share_specs(self):
        config = self._make_config(
            samba_shares=[['read', 'share', '/mnt/data']],
        )
        parts = config.to_setup_command()
        cmd = ' '.join(parts)
        self.assertIn('--share read share /mnt/data', cmd)
        self.assertNotIn('[REDACTED]', cmd)

    def test_share_command_redacts_mixed_share_users(self):
        config = self._make_config(
            share_credentials=[['user1', 'secret1'], ['user2', 'secret2']],
            # Intentional whitespace, duplicates, and empty entries to exercise user list cleanup.
            samba_shares=[['read', 'share', '/mnt/data', ' user1 , , user2:secret2 ,user1,user3:secret3 ']],
        )
        parts = config.to_setup_command()
        cmd = ' '.join(parts)
        self.assertIn('--credential user1 [REDACTED]', cmd)
        self.assertEqual(cmd.count('--credential user1 [REDACTED]'), 1)
        self.assertIn('user1,user2:[REDACTED],user1,user3:[REDACTED]', cmd)
        self.assertNotIn('secret2', cmd)
        self.assertNotIn('secret3', cmd)

    def test_python_flag_included(self):
        config = self._make_config(install_python=True)
        parts = config.to_setup_command()
        self.assertIn('--python', parts)


class TestSetupConfigHostedFields(unittest.TestCase):
    def _make_config(self, **kwargs):
        defaults = dict(host='testhost', username='testuser', system_type='server_lite')
        defaults.update(kwargs)
        return SetupConfig(**defaults)

    def test_hosted_defaults(self):
        config = self._make_config()
        self.assertIsNone(config.hosted_node)
        self.assertEqual(config.hosted_user, 'root')
        self.assertIsNone(config.hosted_key)
        self.assertIsNone(config.container_memory)
        self.assertIsNone(config.container_storage)
        self.assertEqual(config.container_cores, 1)
        self.assertEqual(config.container_base, 'debian')

    def test_hosted_fields(self):
        config = self._make_config(
            hosted_node='10.0.0.1',
            hosted_user='admin',
            hosted_key='/path/to/key',
            container_memory='2G',
            container_storage=['root', 'auto', '10G'],
            container_cores=4,
            container_base='ubuntu',
        )
        self.assertEqual(config.hosted_node, '10.0.0.1')
        self.assertEqual(config.hosted_user, 'admin')
        self.assertEqual(config.hosted_key, '/path/to/key')
        self.assertEqual(config.container_memory, '2G')
        self.assertEqual(config.container_storage, ['root', 'auto', '10G'])
        self.assertEqual(config.container_cores, 4)
        self.assertEqual(config.container_base, 'ubuntu')

    def test_to_dict_includes_hosted_fields(self):
        config = self._make_config(
            hosted_node='10.0.0.1',
            container_memory='2G',
            container_storage=['root', 'auto', '10G'],
        )
        d = config.to_dict()
        self.assertEqual(d['hosted_node'], '10.0.0.1')
        self.assertEqual(d['container_memory'], '2G')
        self.assertEqual(d['container_storage'], ['root', 'auto', '10G'])

    def test_from_dict_restores_hosted_fields(self):
        data = {
            'username': 'testuser',
            'hosted_node': '10.0.0.1',
            'container_memory': '4G',
            'container_storage': ['template', 'local', '5G'],
            'container_cores': 8,
            'container_base': 'fedora',
        }
        config = SetupConfig.from_dict('target', 'server_web', data)
        self.assertEqual(config.hosted_node, '10.0.0.1')
        self.assertEqual(config.container_memory, '4G')
        self.assertEqual(config.container_storage, ['template', 'local', '5G'])
        self.assertEqual(config.container_cores, 8)
        self.assertEqual(config.container_base, 'fedora')

    def test_hosted_fields_not_in_remote_args(self):
        config = self._make_config(
            hosted_node='10.0.0.1',
            container_memory='2G',
            container_storage=['root', 'auto', '10G'],
        )
        args_str = ' '.join(config.to_remote_args())
        self.assertNotIn('--hosted', args_str)
        self.assertNotIn('--memory', args_str)
        self.assertNotIn('--storage', args_str)
        self.assertNotIn('--cores', args_str)

    def test_hosted_fields_not_in_setup_command(self):
        config = self._make_config(
            hosted_node='10.0.0.1',
            container_memory='2G',
            container_storage=['root', 'auto', '10G'],
        )
        parts = config.to_setup_command()
        cmd = ' '.join(parts)
        self.assertNotIn('--hosted', cmd)
        self.assertNotIn('--memory', cmd)
        self.assertNotIn('--storage', cmd)


if __name__ == '__main__':
    unittest.main()
