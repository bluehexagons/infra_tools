"""Workstation-oriented built-in plugin definitions."""

from __future__ import annotations

from lib.plugin_registry import PluginDefinition, SystemTypeDefinition


PLUGIN = PluginDefinition(
    name="workstation",
    module=__name__,
    plugin_kind="composition",
    dependencies=("core",),
    system_types=(
        SystemTypeDefinition(
            name="workstation_desktop",
            description="Desktop workstation with GUI",
            order=10,
            include_desktop=True,
            include_cli_tools=True,
            include_desktop_apps=True,
            default_browser="librewolf",
            step_builder="lib.plugin_steps:build_standard_steps",
        ),
        SystemTypeDefinition(
            name="pc_dev",
            description="PC development environment",
            order=20,
            include_desktop=True,
            include_cli_tools=True,
            include_pc_dev_apps=True,
            default_install_office=True,
            default_enable_smbclient=True,
            default_browser="librewolf",
            step_builder="lib.plugin_steps:build_standard_steps",
        ),
        SystemTypeDefinition(
            name="workstation_dev",
            description="Developer workstation",
            order=30,
            include_desktop=True,
            include_cli_tools=True,
            include_workstation_dev_apps=True,
            default_browser="librewolf",
            step_builder="lib.plugin_steps:build_standard_steps",
        ),
    ),
)
