"""Tests for lib/machine_state.py: machine state checks with mocked state files."""

from __future__ import annotations

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
                ms.save_setup_config({'timezone': 'UTC', 'username': 'test',
                                      'host': '10.0.0.1', 'system_type': 'server_lite'})
                loaded = ms.load_setup_config()
                assert loaded is not None
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


class TestMachineStateValidation(unittest.TestCase):
    """Test structural validation of loaded machine state."""

    def _write_state(self, tmpdir, data):
        state_file = os.path.join(tmpdir, 'machine.json')
        import json
        with open(state_file, 'w') as f:
            json.dump(data, f)
        return state_file

    def test_valid_state_passes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = self._write_state(tmpdir, {
                'machine_type': 'vm', 'system_type': 'server_dev', 'username': 'admin'
            })
            with patch.object(ms, 'STATE_FILE', state_file):
                state = ms.load_machine_state()
                self.assertEqual(state['machine_type'], 'vm')

    def test_missing_required_key_returns_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Missing 'username'
            state_file = self._write_state(tmpdir, {
                'machine_type': 'vm', 'system_type': 'server_dev'
            })
            with patch.object(ms, 'STATE_FILE', state_file):
                state = ms.load_machine_state()
                self.assertEqual(state['machine_type'], 'unprivileged')
                self.assertIsNone(state['username'])

    def test_unknown_machine_type_returns_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = self._write_state(tmpdir, {
                'machine_type': 'quantum_computer', 'system_type': 'server_dev', 'username': 'test'
            })
            with patch.object(ms, 'STATE_FILE', state_file):
                state = ms.load_machine_state()
                self.assertEqual(state['machine_type'], 'unprivileged')

    def test_json_list_instead_of_dict_returns_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = self._write_state(tmpdir, ["not", "a", "dict"])
            with patch.object(ms, 'STATE_FILE', state_file):
                state = ms.load_machine_state()
                self.assertEqual(state['machine_type'], 'unprivileged')

    def test_null_machine_type_accepted(self):
        """machine_type=None is accepted (edge case for partial state)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = self._write_state(tmpdir, {
                'machine_type': None, 'system_type': None, 'username': None
            })
            with patch.object(ms, 'STATE_FILE', state_file):
                state = ms.load_machine_state()
                self.assertIsNone(state['machine_type'])

    def test_extra_keys_preserved(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = self._write_state(tmpdir, {
                'machine_type': 'hardware', 'system_type': 'server_web',
                'username': 'root', 'gpu': True, 'custom_flag': 42
            })
            with patch.object(ms, 'STATE_FILE', state_file):
                state = ms.load_machine_state()
                self.assertTrue(state['gpu'])
                self.assertEqual(state['custom_flag'], 42)


class TestSetupConfigValidation(unittest.TestCase):
    """Test structural validation of loaded setup config."""

    def _write_config(self, tmpdir, data):
        config_file = os.path.join(tmpdir, 'setup.json')
        import json
        with open(config_file, 'w') as f:
            json.dump(data, f)
        return config_file

    def test_valid_config_passes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = self._write_config(tmpdir, {
                'host': '10.0.0.1', 'username': 'admin', 'system_type': 'server_lite'
            })
            with patch.object(ms, 'SETUP_CONFIG_FILE', config_file):
                config = ms.load_setup_config()
                assert config is not None
                self.assertEqual(config['host'], '10.0.0.1')

    def test_missing_required_key_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Missing 'username' (required for runtime operations)
            config_file = self._write_config(tmpdir, {
                'system_type': 'server_lite'
            })
            with patch.object(ms, 'SETUP_CONFIG_FILE', config_file):
                self.assertIsNone(ms.load_setup_config())

    def test_unknown_system_type_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = self._write_config(tmpdir, {
                'host': '10.0.0.1', 'username': 'admin', 'system_type': 'moon_base'
            })
            with patch.object(ms, 'SETUP_CONFIG_FILE', config_file):
                self.assertIsNone(ms.load_setup_config())

    def test_unknown_machine_type_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = self._write_config(tmpdir, {
                'host': '10.0.0.1', 'username': 'admin',
                'system_type': 'server_lite', 'machine_type': 'invalid'
            })
            with patch.object(ms, 'SETUP_CONFIG_FILE', config_file):
                self.assertIsNone(ms.load_setup_config())

    def test_json_list_instead_of_dict_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = self._write_config(tmpdir, [1, 2, 3])
            with patch.object(ms, 'SETUP_CONFIG_FILE', config_file):
                self.assertIsNone(ms.load_setup_config())

    def test_valid_machine_type_in_config_accepted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = self._write_config(tmpdir, {
                'host': '10.0.0.1', 'username': 'admin',
                'system_type': 'server_lite', 'machine_type': 'vm'
            })
            with patch.object(ms, 'SETUP_CONFIG_FILE', config_file):
                config = ms.load_setup_config()
                assert config is not None
                self.assertEqual(config['machine_type'], 'vm')

    def test_no_machine_type_key_accepted(self):
        """Config without machine_type is valid (it's optional)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = self._write_config(tmpdir, {
                'host': '10.0.0.1', 'username': 'admin', 'system_type': 'server_dev'
            })
            with patch.object(ms, 'SETUP_CONFIG_FILE', config_file):
                config = ms.load_setup_config()
                assert config is not None
                self.assertNotIn('machine_type', config)


if __name__ == '__main__':
    unittest.main()
