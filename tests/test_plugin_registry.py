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
from lib.system_types import get_steps_for_system_type
from lib.config import SetupConfig


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
        self.assertEqual(
            [plugin.plugin_kind for plugin in registry.plugins],
            ["base", "composition", "composition"],
        )

    def test_system_type_metadata_drives_defaults(self):
        system_type = get_system_type_definition("pc_dev")
        self.assertTrue(system_type.include_desktop)
        self.assertTrue(system_type.include_cli_tools)
        self.assertTrue(system_type.include_pc_dev_apps)
        self.assertTrue(system_type.default_install_office)
        self.assertTrue(system_type.default_enable_smbclient)
        self.assertEqual(system_type.default_browser, "librewolf")
        self.assertIsNotNone(system_type.step_builder)

    def test_builtin_system_types_use_plugin_local_step_builders(self):
        for system_type_name in get_system_type_names():
            system_type = get_system_type_definition(system_type_name)
            self.assertIsNotNone(system_type.step_builder)
            self.assertTrue(system_type.step_builder.startswith("plugins."))

    def test_custom_step_builder_is_plugin_registered(self):
        config = SetupConfig(
            host="host",
            username="user",
            system_type="custom_steps",
            custom_steps="install_ruby",
        )
        steps = get_steps_for_system_type(config)
        self.assertEqual([name for name, _ in steps], ["Running install_ruby"])

    def test_proxmox_step_builder_is_plugin_registered(self):
        config = SetupConfig(host="host", username="user", system_type="server_proxmox")
        step_names = [name for name, _ in get_steps_for_system_type(config)]
        self.assertEqual(step_names[0], "Creating remoteusers group")
        self.assertEqual(step_names[-1], "Checking if restart required")

    def test_duplicate_plugin_names_fail(self):
        plugin = PluginDefinition(name="dup", module="plugins.one")
        with self.assertRaisesRegex(ValueError, "Duplicate plugin name"):
            build_plugin_registry([plugin, plugin])

    def test_unknown_plugin_dependency_fails(self):
        plugin = PluginDefinition(
            name="workstation",
            module="plugins.workstation",
            plugin_kind="composition",
            dependencies=("core",),
            system_types=(
                SystemTypeDefinition(name="workstation_dev", description="Workstation", order=10),
            ),
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
            plugin_kind="composition",
            dependencies=("two",),
            system_types=(
                SystemTypeDefinition(name="one_system", description="One", order=10),
            ),
        )
        plugin_two = PluginDefinition(
            name="two",
            module="plugins.two",
            plugin_kind="composition",
            dependencies=("one",),
            system_types=(
                SystemTypeDefinition(name="two_system", description="Two", order=20),
            ),
        )
        with self.assertRaisesRegex(ValueError, "Cyclic plugin dependencies"):
            build_plugin_registry([plugin_one, plugin_two])

    def test_base_plugins_cannot_declare_dependencies(self):
        plugin = PluginDefinition(
            name="base-with-deps",
            module="plugins.base_with_deps",
            plugin_kind="base",
            dependencies=("core",),
        )
        with self.assertRaisesRegex(ValueError, "Base plugin .* cannot declare dependencies"):
            build_plugin_registry([plugin])

    def test_capability_plugins_cannot_register_system_types(self):
        plugin = PluginDefinition(
            name="capability-with-system",
            module="plugins.capability_with_system",
            plugin_kind="capability",
            system_types=(
                SystemTypeDefinition(name="bad_system", description="Bad", order=10),
            ),
        )
        with self.assertRaisesRegex(ValueError, "Capability plugin .* cannot register system types"):
            build_plugin_registry([plugin])

    def test_composition_plugins_must_register_system_types(self):
        plugin = PluginDefinition(
            name="composition-without-system",
            module="plugins.composition_without_system",
            plugin_kind="composition",
            dependencies=("core",),
        )
        core = PluginDefinition(name="core", module="plugins.core")
        with self.assertRaisesRegex(
            ValueError,
            "Composition plugin .* must register at least one system type",
        ):
            build_plugin_registry([core, plugin])
