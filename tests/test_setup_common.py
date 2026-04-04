"""Tests for lib/setup_common.py: setup_main timing/status persistence."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.config import SetupConfig


def _make_config(**kwargs) -> SetupConfig:
    defaults = dict(host='testhost', username='testuser', system_type='server_lite')
    defaults.update(kwargs)
    return SetupConfig(**defaults)


class TestSetupMainTimingPersistence(unittest.TestCase):
    """Verify setup_main always saves last_start_time/end_time/success."""

    def test_success_saves_timing_and_success_true(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from lib import setup_common
            config = _make_config()
            saved_calls = []

            def fake_save(cfg, start_time=None, end_time=None, success=None):
                saved_calls.append({'start_time': start_time, 'end_time': end_time, 'success': success})

            with patch('lib.cache.SETUP_CACHE_DIR', tmpdir), \
                 patch.object(setup_common, 'run_remote_setup', return_value=0), \
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
                args.dry_run = False
                parser.parse_args.return_value = args

                with patch.object(setup_common, 'create_argument_parser', return_value=parser), \
                     patch('lib.config.SetupConfig.from_args', return_value=config):
                    setup_common.setup_main('server_lite', 'Test', lambda c: None)

            # Two saves expected: first is the pre-run config-only save (no timing),
            # second is the post-run save with start_time/end_time/success.
            self.assertEqual(len(saved_calls), 2)
            post_run = saved_calls[1]
            self.assertIsNotNone(post_run['start_time'])
            self.assertIsNotNone(post_run['end_time'])
            self.assertIs(post_run['success'], True)

    def test_failure_saves_timing_and_success_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from lib import setup_common
            config = _make_config()
            saved_calls = []

            def fake_save(cfg, start_time=None, end_time=None, success=None):
                saved_calls.append({'start_time': start_time, 'end_time': end_time, 'success': success})

            with patch('lib.cache.SETUP_CACHE_DIR', tmpdir), \
                 patch.object(setup_common, 'run_remote_setup', return_value=1), \
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

    def test_exception_saves_timing_and_success_false(self):
        """Verifies that even if run_remote_setup raises, success=False is saved."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from lib import setup_common
            config = _make_config()
            saved_calls = []

            def fake_save(cfg, start_time=None, end_time=None, success=None):
                saved_calls.append({'start_time': start_time, 'end_time': end_time, 'success': success})

            with patch('lib.cache.SETUP_CACHE_DIR', tmpdir), \
                 patch.object(setup_common, 'run_remote_setup', side_effect=RuntimeError('boom')), \
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

    def test_dry_run_skips_post_run_save(self):
        """In dry-run mode, save_setup_command should never be called."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from lib import setup_common
            config = _make_config(dry_run=True)
            saved_calls = []

            def fake_save(cfg, start_time=None, end_time=None, success=None):
                saved_calls.append({'start_time': start_time, 'end_time': end_time, 'success': success})

            with patch('lib.cache.SETUP_CACHE_DIR', tmpdir), \
                 patch.object(setup_common, 'run_remote_setup', return_value=0), \
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


if __name__ == '__main__':
    unittest.main()
