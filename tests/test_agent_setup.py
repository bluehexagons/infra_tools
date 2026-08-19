"""Tests for agent VM repository/config payload preparation."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.config import SetupConfig
from lib.setup_common import prepare_agent_payload


class TestAgentPayloadPreparation(unittest.TestCase):
    def test_stages_selected_config_and_credentials(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as payload_dir:
            opencode_skill_dir = os.path.join(home, '.config', 'opencode', 'skills', 'review')
            os.makedirs(opencode_skill_dir)
            with open(os.path.join(opencode_skill_dir, 'SKILL.md'), 'w', encoding='utf-8') as file_obj:
                file_obj.write('---\nname: review\ndescription: Review code\n---\n')

            opencode_auth_dir = os.path.join(home, '.local', 'share', 'opencode')
            os.makedirs(opencode_auth_dir)
            with open(os.path.join(opencode_auth_dir, 'auth.json'), 'w', encoding='utf-8') as file_obj:
                file_obj.write('{"token":"secret"}\n')
            os.chmod(os.path.join(opencode_auth_dir, 'auth.json'), 0o600)

            codex_dir = os.path.join(home, '.codex')
            os.makedirs(os.path.join(codex_dir, 'skills', 'review'))
            with open(os.path.join(codex_dir, 'config.toml'), 'w', encoding='utf-8') as file_obj:
                file_obj.write('model = "test"\n')
            with open(os.path.join(codex_dir, 'auth.json'), 'w', encoding='utf-8') as file_obj:
                file_obj.write('{"token":"secret"}\n')
            os.chmod(os.path.join(codex_dir, 'auth.json'), 0o600)

            claude_dir = os.path.join(home, '.claude')
            os.makedirs(os.path.join(claude_dir, 'commands'))
            with open(os.path.join(claude_dir, 'settings.json'), 'w', encoding='utf-8') as file_obj:
                file_obj.write('{}\n')
            with open(os.path.join(claude_dir, '.credentials.json'), 'w', encoding='utf-8') as file_obj:
                file_obj.write('{"token":"secret"}\n')
            os.chmod(os.path.join(claude_dir, '.credentials.json'), 0o600)

            gh_config_dir = os.path.join(home, '.config', 'gh')
            os.makedirs(gh_config_dir)
            with open(os.path.join(gh_config_dir, 'config.yml'), 'w', encoding='utf-8') as file_obj:
                file_obj.write('editor: nvim\n')
            with open(os.path.join(gh_config_dir, 'hosts.yml'), 'w', encoding='utf-8') as file_obj:
                file_obj.write('github.com:\n  oauth_token: secret\n')
            os.chmod(os.path.join(gh_config_dir, 'hosts.yml'), 0o600)

            config = SetupConfig(
                host='10.0.0.10',
                username='agentuser',
                system_type='server_dev',
                install_gh=True,
                install_codex=True,
                install_claude=True,
                install_opencode=True,
                git_auth_source='active',
                agent_auth_source='active',
                copy_agent_config=True,
                copy_agent_keys=True,
            )

            with patch.dict(os.environ, {'HOME': home, 'SUDO_USER': ''}):
                prepare_agent_payload(config, payload_dir)

            self.assertTrue(os.path.exists(
                os.path.join(payload_dir, 'config', 'opencode', 'skills', 'review', 'SKILL.md')
            ))
            self.assertTrue(os.path.exists(
                os.path.join(payload_dir, 'config', 'codex', 'config.toml')
            ))
            self.assertFalse(os.path.exists(
                os.path.join(payload_dir, 'config', 'codex', 'auth.json')
            ))
            self.assertTrue(os.path.exists(
                os.path.join(payload_dir, 'secrets', 'codex', 'auth.json')
            ))
            self.assertTrue(os.path.exists(
                os.path.join(payload_dir, 'config', 'claude', 'settings.json')
            ))
            self.assertFalse(os.path.exists(
                os.path.join(payload_dir, 'config', 'claude', '.credentials.json')
            ))
            self.assertTrue(os.path.exists(
                os.path.join(payload_dir, 'secrets', 'claude', '.credentials.json')
            ))
            self.assertTrue(os.path.exists(
                os.path.join(payload_dir, 'secrets', 'opencode', 'auth.json')
            ))
            self.assertTrue(os.path.exists(
                os.path.join(payload_dir, 'config', 'gh', 'config.yml')
            ))
            self.assertFalse(os.path.exists(
                os.path.join(payload_dir, 'config', 'gh', 'hosts.yml')
            ))
            self.assertTrue(os.path.exists(
                os.path.join(payload_dir, 'secrets', 'gh', 'hosts.yml')
            ))


if __name__ == '__main__':
    unittest.main()
