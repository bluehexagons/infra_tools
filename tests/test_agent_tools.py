"""Tests for agent installer metadata, verification, and local diagnostics."""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from common.agent_steps import (
    _download_verified_file,
    _latest_t3code_asset,
    copy_agent_tooling_payload,
    install_claude,
    install_codex,
    install_opencode,
    install_t3code,
)
from lib.agent_cli import inspect_agent_tools, run_agent_command
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
            os.makedirs(payload_dir)
            with (
                patch('common.agent_steps.REMOTE_AGENT_PAYLOAD_DIR', payload_dir),
                patch('common.agent_steps._copy_secret_file', side_effect=OSError('copy failed')),
            ):
                with self.assertRaisesRegex(OSError, 'copy failed'):
                    copy_agent_tooling_payload(config)

            self.assertFalse(os.path.exists(payload_dir))


if __name__ == '__main__':
    unittest.main()
