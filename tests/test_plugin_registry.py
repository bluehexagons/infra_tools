"""Tests for built-in plugin discovery and registry behavior."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.plugin_registry import (
    PluginDefinition,
    SystemTypeDefinition,
    build_plugin_registry,
    get_plugin_registry,
    get_system_type_definition,
    get_system_type_names,
)


class TestPluginRegistry(unittest.TestCase):
    def test_builtin_system_types_match_expected_order(self):
        self.assertEqual(
            get_system_type_names(),
            [
                "workstation_desktop",
                "pc_dev",
                "workstation_dev",
                "server_dev",
                "server_web",
                "server_lite",
                "server_proxmox",
                "custom_steps",
            ],
        )

    def test_builtin_registry_exposes_plugin_names(self):
        registry = get_plugin_registry()
        self.assertEqual(
            [plugin.name for plugin in registry.plugins],
            ["core", "server", "workstation"],
        )

    def test_system_type_metadata_drives_defaults(self):
        system_type = get_system_type_definition("pc_dev")
        self.assertTrue(system_type.include_desktop)
        self.assertTrue(system_type.include_cli_tools)
        self.assertTrue(system_type.include_pc_dev_apps)
        self.assertTrue(system_type.default_install_office)
        self.assertTrue(system_type.default_enable_smbclient)
        self.assertEqual(system_type.default_browser, "librewolf")

    def test_duplicate_plugin_names_fail(self):
        plugin = PluginDefinition(name="dup", module="plugins.one")
        with self.assertRaisesRegex(ValueError, "Duplicate plugin name"):
            build_plugin_registry([plugin, plugin])

    def test_unknown_plugin_dependency_fails(self):
        plugin = PluginDefinition(
            name="workstation",
            module="plugins.workstation",
            dependencies=("core",),
        )
        with self.assertRaisesRegex(ValueError, "depends on unknown plugin"):
            build_plugin_registry([plugin])

    def test_duplicate_system_type_names_fail(self):
        plugin_one = PluginDefinition(
            name="one",
            module="plugins.one",
            system_types=(
                SystemTypeDefinition(name="server_lite", description="One", order=10),
            ),
        )
        plugin_two = PluginDefinition(
            name="two",
            module="plugins.two",
            system_types=(
                SystemTypeDefinition(name="server_lite", description="Two", order=20),
            ),
        )
        with self.assertRaisesRegex(ValueError, "Duplicate system type"):
            build_plugin_registry([plugin_one, plugin_two])

    def test_cyclic_dependencies_fail(self):
        plugin_one = PluginDefinition(
            name="one",
            module="plugins.one",
            dependencies=("two",),
        )
        plugin_two = PluginDefinition(
            name="two",
            module="plugins.two",
            dependencies=("one",),
        )
        with self.assertRaisesRegex(ValueError, "Cyclic plugin dependencies"):
            build_plugin_registry([plugin_one, plugin_two])
