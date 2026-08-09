"""Tests for agent installer metadata, verification, and local diagnostics."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from common.agent_steps import (
    _download_verified_file,
    _latest_t3code_asset,
    _copy_secret_file,
    _user_home,
    copy_agent_tooling_payload,
    install_agent_repositories,
    install_claude,
    install_codex,
    install_opencode,
    install_t3code,
)
from lib.agent_cli import inspect_agent_tools, run_agent_command, update_agent_tools
from lib.agent_cli import _download_codex_installer, _invoke_agent_update
from lib.config import SetupConfig


class TestOfficialAgentInstallers(unittest.TestCase):
    def setUp(self):
        self.config = SetupConfig(
            host='host',
            username='agent',
            system_type='server_dev',
        )

    def test_cli_installers_use_official_scripts_without_npm(self):
        with patch('common.agent_steps._install_script_tool') as installer:
            install_codex(self.config)
            install_claude(self.config)
            install_opencode(self.config)

        commands = [call.kwargs['installer'] for call in installer.call_args_list]
        self.assertEqual(commands, [
            'curl -fsSL https://chatgpt.com/codex/install.sh | sh',
            'curl -fsSL https://claude.ai/install.sh | bash',
            'curl -fsSL https://opencode.ai/install | bash',
        ])
        self.assertTrue(all('npm' not in command for command in commands))

    def test_latest_t3code_asset_requires_official_digest(self):
        response = io.BytesIO(
            b'{"assets":[{"name":"T3-Code-1.2.3-x86_64.AppImage",'
            b'"browser_download_url":"https://github.com/pingdotgg/t3code/releases/download/v1/file",'
            b'"digest":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}]}'
        )
        with patch('urllib.request.urlopen', return_value=response):
            url, digest = _latest_t3code_asset()
        self.assertEqual(
            url,
            'https://github.com/pingdotgg/t3code/releases/download/v1/file',
        )
        self.assertEqual(digest, 'a' * 64)

    def test_latest_t3code_asset_normalizes_digest_case(self):
        response = io.BytesIO(
            b'{"assets":[{"name":"T3-Code-1.2.3-x86_64.AppImage",'
            b'"browser_download_url":"https://github.com/pingdotgg/t3code/releases/download/v1/file",'
            b'"digest":"sha256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"}]}'
        )
        with patch('urllib.request.urlopen', return_value=response):
            _url, digest = _latest_t3code_asset()
        self.assertEqual(digest, 'a' * 64)

    def test_user_home_comes_from_account_database(self):
        account = type('Account', (), {'pw_dir': '/srv/agent'})()
        with patch('common.agent_steps.pwd.getpwnam', return_value=account):
            self.assertEqual(_user_home(self.config), '/srv/agent')

    def test_verified_download_rejects_checksum_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = os.path.join(directory, 'tool.AppImage')
            with patch('urllib.request.urlopen', return_value=io.BytesIO(b'payload')):
                with self.assertRaisesRegex(RuntimeError, 'checksum'):
                    _download_verified_file('https://github.com/example', 'wrong', destination)
            self.assertFalse(os.path.exists(destination))

    def test_verified_download_writes_matching_payload(self):
        payload = b'official-appimage'
        expected = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            destination = os.path.join(directory, 'tool.AppImage')
            with patch('urllib.request.urlopen', return_value=io.BytesIO(payload)):
                _download_verified_file('https://github.com/example', expected, destination)
            with open(destination, 'rb') as file_obj:
                self.assertEqual(file_obj.read(), payload)

    def test_t3code_install_adds_minimal_wrapper_and_desktop_entry(self):
        with tempfile.TemporaryDirectory() as home:
            def write_appimage(_url, _digest, destination):
                with open(destination, 'wb') as file_obj:
                    file_obj.write(b'appimage')

            with (
                patch('common.agent_steps.platform.machine', return_value='x86_64'),
                patch('common.agent_steps._user_home', return_value=home),
                patch('common.agent_steps._tool_available', return_value=False),
                patch(
                    'common.agent_steps._latest_t3code_asset',
                    return_value=('https://github.com/example', 'a' * 64),
                ),
                patch(
                    'common.agent_steps._download_verified_file',
                    side_effect=write_appimage,
                ),
                patch('common.agent_steps._chown_path'),
                patch('common.agent_steps._ensure_agent_shell_path'),
            ):
                install_t3code(self.config)

            wrapper = os.path.join(home, '.local', 'bin', 't3code')
            desktop = os.path.join(
                home,
                '.local',
                'share',
                'applications',
                't3code.desktop',
            )
            with open(wrapper, encoding='utf-8') as file_obj:
                self.assertIn('APPIMAGE_EXTRACT_AND_RUN', file_obj.read())
            with open(desktop, encoding='utf-8') as file_obj:
                self.assertIn(f'Exec={wrapper}', file_obj.read())


class TestAgentDoctor(unittest.TestCase):
    def test_inspects_user_tool_and_credentials_without_contents(self):
        with tempfile.TemporaryDirectory() as home:
            bin_dir = os.path.join(home, '.local', 'bin')
            os.makedirs(bin_dir)
            codex_path = os.path.join(bin_dir, 'codex')
            with open(codex_path, 'w', encoding='utf-8') as file_obj:
                file_obj.write('#!/bin/sh\necho "codex 1.2.3"\n')
            os.chmod(codex_path, 0o755)
            os.makedirs(os.path.join(home, '.codex'))
            with open(os.path.join(home, '.codex', 'auth.json'), 'w', encoding='utf-8') as file_obj:
                file_obj.write('{"secret":"never-print-this"}\n')

            result = inspect_agent_tools(['codex'], home=home)

        self.assertTrue(result[0]['installed'])
        self.assertEqual(result[0]['version'], 'codex 1.2.3')
        self.assertTrue(result[0]['credential'])
        self.assertNotIn('never-print-this', str(result))

    def test_explicit_missing_tool_is_unhealthy(self):
        args = argparse.Namespace(
            agent_command='doctor',
            agent_doctor_tools=['t3code'],
            json=True,
        )
        with patch('lib.agent_cli.inspect_agent_tools', return_value=[
            {
                'tool': 't3code',
                'installed': False,
                'path': None,
                'version': None,
                'credential': None,
            }
        ]):
            self.assertEqual(run_agent_command(args), 1)


class TestAgentUpdate(unittest.TestCase):
    @staticmethod
    def _write_tool(path: str, version: str, *, healthy: bool = True) -> None:
        with open(path, 'w', encoding='utf-8') as file_obj:
            file_obj.write(
                '#!/bin/sh\n'
                f'if [ "$1" = "--version" ]; then echo "{version}"; exit 0; fi\n'
                f'if [ "$1" = "--help" ]; then echo "help"; exit {0 if healthy else 1}; fi\n'
                'exit 0\n'
            )
        os.chmod(path, 0o755)

    def test_dry_run_reports_method_without_updating_or_writing_state(self):
        with tempfile.TemporaryDirectory() as home:
            bin_dir = os.path.join(home, '.local', 'bin')
            os.makedirs(bin_dir)
            codex_path = os.path.join(bin_dir, 'codex')
            self._write_tool(codex_path, 'codex 1.0.0')

            with patch('lib.agent_cli._invoke_agent_update') as updater:
                result = update_agent_tools(['codex'], home=home, dry_run=True)

            updater.assert_not_called()
            self.assertEqual(result[0]['status'], 'planned')
            self.assertEqual(result[0]['before_version'], 'codex 1.0.0')
            self.assertFalse(os.path.exists(os.path.join(
                home,
                '.local',
                'state',
                'infra_tools',
                'agent-tools.json',
            )))

    def test_successful_update_records_verified_versions_and_private_state(self):
        with tempfile.TemporaryDirectory() as home:
            bin_dir = os.path.join(home, '.local', 'bin')
            os.makedirs(bin_dir)
            claude_path = os.path.join(bin_dir, 'claude')
            self._write_tool(claude_path, 'claude 1.0.0')

            def update(_tool, path, _home):
                self._write_tool(path, 'claude 2.0.0')
                return {
                    'returncode': 0,
                    'method': 'claude update',
                    'installer_sha256': None,
                }

            with patch('lib.agent_cli._invoke_agent_update', side_effect=update):
                result = update_agent_tools(['claude'], home=home)

            state_path = os.path.join(
                home,
                '.local',
                'state',
                'infra_tools',
                'agent-tools.json',
            )
            with open(state_path, encoding='utf-8') as file_obj:
                state = json.load(file_obj)
            self.assertEqual(result[0]['status'], 'updated')
            self.assertEqual(result[0]['after_version'], 'claude 2.0.0')
            self.assertEqual(state['tools']['claude']['status'], 'updated')
            self.assertEqual(os.stat(state_path).st_mode & 0o777, 0o600)

    def test_interrupted_update_leaves_visible_in_progress_state(self):
        with tempfile.TemporaryDirectory() as home:
            bin_dir = os.path.join(home, '.local', 'bin')
            os.makedirs(bin_dir)
            codex_path = os.path.join(bin_dir, 'codex')
            self._write_tool(codex_path, 'codex 1.0.0')

            with patch('lib.agent_cli._invoke_agent_update', side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    update_agent_tools(['codex'], home=home)

            state_path = os.path.join(
                home,
                '.local',
                'state',
                'infra_tools',
                'agent-tools.json',
            )
            with open(state_path, encoding='utf-8') as file_obj:
                state = json.load(file_obj)
            self.assertEqual(state['tools']['codex']['status'], 'in_progress')

    def test_failed_post_update_smoke_test_restores_previous_executable(self):
        with tempfile.TemporaryDirectory() as home:
            bin_dir = os.path.join(home, '.local', 'bin')
            os.makedirs(bin_dir)
            opencode_path = os.path.join(bin_dir, 'opencode')
            self._write_tool(opencode_path, 'opencode 1.0.0')

            def broken_update(_tool, path, _home):
                self._write_tool(path, 'opencode 2.0.0', healthy=False)
                return {
                    'returncode': 0,
                    'method': 'opencode upgrade',
                    'installer_sha256': None,
                }

            with patch('lib.agent_cli._invoke_agent_update', side_effect=broken_update):
                result = update_agent_tools(['opencode'], home=home)

            self.assertEqual(result[0]['status'], 'failed')
            self.assertEqual(result[0]['failure'], 'post_update_verification')
            self.assertTrue(result[0]['rollback'])
            self.assertEqual(result[0]['after_version'], 'opencode 1.0.0')
            self.assertTrue(os.path.islink(opencode_path))

    def test_system_managed_executable_is_not_mutated(self):
        with tempfile.TemporaryDirectory() as home:
            with (
                patch('lib.agent_cli._tool_path', return_value='/usr/bin/claude'),
                patch('lib.agent_cli._tool_version', return_value='claude 1.0.0'),
                patch('lib.agent_cli._invoke_agent_update') as updater,
            ):
                result = update_agent_tools(['claude'], home=home)

            updater.assert_not_called()
            self.assertEqual(result[0]['failure'], 'not_user_managed')

    def test_corrupt_state_stops_before_mutating_tools(self):
        with tempfile.TemporaryDirectory() as home:
            bin_dir = os.path.join(home, '.local', 'bin')
            state_dir = os.path.join(home, '.local', 'state', 'infra_tools')
            os.makedirs(bin_dir)
            os.makedirs(state_dir)
            self._write_tool(os.path.join(bin_dir, 'codex'), 'codex 1.0.0')
            with open(os.path.join(state_dir, 'agent-tools.json'), 'w', encoding='utf-8') as file_obj:
                file_obj.write('not-json')

            with patch('lib.agent_cli._invoke_agent_update') as updater:
                with self.assertRaisesRegex(RuntimeError, 'Cannot read agent update state'):
                    update_agent_tools(['codex'], home=home)

            updater.assert_not_called()

    def test_codex_installer_download_records_digest_and_private_mode(self):
        payload = b'#!/bin/sh\necho installer\n'
        with tempfile.TemporaryDirectory() as directory:
            with patch('lib.agent_cli.urllib.request.urlopen', return_value=io.BytesIO(payload)):
                path, digest = _download_codex_installer(directory)
            try:
                with open(path, 'rb') as file_obj:
                    self.assertEqual(file_obj.read(), payload)
                self.assertEqual(digest, hashlib.sha256(payload).hexdigest())
                self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            finally:
                os.unlink(path)

    def test_codex_installer_download_enforces_size_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch('lib.agent_cli._MAX_INSTALLER_BYTES', 3),
                patch('lib.agent_cli.urllib.request.urlopen', return_value=io.BytesIO(b'1234')),
            ):
                with self.assertRaisesRegex(RuntimeError, 'size limit'):
                    _download_codex_installer(directory)
            self.assertEqual(os.listdir(directory), [])

    def test_interrupted_codex_download_removes_partial_installer(self):
        class InterruptedResponse(io.BytesIO):
            def read(self, size: int = -1) -> bytes:
                if self.tell() > 0:
                    raise OSError('connection reset')
                return super().read(1)

        with tempfile.TemporaryDirectory() as directory:
            response = InterruptedResponse(b'partial')
            with patch('lib.agent_cli.urllib.request.urlopen', return_value=response):
                with self.assertRaisesRegex(OSError, 'connection reset'):
                    _download_codex_installer(directory)
            self.assertEqual(os.listdir(directory), [])

    def test_native_updaters_use_vendor_subcommands_without_a_shell(self):
        completed = type('Completed', (), {'returncode': 0})()
        cases = (
            ('claude', ['/home/agent/.local/bin/claude', 'update']),
            ('opencode', ['/home/agent/.opencode/bin/opencode', 'upgrade']),
        )
        for tool, expected in cases:
            with self.subTest(tool=tool):
                with patch('lib.agent_cli.subprocess.run', return_value=completed) as runner:
                    result = _invoke_agent_update(tool, expected[0], '/home/agent')
                self.assertEqual(runner.call_args.args[0], expected)
                self.assertNotIn('shell', runner.call_args.kwargs)
                self.assertEqual(result['returncode'], 0)


class TestAgentPayloadInstallation(unittest.TestCase):
    def test_copied_credentials_are_removed_from_uploaded_payload(self):
        config = SetupConfig(
            host='host',
            username='agent',
            system_type='server_dev',
            install_codex=True,
            copy_agent_keys=True,
        )
        with tempfile.TemporaryDirectory() as directory:
            payload_dir = os.path.join(directory, 'payload')
            home = os.path.join(directory, 'home')
            source = os.path.join(payload_dir, 'secrets', 'codex', 'auth.json')
            os.makedirs(os.path.dirname(source))
            os.makedirs(home)
            with open(source, 'w', encoding='utf-8') as file_obj:
                file_obj.write('{"token":"secret"}\n')

            with (
                patch('common.agent_steps.REMOTE_AGENT_PAYLOAD_DIR', payload_dir),
                patch('common.agent_steps._user_home', return_value=home),
                patch('common.agent_steps._chown_path'),
            ):
                copy_agent_tooling_payload(config)

            destination = os.path.join(home, '.codex', 'auth.json')
            self.assertTrue(os.path.isfile(destination))
            self.assertEqual(os.stat(destination).st_mode & 0o777, 0o600)
            self.assertFalse(os.path.exists(payload_dir))

    def test_secret_copy_rejects_symlinked_destination(self):
        config = SetupConfig(
            host='host',
            username='agent',
            system_type='server_dev',
        )
        with tempfile.TemporaryDirectory() as directory:
            source = os.path.join(directory, 'auth.json')
            outside = os.path.join(directory, 'outside.json')
            home = os.path.join(directory, 'home')
            os.makedirs(home)
            with open(source, 'w', encoding='utf-8') as file_obj:
                file_obj.write('secret')
            with open(outside, 'w', encoding='utf-8') as file_obj:
                file_obj.write('untouched')
            os.symlink(directory, os.path.join(home, '.codex'))

            with self.assertRaisesRegex(RuntimeError, 'symlinked agent destination'):
                _copy_secret_file(
                    config,
                    source,
                    os.path.join(home, '.codex', 'auth.json'),
                    'Codex',
                )

            with open(outside, encoding='utf-8') as file_obj:
                self.assertEqual(file_obj.read(), 'untouched')

    def test_uploaded_repository_cache_is_retained_and_root_only(self):
        config = SetupConfig(
            host='host',
            username='agent',
            system_type='server_dev',
        )
        with tempfile.TemporaryDirectory() as directory:
            staged = os.path.join(directory, 'staged')
            cache = os.path.join(directory, 'cache', 'agent_repos')
            home = os.path.join(directory, 'home')
            source = os.path.join(staged, 'repo', '.git')
            os.makedirs(source)
            os.makedirs(home)
            with open(os.path.join(source, 'config'), 'w', encoding='utf-8') as file_obj:
                file_obj.write('[remote "origin"]\nurl = git@github.com:user/repo.git\n')

            with (
                patch('common.agent_steps.REMOTE_AGENT_REPOS_DIR', staged),
                patch('common.agent_steps.AGENT_REPOS_CACHE_DIR', cache),
                patch('common.agent_steps._user_home', return_value=home),
                patch('common.agent_steps._chown_path'),
            ):
                install_agent_repositories(config)

            self.assertTrue(os.path.exists(os.path.join(home, 'repos', 'repo', '.git', 'config')))
            self.assertTrue(os.path.exists(os.path.join(cache, 'repo', '.git', 'config')))
            self.assertEqual(os.stat(cache).st_mode & 0o777, 0o700)
            self.assertTrue(os.path.isdir(staged))

    def test_payload_is_removed_when_copying_fails(self):
        config = SetupConfig(
            host='host',
            username='agent',
            system_type='server_dev',
            install_codex=True,
            copy_agent_keys=True,
        )
        with tempfile.TemporaryDirectory() as directory:
            payload_dir = os.path.join(directory, 'payload')
            home = os.path.join(directory, 'home')
            os.makedirs(payload_dir)
            os.makedirs(home)
            with (
                patch('common.agent_steps.REMOTE_AGENT_PAYLOAD_DIR', payload_dir),
                patch('common.agent_steps._user_home', return_value=home),
                patch('common.agent_steps._copy_secret_file', side_effect=OSError('copy failed')),
            ):
                with self.assertRaisesRegex(OSError, 'copy failed'):
                    copy_agent_tooling_payload(config)

            self.assertFalse(os.path.exists(payload_dir))


if __name__ == '__main__':
    unittest.main()
