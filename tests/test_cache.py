"""Tests for lib/cache.py: setup command caching, loading, and merging."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.cache import (
    get_cache_path_for_host,
    save_setup_command,
    load_setup_command,
    merge_setup_configs,
)
from lib.config import SetupConfig


class TestGetCachePathForHost(unittest.TestCase):
    def test_returns_json_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('lib.cache.SETUP_CACHE_DIR', tmpdir):
                path = get_cache_path_for_host('myhost')
                self.assertTrue(path.endswith('.json'))
                self.assertIn('myhost', path)

    def test_normalizes_host(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('lib.cache.SETUP_CACHE_DIR', tmpdir):
                path1 = get_cache_path_for_host('MyHost.')
                path2 = get_cache_path_for_host('myhost')
                self.assertEqual(path1, path2)

    def test_safe_chars_in_filename(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('lib.cache.SETUP_CACHE_DIR', tmpdir):
                path = get_cache_path_for_host('host with spaces!')
                basename = os.path.basename(path)
                # Should not contain spaces or special chars
                self.assertNotIn(' ', basename)
                self.assertNotIn('!', basename)


class TestSaveAndLoadSetupCommand(unittest.TestCase):
    def _make_config(self, **kwargs):
        defaults = dict(host='testhost', username='testuser', system_type='server_lite')
        defaults.update(kwargs)
        return SetupConfig(**defaults)

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('lib.cache.SETUP_CACHE_DIR', tmpdir):
                config = self._make_config(timezone='America/New_York')
                save_setup_command(config)
                loaded = load_setup_command('testhost')
                self.assertIsNotNone(loaded)
                self.assertEqual(loaded.host, 'testhost')
                self.assertEqual(loaded.system_type, 'server_lite')
                self.assertEqual(loaded.timezone, 'America/New_York')

    def test_load_nonexistent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('lib.cache.SETUP_CACHE_DIR', tmpdir):
                loaded = load_setup_command('nonexistent')
                self.assertIsNone(loaded)

    def test_save_with_name_and_tags(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('lib.cache.SETUP_CACHE_DIR', tmpdir):
                config = self._make_config(friendly_name='My Server', tags=['web', 'prod'])
                save_setup_command(config)
                loaded = load_setup_command('testhost')
                self.assertEqual(loaded.friendly_name, 'My Server')
                self.assertEqual(loaded.tags, ['web', 'prod'])


class TestMergeSetupConfigs(unittest.TestCase):
    def _make_config(self, **kwargs):
        defaults = dict(host='testhost', username='testuser', system_type='server_lite')
        defaults.update(kwargs)
        return SetupConfig(**defaults)

    def test_basic_merge(self):
        cached = self._make_config(timezone='UTC')
        new = self._make_config(timezone='America/New_York')
        merged = merge_setup_configs(cached, new)
        self.assertEqual(merged.timezone, 'America/New_York')

    def test_none_values_not_overwritten(self):
        cached = self._make_config(timezone='America/New_York')
        new = self._make_config(timezone=None)
        merged = merge_setup_configs(cached, new)
        # None should not overwrite existing value
        self.assertEqual(merged.timezone, 'America/New_York')

    def test_deploy_specs_merge_no_duplicates(self):
        cached = self._make_config(deploy_specs=[['example.com/', 'https://git.com/repo1']])
        new = self._make_config(deploy_specs=[['example.com/', 'https://git.com/repo1'], ['other.com/', 'https://git.com/repo2']])
        merged = merge_setup_configs(cached, new)
        self.assertEqual(len(merged.deploy_specs), 2)

    def test_samba_shares_merge(self):
        cached = self._make_config(samba_shares=[['read', 'share1', '/mnt/data', 'u:p']])
        new = self._make_config(samba_shares=[['write', 'share2', '/mnt/docs', 'u:p']])
        merged = merge_setup_configs(cached, new)
        self.assertEqual(len(merged.samba_shares), 2)

    def test_tags_overwritten(self):
        cached = self._make_config(tags=['old'])
        new = self._make_config(tags=['new1', 'new2'])
        merged = merge_setup_configs(cached, new)
        self.assertEqual(merged.tags, ['new1', 'new2'])

    def test_host_system_type_preserved(self):
        cached = self._make_config(host='host1', system_type='server_lite')
        new = self._make_config(host='host2', system_type='server_web')
        merged = merge_setup_configs(cached, new)
        self.assertEqual(merged.host, 'host1')
        self.assertEqual(merged.system_type, 'server_lite')


if __name__ == '__main__':
    unittest.main()
