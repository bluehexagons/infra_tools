"""Tests for lib/config.py: SetupConfig serialization, to_remote_args, to_dict, from_dict."""

from __future__ import annotations

import os
import sys
import unittest
from argparse import Namespace

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

    def test_to_dict_excludes_share_credentials(self):
        config = self._make_config(share_credentials=[['user1', 'secret1']])
        d = config.to_dict()
        self.assertNotIn('share_credentials', d)

    def test_to_dict_redacts_inline_share_passwords(self):
        config = self._make_config(samba_shares=[['read', 'share', '/mnt/data', 'user1:secret1,user2']])
        d = config.to_dict()
        self.assertEqual(d['samba_shares'], [['read', 'share', '/mnt/data', 'user1,user2']])

    def test_to_dict_redacts_inline_smb_mount_passwords(self):
        config = self._make_config(smb_mounts=[['/mnt/share', '1.2.3.4', 'user1:secret1', 'docs', '/']])
        d = config.to_dict()
        self.assertEqual(d['smb_mounts'], [['/mnt/share', '1.2.3.4', 'user1', 'docs', '/']])


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
        # Default deployment mode doesn't add a flag; lite and full modes use --deployment-lite/--deployment-full
        self.assertIn('--deploy', args_str)

    def test_deployment_mode_flags(self):
        deploy_specs = [['example.com/', 'https://github.com/user/repo.git']]

        lite = self._make_config(deploy_specs=deploy_specs, deployment_mode='lite')
        self.assertIn('--deployment-lite', lite.to_remote_args())
        self.assertIn('--deployment-lite', lite.to_setup_command())

        full = self._make_config(deploy_specs=deploy_specs, deployment_mode='full')
        self.assertTrue(full.full_deploy)
        self.assertIn('--deployment-full', full.to_remote_args())
        self.assertIn('--deployment-full', full.to_setup_command())

    def test_deploy_latest(self):
        config = self._make_config(deploy_latest=True)
        args = config.to_remote_args()
        self.assertIn('--deploy-latest', args)
        args = config.to_setup_command()
        self.assertIn('--deploy-latest', args)
        self.assertNotIn('deploy_latest', config.to_dict())

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

    def test_antistatic_db(self):
        config = self._make_config(antistatic_db='db.example.com:8081')
        args = config.to_remote_args()
        args_str = ' '.join(args)
        self.assertIn('--antistatic-db db.example.com:8081', args_str)

    def test_gogs(self):
        config = self._make_config(gogs=['git.example.com:3000', '/srv/gogs'])
        args = config.to_remote_args()
        args_str = ' '.join(args)
        self.assertIn('--gogs git.example.com:3000 /srv/gogs', args_str)

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
        self.assertIn('python3 infra_tools.py setup server_lite', parts[0])
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

    def test_lxc_machine_type_included_when_system_default_is_vm(self):
        config = self._make_config(system_type='server_web', machine_type='unprivileged')
        parts = config.to_setup_command()
        self.assertIn('--machine unprivileged', parts)

    def test_vm_machine_type_omitted_when_system_default_is_vm(self):
        config = self._make_config(system_type='server_web', machine_type='vm')
        parts = config.to_setup_command()
        self.assertFalse(any('--machine' in p for p in parts))

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

    def test_smb_mount_password_redacted(self):
        config = self._make_config(
            smb_mounts=[['/mnt/share', '1.2.3.4', 'user1:secret1', 'docs', '/']]
        )
        parts = config.to_setup_command()
        cmd = ' '.join(parts)
        self.assertIn('user1:[REDACTED]', cmd)
        self.assertNotIn('secret1', cmd)


class TestSetupConfigFromArgs(unittest.TestCase):
    def _make_args(self, **overrides):
        defaults = dict(
            host='testhost',
            username='testuser',
            timezone='UTC',
            tags=None,
            desktop=None,
            browsers=None,
            browser=None,
            install_office=None,
            enable_rdp=None,
            smb_mounts=None,
            enable_smbclient=None,
            auto_restart=None,
            auto_restart_force_days=None,
            auto_restart_grace=None,
            machine_type=None,
            password=None,
            ssh_key=None,
            friendly_name=None,
            use_flatpak=False,
            apt_packages=None,
            flatpak_packages=None,
            dark_theme=False,
            dry_run=False,
            install_ruby=False,
            install_go=False,
            install_node=False,
            install_python=False,
            custom_steps=None,
            deploy_specs=None,
            full_deploy=False,
            reset_migrations=False,
            enable_ssl=False,
            ssl_email=None,
            enable_cloudflare=False,
            enable_cicd=False,
            is_build_server=False,
            is_app_server=False,
            deploy_targets=None,
            api_subdomain=False,
            enable_samba=False,
            samba_shares=None,
            share_credentials=None,
            sync_specs=None,
            scrub_specs=None,
            notify_specs=None,
            antistatic_server=None,
            antistatic_db=None,
            gogs=None,
            hosted_node=None,
            hosted_user='root',
            hosted_key=None,
            container_memory=None,
            container_storage=None,
            container_cores=1,
            container_base='debian',
        )
        defaults.update(overrides)
        return Namespace(**defaults)

    def test_workstation_defaults_come_from_registry(self):
        config = SetupConfig.from_args(self._make_args(), 'workstation_desktop')
        self.assertEqual(config.machine_type, 'vm')
        self.assertFalse(config.enable_rdp)
        self.assertTrue(config.include_desktop)
        self.assertTrue(config.include_cli_tools)
        self.assertTrue(config.include_desktop_apps)
        self.assertEqual(config.browser, 'librewolf')

    def test_workstation_rdp_can_be_enabled_explicitly(self):
        config = SetupConfig.from_args(self._make_args(enable_rdp=True), 'workstation_desktop')
        self.assertTrue(config.enable_rdp)
        self.assertTrue(config.include_desktop)

    def test_pc_dev_defaults_include_office_and_smbclient(self):
        config = SetupConfig.from_args(self._make_args(), 'pc_dev')
        self.assertEqual(config.machine_type, 'vm')
        self.assertTrue(config.install_office)
        self.assertTrue(config.enable_smbclient)
        self.assertTrue(config.include_pc_dev_apps)

    def test_server_web_defaults_to_vm(self):
        config = SetupConfig.from_args(self._make_args(), 'server_web')
        self.assertEqual(config.machine_type, 'vm')

    def test_build_server_defaults_to_vm(self):
        config = SetupConfig.from_args(
            self._make_args(is_build_server=True),
            'server_lite',
        )
        self.assertTrue(config.is_build_server)
        self.assertEqual(config.machine_type, 'vm')

    def test_explicit_machine_type_overrides_vm_default(self):
        config = SetupConfig.from_args(
            self._make_args(machine_type='unprivileged'),
            'workstation_dev',
        )
        self.assertEqual(config.machine_type, 'unprivileged')

    def test_antistatic_db_from_args(self):
        config = SetupConfig.from_args(
            self._make_args(antistatic_db='db.example.com'),
            'server_web',
        )
        self.assertEqual(config.antistatic_db, 'db.example.com')

    def test_gogs_from_args(self):
        config = SetupConfig.from_args(
            self._make_args(gogs=['git.example.com:3000', '/srv/gogs']),
            'server_web',
        )
        self.assertEqual(config.gogs, ['git.example.com:3000', '/srv/gogs'])

    def test_server_proxmox_defaults_defer_restart_with_force_deadline(self):
        config = SetupConfig.from_args(self._make_args(), 'server_proxmox')
        self.assertFalse(config.auto_restart)
        self.assertEqual(config.auto_restart_force_days, 7)
        self.assertEqual(config.auto_restart_grace, 5)
        self.assertFalse(config.include_cli_tools)
        self.assertFalse(config.include_desktop)

    def test_from_dict_server_proxmox_defaults_restart_policy_when_missing(self):
        config = SetupConfig.from_dict(
            'pve1',
            'server_proxmox',
            {'username': 'root'},
        )
        self.assertFalse(config.auto_restart)
        self.assertEqual(config.auto_restart_force_days, 7)

    def test_from_dict_maps_legacy_no_restart(self):
        config = SetupConfig.from_dict(
            'server1',
            'server_lite',
            {'username': 'root', 'no_restart': True},
        )
        self.assertFalse(config.auto_restart)


class TestSetupConfigHostedFields(unittest.TestCase):
    def _make_config(self, **kwargs):
        defaults: dict[str, object] = dict(host='testhost', username='testuser', system_type='server_lite')
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
            container_storage=[['root', 'auto', '10G'], ['template', 'local']],
            container_cores=4,
            container_base='ubuntu',
        )
        self.assertEqual(config.hosted_node, '10.0.0.1')
        self.assertEqual(config.hosted_user, 'admin')
        self.assertEqual(config.hosted_key, '/path/to/key')
        self.assertEqual(config.container_memory, '2G')
        self.assertEqual(config.container_storage, [['root', 'auto', '10G'], ['template', 'local']])
        self.assertEqual(config.container_cores, 4)
        self.assertEqual(config.container_base, 'ubuntu')

    def test_to_dict_includes_hosted_fields(self):
        config = self._make_config(
            hosted_node='10.0.0.1',
            container_memory='2G',
            container_storage=[['root', 'auto', '10G'], ['template', 'local']],
        )
        d = config.to_dict()
        self.assertEqual(d['hosted_node'], '10.0.0.1')
        self.assertEqual(d['container_memory'], '2G')
        self.assertEqual(d['container_storage'], [['root', 'auto', '10G'], ['template', 'local']])

    def test_from_dict_restores_hosted_fields(self):
        data = {
            'username': 'testuser',
            'hosted_node': '10.0.0.1',
            'container_memory': '4G',
            'container_storage': [['template', 'local'], ['root', 'auto', '5G']],
            'container_cores': 8,
            'container_base': 'fedora',
        }
        config = SetupConfig.from_dict('target', 'server_web', data)
        self.assertEqual(config.hosted_node, '10.0.0.1')
        self.assertEqual(config.container_memory, '4G')
        self.assertEqual(config.container_storage, [['template', 'local'], ['root', 'auto', '5G']])
        self.assertEqual(config.container_cores, 8)
        self.assertEqual(config.container_base, 'fedora')

    def test_hosted_fields_not_in_remote_args(self):
        config = self._make_config(
            hosted_node='10.0.0.1',
            container_memory='2G',
            container_storage=[['root', 'auto', '10G'], ['template', 'local']],
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
            container_storage=[['root', 'auto', '10G'], ['template', 'local']],
        )
        parts = config.to_setup_command()
        cmd = ' '.join(parts)
        self.assertNotIn('--hosted', cmd)
        self.assertNotIn('--memory', cmd)
        self.assertNotIn('--storage', cmd)


if __name__ == '__main__':
    unittest.main()
