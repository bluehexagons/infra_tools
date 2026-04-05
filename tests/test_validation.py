"""Tests for lib/validation.py: validate_directory_empty, validate_network_endpoint, validate_positive_integer."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.validation import (
    validate_deploy_specs,
    validate_deploy_targets,
    validate_directory_empty,
    validate_scrub_specs,
    validate_sync_specs,
    validate_network_endpoint,
    validate_positive_integer,
    validate_memory_string,
    validate_package_name,
    validate_hosted_flags,
    validate_workspace_dir,
)


class TestValidateDirectoryEmpty(unittest.TestCase):
    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            validate_directory_empty(tmpdir)  # should not raise

    def test_non_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, 'file.txt'), 'w') as f:
                f.write('content')
            with self.assertRaises(ValueError):
                validate_directory_empty(tmpdir)

    def test_hidden_files_ignored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, '.hidden'), 'w') as f:
                f.write('hidden')
            validate_directory_empty(tmpdir)  # hidden files should not count

    def test_not_a_directory(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name
        try:
            with self.assertRaises(ValueError):
                validate_directory_empty(path)
        finally:
            os.unlink(path)

    def test_nonexistent_directory(self):
        with self.assertRaises(ValueError):
            validate_directory_empty('/nonexistent/path/xyz')


class TestValidateNetworkEndpoint(unittest.TestCase):
    def test_valid_ip_port(self):
        validate_network_endpoint('192.168.1.1:8080')  # should not raise

    def test_valid_hostname_port(self):
        validate_network_endpoint('example.com:443')  # should not raise

    def test_empty_endpoint(self):
        with self.assertRaises(ValueError):
            validate_network_endpoint('')

    def test_missing_port(self):
        with self.assertRaises(ValueError):
            validate_network_endpoint('192.168.1.1')

    def test_port_out_of_range_high(self):
        with self.assertRaises(ValueError):
            validate_network_endpoint('192.168.1.1:70000')

    def test_port_out_of_range_zero(self):
        with self.assertRaises(ValueError):
            validate_network_endpoint('192.168.1.1:0')

    def test_invalid_host(self):
        with self.assertRaises(ValueError):
            validate_network_endpoint('-invalid:80')

    def test_non_numeric_port(self):
        with self.assertRaises(ValueError):
            validate_network_endpoint('host:abc')

    def test_multiple_colons(self):
        with self.assertRaises(ValueError):
            validate_network_endpoint('host:80:90')


class TestValidateDeployTargets(unittest.TestCase):
    def test_none_passes(self):
        validate_deploy_targets(None)

    def test_valid_targets_pass(self):
        validate_deploy_targets(['app1.example.com', '192.168.1.20'])

    def test_empty_target_fails(self):
        with self.assertRaisesRegex(ValueError, "Deploy target must be a non-empty hostname or IP"):
            validate_deploy_targets([''])

    def test_invalid_target_fails(self):
        with self.assertRaisesRegex(ValueError, "Invalid deploy target host: bad target"):
            validate_deploy_targets(['bad target'])


class TestValidateDeploySpecs(unittest.TestCase):
    def test_none_passes(self):
        validate_deploy_specs(None)

    def test_valid_domain_and_path_specs_pass(self):
        validate_deploy_specs([
            ['example.com/blog,/srv/www/app', 'https://github.com/user/repo.git'],
        ])

    def test_invalid_domain_fails(self):
        with self.assertRaisesRegex(ValueError, "Invalid deploy domain: bad domain"):
            validate_deploy_specs([['bad domain', 'https://github.com/user/repo.git']])

    def test_empty_git_url_fails(self):
        with self.assertRaisesRegex(ValueError, "Deploy git URL must be a non-empty string"):
            validate_deploy_specs([['example.com', '']])

    def test_empty_deploy_spec_entry_fails(self):
        with self.assertRaisesRegex(ValueError, "Deploy target spec list must not contain empty entries"):
            validate_deploy_specs([['example.com,,other.example.com', 'https://github.com/user/repo.git']])


class TestValidateSyncSpecs(unittest.TestCase):
    def test_none_passes(self):
        validate_sync_specs(None)

    def test_valid_sync_specs_pass(self):
        validate_sync_specs([['/src', '/dst', 'daily']])

    def test_relative_source_fails(self):
        with self.assertRaisesRegex(ValueError, "Source path must be absolute: relative"):
            validate_sync_specs([['relative', '/dst', 'daily']])

    def test_invalid_frequency_fails(self):
        with self.assertRaisesRegex(ValueError, "Invalid interval 'yearly'"):
            validate_sync_specs([['/src', '/dst', 'yearly']])


class TestValidateScrubSpecs(unittest.TestCase):
    def test_none_passes(self):
        validate_scrub_specs(None)

    def test_valid_scrub_specs_pass(self):
        validate_scrub_specs([['/data', '.pardatabase', '5%', 'weekly']])

    def test_relative_directory_fails(self):
        with self.assertRaisesRegex(ValueError, "Directory path must be absolute: relative"):
            validate_scrub_specs([['relative', '.pardatabase', '5%', 'weekly']])

    def test_invalid_redundancy_fails(self):
        with self.assertRaisesRegex(ValueError, "Redundancy percentage must be between 1 and 100: 0%"):
            validate_scrub_specs([['/data', '.pardatabase', '0%', 'weekly']])


class TestValidateWorkspaceDir(unittest.TestCase):
    def test_existing_workspace_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            validate_workspace_dir(tmpdir)

    def test_new_nested_workspace_directory_uses_existing_parent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            validate_workspace_dir(os.path.join(tmpdir, 'nested', 'workspace'))

    def test_workspace_path_rejects_existing_file(self):
        with tempfile.NamedTemporaryFile(delete=False) as tmpfile:
            path = tmpfile.name
        try:
            with self.assertRaises(ValueError):
                validate_workspace_dir(path)
        finally:
            os.unlink(path)


class TestValidatePositiveInteger(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(validate_positive_integer('42'), 42)

    def test_valid_with_spaces(self):
        self.assertEqual(validate_positive_integer('  7  '), 7)

    def test_zero_not_positive(self):
        with self.assertRaises(ValueError):
            validate_positive_integer('0')

    def test_negative(self):
        with self.assertRaises(ValueError):
            validate_positive_integer('-5')

    def test_empty(self):
        with self.assertRaises(ValueError):
            validate_positive_integer('')

    def test_non_numeric(self):
        with self.assertRaises(ValueError):
            validate_positive_integer('abc')

    def test_custom_name_in_error(self):
        with self.assertRaises(ValueError) as ctx:
            validate_positive_integer('0', name='count')
        self.assertIn('count', str(ctx.exception))


class TestValidateMemoryString(unittest.TestCase):
    def test_valid_gigabytes(self):
        validate_memory_string('2G')  # should not raise

    def test_valid_megabytes(self):
        validate_memory_string('512M')  # should not raise

    def test_valid_kilobytes(self):
        validate_memory_string('1024K')  # should not raise

    def test_valid_terabytes(self):
        validate_memory_string('1T')  # should not raise

    def test_case_insensitive(self):
        validate_memory_string('2g')  # should not raise

    def test_invalid_suffix(self):
        with self.assertRaises(ValueError):
            validate_memory_string('2GB')

    def test_no_suffix(self):
        with self.assertRaises(ValueError):
            validate_memory_string('512')

    def test_empty_string(self):
        with self.assertRaises(ValueError):
            validate_memory_string('')

    def test_letters_only(self):
        with self.assertRaises(ValueError):
            validate_memory_string('abc')

    def test_custom_name_in_error(self):
        with self.assertRaises(ValueError) as ctx:
            validate_memory_string('bad', name='--storage')
        self.assertIn('--storage', str(ctx.exception))


class TestValidatePackageName(unittest.TestCase):
    def test_valid_package_name(self):
        self.assertEqual(validate_package_name('python3-venv'), 'python3-venv')

    def test_valid_package_name_with_plus(self):
        self.assertEqual(validate_package_name('libgtk-3-0t64+extra'), 'libgtk-3-0t64+extra')

    def test_empty_package_name(self):
        with self.assertRaises(ValueError):
            validate_package_name('')

    def test_invalid_package_name(self):
        with self.assertRaises(ValueError):
            validate_package_name('python3; rm -rf /')


class _MockConfig:
    """Minimal mock for SetupConfig used by validate_hosted_flags."""
    def __init__(self, **kwargs):
        self.hosted_node = kwargs.get('hosted_node')
        self.container_memory = kwargs.get('container_memory')
        self.container_storage = kwargs.get('container_storage')
        self.container_cores = kwargs.get('container_cores', 1)


class TestValidateHostedFlags(unittest.TestCase):
    def test_no_hosted_node_passes(self):
        config = _MockConfig(hosted_node=None)
        validate_hosted_flags(config)  # should not raise

    def test_valid_config(self):
        config = _MockConfig(
            hosted_node='10.0.0.1',
            container_memory='2G',
            container_storage=[['root', 'auto', '10G'], ['template', 'local']],
            container_cores=2,
        )
        validate_hosted_flags(config)  # should not raise

    def test_missing_memory(self):
        config = _MockConfig(
            hosted_node='10.0.0.1',
            container_memory=None,
            container_storage=[['root', 'auto', '10G']],
        )
        with self.assertRaises(ValueError) as ctx:
            validate_hosted_flags(config)
        self.assertIn('--memory', str(ctx.exception))

    def test_missing_storage(self):
        config = _MockConfig(
            hosted_node='10.0.0.1',
            container_memory='2G',
            container_storage=None,
        )
        with self.assertRaises(ValueError) as ctx:
            validate_hosted_flags(config)
        self.assertIn('--storage', str(ctx.exception))

    def test_invalid_storage_type(self):
        config = _MockConfig(
            hosted_node='10.0.0.1',
            container_memory='2G',
            container_storage=[['bad', 'auto', '10G']],
        )
        with self.assertRaises(ValueError) as ctx:
            validate_hosted_flags(config)
        self.assertIn('TYPE', str(ctx.exception))

    def test_invalid_memory_format(self):
        config = _MockConfig(
            hosted_node='10.0.0.1',
            container_memory='2GB',
            container_storage=[['root', 'auto', '10G']],
        )
        with self.assertRaises(ValueError):
            validate_hosted_flags(config)

    def test_invalid_hosted_node_host(self):
        config = _MockConfig(
            hosted_node='bad host',
            container_memory='2G',
            container_storage=[['root', 'auto', '10G']],
        )
        with self.assertRaisesRegex(ValueError, "Invalid hosted node host: bad host"):
            validate_hosted_flags(config)

    def test_invalid_storage_amount_for_root(self):
        config = _MockConfig(
            hosted_node='10.0.0.1',
            container_memory='2G',
            container_storage=[['root', 'auto', 'bad']],
        )
        with self.assertRaises(ValueError):
            validate_hosted_flags(config)

    def test_template_storage_omits_amount(self):
        config = _MockConfig(
            hosted_node='10.0.0.1',
            container_memory='2G',
            container_storage=[['root', 'auto', '10G'], ['template', 'local']],
        )
        validate_hosted_flags(config)  # should not raise

    def test_template_storage_with_amount_rejected(self):
        config = _MockConfig(
            hosted_node='10.0.0.1',
            container_memory='2G',
            container_storage=[['root', 'auto', '10G'], ['template', 'local', 'ignored']],
        )
        with self.assertRaises(ValueError):
            validate_hosted_flags(config)

    def test_path_type_rejected(self):
        config = _MockConfig(
            hosted_node='10.0.0.1',
            container_memory='2G',
            container_storage=[['path', 'auto', '10G']],
        )
        with self.assertRaises(ValueError) as ctx:
            validate_hosted_flags(config)
        self.assertIn('TYPE', str(ctx.exception))

    def test_zero_cores_rejected(self):
        config = _MockConfig(
            hosted_node='10.0.0.1',
            container_memory='2G',
            container_storage=[['root', 'auto', '10G']],
            container_cores=0,
        )
        with self.assertRaises(ValueError) as ctx:
            validate_hosted_flags(config)
        self.assertIn('cores', str(ctx.exception).lower())

    def test_duplicate_storage_types_rejected(self):
        config = _MockConfig(
            hosted_node='10.0.0.1',
            container_memory='2G',
            container_storage=[['root', 'auto', '10G'], ['root', 'local', '20G']],
        )
        with self.assertRaises(ValueError):
            validate_hosted_flags(config)

    def test_storage_too_few_elements(self):
        config = _MockConfig(
            hosted_node='10.0.0.1',
            container_memory='2G',
            container_storage=['root', 'auto'],
        )
        with self.assertRaises(ValueError) as ctx:
            validate_hosted_flags(config)
        self.assertIn('TYPE POOL AMOUNT', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
