"""Server-oriented built-in plugin definitions."""

from __future__ import annotations

from lib.plugin_registry import PluginDefinition, SystemTypeDefinition


PLUGIN = PluginDefinition(
    name="server",
    module=__name__,
    dependencies=("core",),
    system_types=(
        SystemTypeDefinition(
            name="server_dev",
            description="Development server",
            order=40,
            include_cli_tools=True,
            step_builder="lib.plugin_steps:build_standard_steps",
        ),
        SystemTypeDefinition(
            name="server_web",
            description="Web server",
            order=50,
            include_cli_tools=True,
            include_web_server=True,
            include_web_firewall=True,
            step_builder="lib.plugin_steps:build_standard_steps",
        ),
        SystemTypeDefinition(
            name="server_lite",
            description="Lightweight server",
            order=60,
            step_builder="lib.plugin_steps:build_standard_steps",
        ),
        SystemTypeDefinition(
            name="server_proxmox",
            description="Proxmox host server",
            order=70,
            default_no_restart=True,
            step_builder="lib.plugin_steps:build_server_proxmox_steps",
        ),
    ),
)
