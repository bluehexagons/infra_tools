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
    resolve_custom_step,
    resolve_validator,
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
            ["core", "common", "desktop", "security", "smb", "sync", "web", "proxmox", "server", "workstation"],
        )
        self.assertEqual(
            [plugin.plugin_kind for plugin in registry.plugins],
            [
                "base",
                "capability",
                "capability",
                "capability",
                "capability",
                "capability",
                "capability",
                "composition",
                "composition",
                "composition",
            ],
        )

    def test_builtin_step_builders_are_plugin_owned(self):
        self.assertEqual(
            get_system_type_definition("custom_steps").step_builder,
            "plugins.core:build_custom_steps",
        )
        self.assertEqual(
            get_system_type_definition("server_dev").step_builder,
            "plugins.server:build_server_steps",
        )
        self.assertEqual(
            get_system_type_definition("server_proxmox").step_builder,
            "plugins.proxmox:build_server_proxmox_steps",
        )
        self.assertEqual(
            get_system_type_definition("workstation_dev").step_builder,
            "plugins.workstation:build_workstation_steps",
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

    def test_custom_step_builder_is_plugin_registered(self):
        config = SetupConfig(
            host="host",
            username="user",
            system_type="custom_steps",
            custom_steps="install_ruby",
        )
        steps = get_steps_for_system_type(config)
        self.assertEqual([name for name, _ in steps], ["Running install_ruby"])

    def test_custom_step_resolution_is_plugin_owned(self):
        self.assertIs(resolve_custom_step("install_ruby"), resolve_custom_step("install_ruby"))
        self.assertTrue(callable(resolve_custom_step("configure_smb_mount")))

    def test_plugin_validator_resolution_is_plugin_owned(self):
        self.assertTrue(callable(resolve_validator("parse_sync_spec")))
        self.assertTrue(callable(resolve_validator("validate_samba_share_credentials")))

    def test_proxmox_step_builder_is_plugin_registered(self):
        config = SetupConfig(host="host", username="user", system_type="server_proxmox")
        step_names = [name for name, _ in get_steps_for_system_type(config)]
        self.assertEqual(step_names[0], "Creating remoteusers group")
        self.assertEqual(step_names[-1], "Checking if restart required")

    def test_build_server_adds_build_user_tool_steps(self):
        config = SetupConfig(
            host="host",
            username="user",
            system_type="server_web",
            is_build_server=True,
            install_node=True,
            install_python=True,
        )
        step_names = [name for name, _ in get_steps_for_system_type(config)]
        self.assertIn("Installing Node.js (nvm + latest LTS + PNPM)", step_names)
        self.assertIn("Installing build-user Node.js", step_names)
        self.assertIn("Installing build-user Python tooling", step_names)
        self.assertLess(
            step_names.index("Creating build workspace directories"),
            step_names.index("Installing build-user Node.js"),
        )

    def test_server_dev_adds_agent_vm_steps(self):
        config = SetupConfig(
            host="host",
            username="user",
            system_type="server_dev",
            install_gh=True,
            install_codex=True,
            install_claude=True,
            install_opencode=True,
            install_t3code=True,
            copy_agent_config=True,
            copy_agent_keys=True,
            agent_repos=["https://github.com/user/repo.git"],
            include_cli_tools=True,
        )
        step_names = [name for name, _ in get_steps_for_system_type(config)]
        self.assertIn("Installing GitHub CLI", step_names)
        self.assertIn("Installing common agent coding tools", step_names)
        self.assertIn("Installing Codex CLI", step_names)
        self.assertIn("Installing Claude Code", step_names)
        self.assertIn("Installing OpenCode", step_names)
        self.assertIn("Installing T3 Code", step_names)
        self.assertIn("Copying agent tool configuration", step_names)
        self.assertIn("Installing uploaded agent repositories", step_names)
        self.assertLess(
            step_names.index("Installing CLI tools"),
            step_names.index("Installing GitHub CLI"),
        )

    def test_workstation_dev_adds_agent_vm_steps(self):
        config = SetupConfig(
            host="host",
            username="user",
            system_type="workstation_dev",
            agent_suite="terminal",
            copy_agent_config=True,
            agent_repos=["https://github.com/user/repo.git"],
            include_desktop=True,
            include_cli_tools=True,
        )
        step_names = [name for name, _ in get_steps_for_system_type(config)]
        self.assertIn("Installing common agent coding tools", step_names)
        self.assertIn("Installing GitHub CLI", step_names)
        self.assertIn("Installing Codex CLI", step_names)
        self.assertIn("Installing Claude Code", step_names)
        self.assertIn("Installing OpenCode", step_names)
        self.assertIn("Copying agent tool configuration", step_names)
        self.assertIn("Installing uploaded agent repositories", step_names)
        self.assertLess(
            step_names.index("Installing CLI tools"),
            step_names.index("Installing GitHub CLI"),
        )

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

    def test_duplicate_custom_step_names_fail(self):
        plugin_one = PluginDefinition(
            name="one",
            module="plugins.one",
            custom_steps=("install_ruby",),
            custom_step_provider="plugins.one:get_custom_step_functions",
        )
        plugin_two = PluginDefinition(
            name="two",
            module="plugins.two",
            custom_steps=("install_ruby",),
            custom_step_provider="plugins.two:get_custom_step_functions",
        )
        with self.assertRaisesRegex(ValueError, "Duplicate custom step"):
            build_plugin_registry([plugin_one, plugin_two])

    def test_duplicate_validator_names_fail(self):
        plugin_one = PluginDefinition(
            name="one",
            module="plugins.one",
            validators=("parse_sync_spec",),
            validator_provider="plugins.one:get_validator_functions",
        )
        plugin_two = PluginDefinition(
            name="two",
            module="plugins.two",
            validators=("parse_sync_spec",),
            validator_provider="plugins.two:get_validator_functions",
        )
        with self.assertRaisesRegex(ValueError, "Duplicate validator"):
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

    def test_custom_step_provider_requires_custom_steps(self):
        plugin = PluginDefinition(
            name="provider-only",
            module="plugins.provider_only",
            custom_step_provider="plugins.provider_only:get_custom_step_functions",
        )
        with self.assertRaisesRegex(ValueError, "must declare both custom_steps and custom_step_provider"):
            build_plugin_registry([plugin])

    def test_validator_provider_requires_validators(self):
        plugin = PluginDefinition(
            name="validator-only",
            module="plugins.validator_only",
            validator_provider="plugins.validator_only:get_validator_functions",
        )
        with self.assertRaisesRegex(ValueError, "must declare both validators and validator_provider"):
            build_plugin_registry([plugin])
