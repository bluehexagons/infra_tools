"""Tests for lib/machine_state.py: machine state checks with mocked state files."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import lib.machine_state as ms


class TestMachineStateHelpers(unittest.TestCase):
    """Test machine type helper functions by mocking load_machine_state."""

    def _patch_machine_type(self, machine_type):
        return patch.object(ms, 'load_machine_state', return_value={
            'machine_type': machine_type,
            'system_type': 'server_lite',
            'username': 'test',
        })

    def test_is_unprivileged(self):
        with self._patch_machine_type('unprivileged'):
            self.assertTrue(ms.is_unprivileged())
            self.assertTrue(ms.is_container())
            self.assertFalse(ms.can_modify_kernel())
            self.assertFalse(ms.can_manage_swap())

    def test_is_oci(self):
        with self._patch_machine_type('oci'):
            self.assertTrue(ms.is_oci())
            self.assertTrue(ms.is_container())
            self.assertFalse(ms.can_restart_system())

    def test_is_vm(self):
        with self._patch_machine_type('vm'):
            self.assertTrue(ms.is_vm())
            self.assertFalse(ms.is_container())
            self.assertTrue(ms.can_modify_kernel())
            self.assertTrue(ms.can_manage_swap())
            self.assertTrue(ms.can_manage_firewall())
            self.assertTrue(ms.can_manage_time_sync())
            self.assertTrue(ms.has_gpu_access())

    def test_is_privileged(self):
        with self._patch_machine_type('privileged'):
            self.assertTrue(ms.is_privileged_container())
            self.assertFalse(ms.is_container())
            self.assertTrue(ms.can_modify_kernel())

    def test_is_hardware(self):
        with self._patch_machine_type('hardware'):
            self.assertTrue(ms.is_hardware())
            self.assertFalse(ms.is_container())
            self.assertTrue(ms.can_modify_kernel())
            self.assertTrue(ms.can_restart_system())

    def test_can_restart_system_not_oci(self):
        for mt in ('unprivileged', 'vm', 'privileged', 'hardware'):
            with self._patch_machine_type(mt):
                self.assertTrue(ms.can_restart_system(), f"Expected can_restart_system=True for {mt}")


class TestSaveLoadMachineState(unittest.TestCase):
    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = os.path.join(tmpdir, 'machine.json')
            with patch.object(ms, 'STATE_DIR', tmpdir), \
                 patch.object(ms, 'STATE_FILE', state_file):
                ms.save_machine_state('vm', 'server_dev', 'testuser')
                state = ms.load_machine_state()
                self.assertEqual(state['machine_type'], 'vm')
                self.assertEqual(state['system_type'], 'server_dev')
                self.assertEqual(state['username'], 'testuser')

    def test_load_missing_file_returns_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = os.path.join(tmpdir, 'nonexistent.json')
            with patch.object(ms, 'STATE_FILE', state_file):
                state = ms.load_machine_state()
                self.assertEqual(state['machine_type'], 'unprivileged')
                self.assertIsNone(state['system_type'])

    def test_load_corrupt_file_returns_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = os.path.join(tmpdir, 'corrupt.json')
            with open(state_file, 'w') as f:
                f.write('not valid json')
            with patch.object(ms, 'STATE_FILE', state_file):
                state = ms.load_machine_state()
                self.assertEqual(state['machine_type'], 'unprivileged')

    def test_save_with_extra_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = os.path.join(tmpdir, 'machine.json')
            with patch.object(ms, 'STATE_DIR', tmpdir), \
                 patch.object(ms, 'STATE_FILE', state_file):
                ms.save_machine_state('hardware', 'server_web', 'admin', extra_data={'gpu': True})
                state = ms.load_machine_state()
                self.assertTrue(state.get('gpu'))


class TestSaveLoadSetupConfig(unittest.TestCase):
    def test_save_and_load_setup_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = os.path.join(tmpdir, 'setup.json')
            with patch.object(ms, 'STATE_DIR', tmpdir), \
                 patch.object(ms, 'SETUP_CONFIG_FILE', config_file):
                ms.save_setup_config({'timezone': 'UTC', 'username': 'test'})
                loaded = ms.load_setup_config()
                self.assertIsNotNone(loaded)
                self.assertEqual(loaded['timezone'], 'UTC')

    def test_load_missing_setup_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = os.path.join(tmpdir, 'no_such.json')
            with patch.object(ms, 'SETUP_CONFIG_FILE', config_file):
                self.assertIsNone(ms.load_setup_config())

    def test_load_corrupt_setup_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = os.path.join(tmpdir, 'bad.json')
            with open(config_file, 'w') as f:
                f.write('{broken')
            with patch.object(ms, 'SETUP_CONFIG_FILE', config_file):
                self.assertIsNone(ms.load_setup_config())


if __name__ == '__main__':
    unittest.main()
