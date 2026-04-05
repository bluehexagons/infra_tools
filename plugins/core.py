"""Core plugin definitions."""

from __future__ import annotations

from lib.plugin_registry import PluginDefinition, SystemTypeDefinition


PLUGIN = PluginDefinition(
    name="core",
    module=__name__,
    plugin_kind="base",
    system_types=(
        SystemTypeDefinition(
            name="custom_steps",
            description="Run an explicit custom step list",
            order=80,
            step_builder="plugins.core_steps:build_custom_steps",
        ),
    ),
)
