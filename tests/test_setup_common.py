"""Tests for lib/setup_common.py: setup_main timing/status persistence."""

from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.config import SetupConfig
from lib.proxmox_hosts import ProxmoxHost, ProxmoxHostFacts, add_proxmox_host


def _make_config(**kwargs) -> SetupConfig:
    defaults = dict(host='testhost', username='testuser', system_type='server_lite')
    defaults.update(kwargs)
    return SetupConfig(**defaults)


class TestSetupMainTimingPersistence(unittest.TestCase):
    """Verify setup_main always saves last_start_time/end_time/success."""

    def test_success_saves_timing_and_success_true(self):
        with tempfile.TemporaryDirectory():
            from lib import setup_common
            config = _make_config()
            saved_calls = []

            def fake_save(cfg, start_time=None, end_time=None, success=None, **kwargs):
                saved_calls.append(
                    {
                        'start_time': start_time,
                        'end_time': end_time,
                        'success': success,
                        'operation': kwargs.get('operation'),
                    }
                )

            with patch.object(setup_common, 'run_remote_setup', return_value=0), \
                 patch.object(setup_common, 'validate_host', return_value=True), \
                 patch.object(setup_common, 'validate_username', return_value=True), \
                 patch.object(setup_common, 'get_current_username', return_value='testuser'), \
                 patch.object(setup_common, 'validate_samba_share_credentials'), \
                 patch.object(setup_common, 'print_setup_summary'), \
                 patch.object(setup_common, 'store_cli_credentials'), \
                 patch.object(setup_common, 'save_setup_command', side_effect=fake_save):

                parser = MagicMock()
                args = MagicMock()
                args.host = 'testhost'
                args.username = 'testuser'
                args.dry_run = False
                parser.parse_args.return_value = args

                with patch.object(setup_common, 'create_argument_parser', return_value=parser), \
                     patch('lib.config.SetupConfig.from_args', return_value=config):
                    setup_common.setup_main('server_lite', 'Test', lambda c: None)

            # Two saves expected: first is the pre-run config-only save (no timing),
            # second is the post-run save with start_time/end_time/success.
            self.assertEqual(len(saved_calls), 2)
            self.assertEqual(saved_calls[0]['operation'], 'setup')
            post_run = saved_calls[1]
            self.assertIsNotNone(post_run['start_time'])
            self.assertIsNotNone(post_run['end_time'])
            self.assertIs(post_run['success'], True)
            self.assertEqual(post_run['operation'], 'setup')

    def test_failure_saves_timing_and_success_false(self):
        with tempfile.TemporaryDirectory():
            from lib import setup_common
            config = _make_config()
            saved_calls = []

            def fake_save(cfg, start_time=None, end_time=None, success=None, **kwargs):
                saved_calls.append(
                    {
                        'start_time': start_time,
                        'end_time': end_time,
                        'success': success,
                        'operation': kwargs.get('operation'),
                    }
                )

            with patch.object(setup_common, 'run_remote_setup', return_value=1), \
                 patch.object(setup_common, 'validate_host', return_value=True), \
                 patch.object(setup_common, 'validate_username', return_value=True), \
                 patch.object(setup_common, 'get_current_username', return_value='testuser'), \
                 patch.object(setup_common, 'validate_samba_share_credentials'), \
                 patch.object(setup_common, 'print_setup_summary'), \
                 patch.object(setup_common, 'store_cli_credentials'), \
                 patch.object(setup_common, 'save_setup_command', side_effect=fake_save):

                parser = MagicMock()
                args = MagicMock()
                args.host = 'testhost'
                args.username = 'testuser'
                args.dry_run = False
                parser.parse_args.return_value = args

                with patch.object(setup_common, 'create_argument_parser', return_value=parser), \
                     patch('lib.config.SetupConfig.from_args', return_value=config):
                    result = setup_common.setup_main('server_lite', 'Test', lambda c: None)

            self.assertEqual(result, 1)
            post_run = saved_calls[1]
            self.assertIsNotNone(post_run['start_time'])
            self.assertIsNotNone(post_run['end_time'])
            self.assertIs(post_run['success'], False)
            self.assertEqual(post_run['operation'], 'setup')

    def test_exception_saves_timing_and_success_false(self):
        """Verifies that even if run_remote_setup raises, success=False is saved."""
        with tempfile.TemporaryDirectory():
            from lib import setup_common
            config = _make_config()
            saved_calls = []

            def fake_save(cfg, start_time=None, end_time=None, success=None, **kwargs):
                saved_calls.append(
                    {
                        'start_time': start_time,
                        'end_time': end_time,
                        'success': success,
                        'operation': kwargs.get('operation'),
                    }
                )

            with patch.object(setup_common, 'run_remote_setup', side_effect=RuntimeError('boom')), \
                 patch.object(setup_common, 'validate_host', return_value=True), \
                 patch.object(setup_common, 'validate_username', return_value=True), \
                 patch.object(setup_common, 'get_current_username', return_value='testuser'), \
                 patch.object(setup_common, 'validate_samba_share_credentials'), \
                 patch.object(setup_common, 'print_setup_summary'), \
                 patch.object(setup_common, 'store_cli_credentials'), \
                 patch.object(setup_common, 'save_setup_command', side_effect=fake_save):

                parser = MagicMock()
                args = MagicMock()
                args.host = 'testhost'
                args.username = 'testuser'
                args.dry_run = False
                parser.parse_args.return_value = args

                with patch.object(setup_common, 'create_argument_parser', return_value=parser), \
                     patch('lib.config.SetupConfig.from_args', return_value=config):
                    with self.assertRaises(RuntimeError):
                        setup_common.setup_main('server_lite', 'Test', lambda c: None)

            # Post-run save must happen even after exception
            self.assertEqual(len(saved_calls), 2)
            post_run = saved_calls[1]
            self.assertIsNotNone(post_run['start_time'])
            self.assertIsNotNone(post_run['end_time'])
            self.assertIs(post_run['success'], False)
            self.assertEqual(post_run['operation'], 'setup')

    def test_dry_run_skips_post_run_save(self):
        """In dry-run mode, save_setup_command should never be called."""
        with tempfile.TemporaryDirectory():
            from lib import setup_common
            config = _make_config(dry_run=True)
            saved_calls = []

            def fake_save(cfg, start_time=None, end_time=None, success=None, **kwargs):
                saved_calls.append(
                    {
                        'start_time': start_time,
                        'end_time': end_time,
                        'success': success,
                        'operation': kwargs.get('operation'),
                    }
                )

            with patch.object(setup_common, 'run_remote_setup', return_value=0), \
                 patch.object(setup_common, 'validate_host', return_value=True), \
                 patch.object(setup_common, 'validate_username', return_value=True), \
                 patch.object(setup_common, 'get_current_username', return_value='testuser'), \
                 patch.object(setup_common, 'validate_samba_share_credentials'), \
                 patch.object(setup_common, 'print_setup_summary'), \
                 patch.object(setup_common, 'save_setup_command', side_effect=fake_save):

                parser = MagicMock()
                args = MagicMock()
                args.host = 'testhost'
                args.username = 'testuser'
                args.dry_run = True
                parser.parse_args.return_value = args

                with patch.object(setup_common, 'create_argument_parser', return_value=parser), \
                     patch('lib.config.SetupConfig.from_args', return_value=config):
                    setup_common.setup_main('server_lite', 'Test', lambda c: None)

            self.assertEqual(saved_calls, [])


class TestRunRemoteSetupArgumentSecurity(unittest.TestCase):
    def test_copy_project_files_includes_plugins_package(self):
        from lib import setup_common

        with tempfile.TemporaryDirectory() as tmpdir:
            setup_common.copy_project_files(tmpdir)
            self.assertTrue(os.path.isdir(os.path.join(tmpdir, "plugins")))
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "plugins", "__init__.py")))
            self.assertTrue(os.path.isdir(os.path.join(tmpdir, "game")))
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "game", "__init__.py")))

    def test_write_remote_args_file_uses_secure_json_file(self):
        from lib import setup_common

        with tempfile.TemporaryDirectory() as tmpdir:
            path = setup_common._write_remote_args_file(tmpdir, ["--credential", "mediauser", "supersecret"])

            with open(path, encoding="utf-8") as file_obj:
                self.assertEqual(file_obj.read().strip(), '["--credential", "mediauser", "supersecret"]')
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_remote_ssh_command_uses_args_file_without_inline_passwords(self):
        from lib import setup_common

        config = _make_config(
            host="example.com",
            share_credentials=[["mediauser", "supersecret"]],
        )
        process = MagicMock()
        process.stdin = io.BytesIO()
        process.stdout = io.BytesIO(b"")
        process.wait.return_value = 0

        with patch.object(setup_common, "copy_project_files"), \
             patch.object(setup_common, "prepare_deployments"), \
             patch.object(setup_common, "build_ssh_command", return_value=["ssh"]) as mock_build_ssh, \
             patch("subprocess.Popen", return_value=process):
            result = setup_common.run_remote_setup(config)

        self.assertEqual(result, 0)
        remote_command = mock_build_ssh.call_args.kwargs["remote_command"]
        self.assertIn("--args-file", remote_command)
        self.assertNotIn("supersecret", remote_command)


class TestSetupMainValidation(unittest.TestCase):

    @patch("builtins.print")
    def test_invalid_workspace_returns_error_before_validation(self, mock_print):
        from lib import setup_common

        parser = MagicMock()
        args = MagicMock()
        args.workspace = "/bad/workspace"
        parser.parse_args.return_value = args

        with patch.object(setup_common, "create_argument_parser", return_value=parser), \
             patch.object(setup_common, "validate_workspace_dir", side_effect=ValueError("bad workspace")), \
             patch.object(setup_common, "set_workspace_dir") as mock_set_workspace, \
             patch.object(setup_common, "validate_host") as mock_validate_host:
            result = setup_common.setup_main("server_lite", "Test", lambda c: None)

        self.assertEqual(result, 1)
        mock_set_workspace.assert_not_called()
        mock_validate_host.assert_not_called()
        mock_print.assert_called_with("Error: bad workspace")

    @patch("builtins.print")
    def test_invalid_notify_specs_return_error_before_remote_setup(self, mock_print):
        from lib import setup_common

        parser = MagicMock()
        args = MagicMock()
        args.workspace = None
        args.host = "testhost"
        args.username = "testuser"
        parser.parse_args.return_value = args
        config = _make_config(notify_specs=[["webhook", "not-a-url"]])

        with patch.object(setup_common, "create_argument_parser", return_value=parser), \
             patch.object(setup_common, "validate_host", return_value=True), \
             patch.object(setup_common, "validate_username", return_value=True), \
             patch.object(setup_common, "prepare_runtime_config", return_value=config), \
             patch.object(setup_common, "validate_hosted_flags", side_effect=ValueError("Invalid hosted node host: bad host")), \
             patch.object(setup_common, "run_remote_setup") as mock_run_remote:
            result = setup_common.setup_main("server_lite", "Test", lambda c: None)

        self.assertEqual(result, 1)
        mock_run_remote.assert_not_called()
        mock_print.assert_called_with("Error: Invalid webhook URL: not-a-url")

    @patch("builtins.print")
    def test_invalid_deploy_targets_return_error_before_remote_setup(self, mock_print):
        from lib import setup_common

        parser = MagicMock()
        args = MagicMock()
        args.workspace = None
        args.host = "testhost"
        args.username = "testuser"
        parser.parse_args.return_value = args
        config = _make_config(deploy_targets=["bad target"])

        with patch.object(setup_common, "create_argument_parser", return_value=parser), \
             patch.object(setup_common, "validate_host", return_value=True), \
             patch.object(setup_common, "validate_username", return_value=True), \
             patch.object(setup_common, "prepare_runtime_config", return_value=config), \
             patch.object(setup_common, "validate_hosted_flags", side_effect=ValueError("Invalid hosted node host: bad host")), \
             patch.object(setup_common, "run_remote_setup") as mock_run_remote:
            result = setup_common.setup_main("server_lite", "Test", lambda c: None)

        self.assertEqual(result, 1)
        mock_run_remote.assert_not_called()
        mock_print.assert_called_with("Error: Invalid deploy target host: bad target")

    @patch("builtins.print")
    def test_invalid_deploy_specs_return_error_before_remote_setup(self, mock_print):
        from lib import setup_common

        parser = MagicMock()
        args = MagicMock()
        args.workspace = None
        args.host = "testhost"
        args.username = "testuser"
        parser.parse_args.return_value = args
        config = _make_config(deploy_specs=[["bad domain", "https://github.com/user/repo.git"]])

        with patch.object(setup_common, "create_argument_parser", return_value=parser), \
             patch.object(setup_common, "validate_host", return_value=True), \
             patch.object(setup_common, "validate_username", return_value=True), \
             patch.object(setup_common, "prepare_runtime_config", return_value=config), \
             patch.object(setup_common, "validate_hosted_flags", side_effect=ValueError("Invalid hosted node host: bad host")), \
             patch.object(setup_common, "run_remote_setup") as mock_run_remote:
            result = setup_common.setup_main("server_lite", "Test", lambda c: None)

        self.assertEqual(result, 1)
        mock_run_remote.assert_not_called()
        mock_print.assert_called_with("Error: Invalid deploy domain: bad domain")

    @patch("builtins.print")
    def test_invalid_samba_share_specs_return_error_before_remote_setup(self, mock_print):
        from lib import setup_common

        parser = MagicMock()
        args = MagicMock()
        args.workspace = None
        args.host = "testhost"
        args.username = "testuser"
        parser.parse_args.return_value = args
        config = _make_config(samba_shares=[["read", "bad/share", "/mnt/docs", "shareuser:secret"]])

        with patch.object(setup_common, "create_argument_parser", return_value=parser), \
             patch.object(setup_common, "validate_host", return_value=True), \
             patch.object(setup_common, "validate_username", return_value=True), \
             patch.object(setup_common, "prepare_runtime_config", return_value=config), \
             patch.object(setup_common, "run_remote_setup") as mock_run_remote:
            result = setup_common.setup_main("server_lite", "Test", lambda c: None)

        self.assertEqual(result, 1)
        mock_run_remote.assert_not_called()
        mock_print.assert_called_with("Error: Invalid Samba share name (cannot contain /, \\, or spaces): bad/share")

    @patch("builtins.print")
    def test_invalid_ssl_email_returns_error_before_remote_setup(self, mock_print):
        from lib import setup_common

        parser = MagicMock()
        args = MagicMock()
        args.workspace = None
        args.host = "testhost"
        args.username = "testuser"
        parser.parse_args.return_value = args
        config = _make_config(ssl_email="bad-email")

        with patch.object(setup_common, "create_argument_parser", return_value=parser), \
             patch.object(setup_common, "validate_host", return_value=True), \
             patch.object(setup_common, "validate_username", return_value=True), \
             patch.object(setup_common, "prepare_runtime_config", return_value=config), \
             patch.object(setup_common, "run_remote_setup") as mock_run_remote:
            result = setup_common.setup_main("server_lite", "Test", lambda c: None)

        self.assertEqual(result, 1)
        mock_run_remote.assert_not_called()
        mock_print.assert_called_with("Error: Invalid SSL email address: bad-email")

    @patch("builtins.print")
    def test_invalid_apt_package_returns_error_before_remote_setup(self, mock_print):
        from lib import setup_common

        parser = MagicMock()
        args = MagicMock()
        args.workspace = None
        args.host = "testhost"
        args.username = "testuser"
        parser.parse_args.return_value = args
        config = _make_config(apt_packages=["python3; rm -rf /"])

        with patch.object(setup_common, "create_argument_parser", return_value=parser), \
             patch.object(setup_common, "validate_host", return_value=True), \
             patch.object(setup_common, "validate_username", return_value=True), \
             patch.object(setup_common, "prepare_runtime_config", return_value=config), \
             patch.object(setup_common, "run_remote_setup") as mock_run_remote:
            result = setup_common.setup_main("server_lite", "Test", lambda c: None)

        self.assertEqual(result, 1)
        mock_run_remote.assert_not_called()
        mock_print.assert_called_with("Error: Invalid --apt-install name: python3; rm -rf /")

    @patch("builtins.print")
    def test_invalid_timezone_returns_error_before_remote_setup(self, mock_print):
        from lib import setup_common

        parser = MagicMock()
        args = MagicMock()
        args.workspace = None
        args.host = "testhost"
        args.username = "testuser"
        parser.parse_args.return_value = args
        config = _make_config(timezone="Mars/Olympus")

        with patch.object(setup_common, "create_argument_parser", return_value=parser), \
             patch.object(setup_common, "validate_host", return_value=True), \
             patch.object(setup_common, "validate_username", return_value=True), \
             patch.object(setup_common, "prepare_runtime_config", return_value=config), \
             patch.object(setup_common, "run_remote_setup") as mock_run_remote:
            result = setup_common.setup_main("server_lite", "Test", lambda c: None)

        self.assertEqual(result, 1)
        mock_run_remote.assert_not_called()
        mock_print.assert_called_with("Error: Invalid timezone: Mars/Olympus")

    @patch("builtins.print")
    def test_invalid_sync_specs_return_error_before_remote_setup(self, mock_print):
        from lib import setup_common

        parser = MagicMock()
        args = MagicMock()
        args.workspace = None
        args.host = "testhost"
        args.username = "testuser"
        parser.parse_args.return_value = args
        config = _make_config(sync_specs=[["relative", "/dst", "daily"]])

        with patch.object(setup_common, "create_argument_parser", return_value=parser), \
             patch.object(setup_common, "validate_host", return_value=True), \
             patch.object(setup_common, "validate_username", return_value=True), \
             patch.object(setup_common, "prepare_runtime_config", return_value=config), \
             patch.object(setup_common, "run_remote_setup") as mock_run_remote:
            result = setup_common.setup_main("server_lite", "Test", lambda c: None)

        self.assertEqual(result, 1)
        mock_run_remote.assert_not_called()
        mock_print.assert_called_with("Error: Source path must be absolute: relative")

    @patch("builtins.print")
    def test_invalid_scrub_specs_return_error_before_remote_setup(self, mock_print):
        from lib import setup_common

        parser = MagicMock()
        args = MagicMock()
        args.workspace = None
        args.host = "testhost"
        args.username = "testuser"
        parser.parse_args.return_value = args
        config = _make_config(scrub_specs=[["/data", ".pardatabase", "0%", "weekly"]])

        with patch.object(setup_common, "create_argument_parser", return_value=parser), \
             patch.object(setup_common, "validate_host", return_value=True), \
             patch.object(setup_common, "validate_username", return_value=True), \
             patch.object(setup_common, "prepare_runtime_config", return_value=config), \
             patch.object(setup_common, "run_remote_setup") as mock_run_remote:
            result = setup_common.setup_main("server_lite", "Test", lambda c: None)

        self.assertEqual(result, 1)
        mock_run_remote.assert_not_called()
        mock_print.assert_called_with("Error: Redundancy percentage must be between 1 and 100: 0%")

    @patch("builtins.print")
    def test_invalid_smb_mount_specs_return_error_before_remote_setup(self, mock_print):
        from lib import setup_common

        parser = MagicMock()
        args = MagicMock()
        args.workspace = None
        args.host = "testhost"
        args.username = "testuser"
        parser.parse_args.return_value = args
        config = _make_config(smb_mounts=[["/mnt/share", "bad host", "user:pass", "docs", "/sub"]])

        with patch.object(setup_common, "create_argument_parser", return_value=parser), \
             patch.object(setup_common, "validate_host", return_value=True), \
             patch.object(setup_common, "validate_username", return_value=True), \
             patch.object(setup_common, "prepare_runtime_config", return_value=config), \
             patch.object(setup_common, "run_remote_setup") as mock_run_remote:
            result = setup_common.setup_main("server_lite", "Test", lambda c: None)

        self.assertEqual(result, 1)
        mock_run_remote.assert_not_called()
        mock_print.assert_called_with("Error: Invalid SMB mount host: bad host")


class TestExpandRemoteArgs(unittest.TestCase):
    def test_expand_remote_args_preserves_quoted_values(self):
        from lib.setup_common import _expand_remote_args

        expanded = _expand_remote_args([
            "--timezone 'America/New_York'",
            "--mount-smb /mnt/share 1.2.3.4 'user:secret phrase' docs /",
        ])

        self.assertEqual(
            expanded,
            [
                "--timezone",
                "America/New_York",
                "--mount-smb",
                "/mnt/share",
                "1.2.3.4",
                "user:secret phrase",
                "docs",
                "/",
            ],
        )


class TestHostedProvisioningDispatch(unittest.TestCase):
    def _make_args(self) -> MagicMock:
        args = MagicMock()
        args.workspace = None
        args.host = "testhost"
        args.username = "testuser"
        args.dry_run = False
        return args

    @patch("builtins.print")
    def test_hosted_vm_setup_dispatches_to_provision_vm(self, _mock_print):
        from lib import setup_common

        parser = MagicMock()
        parser.parse_args.return_value = self._make_args()
        config = _make_config(
            system_type="server_web",
            machine_type="vm",
            hosted_node="10.0.0.1",
            container_memory="2G",
            container_storage=[["root", "local-lvm", "10G"]],
            vm_image="local:iso/debian-12-generic-amd64.qcow2",
        )

        with patch.object(setup_common, "create_argument_parser", return_value=parser), \
             patch.object(setup_common, "validate_host", return_value=True), \
             patch.object(setup_common, "validate_username", return_value=True), \
             patch.object(setup_common, "prepare_runtime_config", return_value=config), \
             patch.object(setup_common, "validate_hosted_flags"), \
             patch.object(setup_common, "validate_samba_share_credentials"), \
             patch.object(setup_common, "print_setup_summary"), \
             patch.object(setup_common, "store_cli_credentials"), \
             patch.object(setup_common, "save_setup_command"), \
             patch.object(setup_common, "run_remote_setup", return_value=0) as mock_run_remote, \
             patch("lib.config.SetupConfig.from_args", return_value=config), \
             patch("lib.proxmox_vm.provision_vm") as mock_provision_vm:
            result = setup_common.setup_main("server_web", "Test", lambda c: None)

        self.assertEqual(result, 0)
        mock_provision_vm.assert_called_once_with(config, image=config.vm_image)
        mock_run_remote.assert_called_once_with(config)

    @patch("builtins.print")
    def test_hosted_vm_setup_continues_when_vm_already_exists(self, _mock_print):
        from lib import setup_common
        from lib.proxmox_vm import VMAlreadyExists

        parser = MagicMock()
        parser.parse_args.return_value = self._make_args()
        config = _make_config(
            system_type="server_web",
            machine_type="vm",
            hosted_node="10.0.0.1",
            container_memory="2G",
            container_storage=[["root", "local-lvm", "10G"]],
        )

        with patch.object(setup_common, "create_argument_parser", return_value=parser), \
             patch.object(setup_common, "validate_host", return_value=True), \
             patch.object(setup_common, "validate_username", return_value=True), \
             patch.object(setup_common, "prepare_runtime_config", return_value=config), \
             patch.object(setup_common, "validate_hosted_flags"), \
             patch.object(setup_common, "validate_samba_share_credentials"), \
             patch.object(setup_common, "print_setup_summary"), \
             patch.object(setup_common, "store_cli_credentials"), \
             patch.object(setup_common, "save_setup_command"), \
             patch.object(setup_common, "run_remote_setup", return_value=0) as mock_run_remote, \
             patch("lib.config.SetupConfig.from_args", return_value=config), \
             patch("lib.proxmox_vm.provision_vm", side_effect=VMAlreadyExists()):
            result = setup_common.setup_main("server_web", "Test", lambda c: None)

        self.assertEqual(result, 0)
        mock_run_remote.assert_called_once_with(config)

    @patch("builtins.print")
    def test_hosted_lxc_setup_dispatches_to_provision_container(self, _mock_print):
        from lib import setup_common

        parser = MagicMock()
        parser.parse_args.return_value = self._make_args()
        config = _make_config(
            machine_type="unprivileged",
            hosted_node="10.0.0.1",
            container_memory="2G",
            container_storage=[["root", "local-lvm", "10G"], ["template", "local"]],
        )

        with patch.object(setup_common, "create_argument_parser", return_value=parser), \
             patch.object(setup_common, "validate_host", return_value=True), \
             patch.object(setup_common, "validate_username", return_value=True), \
             patch.object(setup_common, "prepare_runtime_config", return_value=config), \
             patch.object(setup_common, "validate_hosted_flags"), \
             patch.object(setup_common, "validate_samba_share_credentials"), \
             patch.object(setup_common, "print_setup_summary"), \
             patch.object(setup_common, "store_cli_credentials"), \
             patch.object(setup_common, "save_setup_command"), \
             patch.object(setup_common, "run_remote_setup", return_value=0) as mock_run_remote, \
             patch("lib.config.SetupConfig.from_args", return_value=config), \
             patch("lib.proxmox_node.provision_container") as mock_provision_container:
            result = setup_common.setup_main("server_lite", "Test", lambda c: None)

        self.assertEqual(result, 0)
        mock_provision_container.assert_called_once_with(config)
        mock_run_remote.assert_called_once_with(config)

    @patch("builtins.print")
    def test_hosted_vm_setup_expands_saved_host_root_storage(self, _mock_print):
        from lib import setup_common

        with tempfile.TemporaryDirectory() as workspace:
            add_proxmox_host(
                ProxmoxHost(
                    name="pve1",
                    address="10.0.0.1",
                    ssh_key="/keys/proxmox",
                    facts=ProxmoxHostFacts(
                        default_root_storage="local-lvm",
                        default_bridge="vmbr0",
                    ),
                ),
                workspace,
            )
            parser = MagicMock()
            args = self._make_args()
            args.workspace = workspace
            parser.parse_args.return_value = args
            config = _make_config(
                system_type="server_web",
                machine_type="vm",
                hosted_node="pve1",
                hosted_key=None,
                container_memory="2G",
                container_storage=[["root", "10G"]],
                vm_image="local:iso/debian-12-generic-amd64.qcow2",
            )

            with patch.object(setup_common, "create_argument_parser", return_value=parser), \
                 patch.object(setup_common, "validate_host", return_value=True), \
                 patch.object(setup_common, "validate_username", return_value=True), \
                 patch.object(setup_common, "prepare_runtime_config", return_value=config), \
                 patch.object(setup_common, "validate_samba_share_credentials"), \
                 patch.object(setup_common, "print_setup_summary"), \
                 patch.object(setup_common, "store_cli_credentials"), \
                 patch.object(setup_common, "save_setup_command"), \
                 patch.object(setup_common, "run_remote_setup", return_value=0), \
                 patch("lib.config.SetupConfig.from_args", return_value=config), \
                 patch("lib.proxmox_vm.provision_vm") as mock_provision_vm:
                result = setup_common.setup_main("server_web", "Test", lambda c: None)

        self.assertEqual(result, 0)
        self.assertEqual(config.hosted_node, "10.0.0.1")
        self.assertEqual(config.hosted_key, "/keys/proxmox")
        self.assertEqual(config.container_storage, [["root", "local-lvm", "10G"]])
        mock_provision_vm.assert_called_once_with(config, image=config.vm_image)

    @patch("builtins.print")
    def test_hosted_lxc_setup_expands_saved_template_storage(self, _mock_print):
        from lib import setup_common

        with tempfile.TemporaryDirectory() as workspace:
            add_proxmox_host(
                ProxmoxHost(
                    name="pve1",
                    address="10.0.0.1",
                    default_storage="local-lvm",
                    facts=ProxmoxHostFacts(default_template_storage="local"),
                ),
                workspace,
            )
            parser = MagicMock()
            args = self._make_args()
            args.workspace = workspace
            parser.parse_args.return_value = args
            config = _make_config(
                machine_type="unprivileged",
                hosted_node="pve1",
                container_memory="2G",
                container_storage=[["root", "host", "10G"], ["template"]],
            )

            with patch.object(setup_common, "create_argument_parser", return_value=parser), \
                 patch.object(setup_common, "validate_host", return_value=True), \
                 patch.object(setup_common, "validate_username", return_value=True), \
                 patch.object(setup_common, "prepare_runtime_config", return_value=config), \
                 patch.object(setup_common, "validate_samba_share_credentials"), \
                 patch.object(setup_common, "print_setup_summary"), \
                 patch.object(setup_common, "store_cli_credentials"), \
                 patch.object(setup_common, "save_setup_command"), \
                 patch.object(setup_common, "run_remote_setup", return_value=0), \
                 patch("lib.config.SetupConfig.from_args", return_value=config), \
                 patch("lib.proxmox_node.provision_container") as mock_provision_container:
                result = setup_common.setup_main("server_lite", "Test", lambda c: None)

        self.assertEqual(result, 0)
        self.assertEqual(
            config.container_storage,
            [["root", "local-lvm", "10G"], ["template", "local"]],
        )
        mock_provision_container.assert_called_once_with(config)


if __name__ == '__main__':
    unittest.main()
