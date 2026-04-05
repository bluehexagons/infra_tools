"""Core plugin definitions."""

from __future__ import annotations

from lib.plugin_registry import PluginDefinition, SystemTypeDefinition


PLUGIN = PluginDefinition(
    name="core",
    module=__name__,
    system_types=(
        SystemTypeDefinition(
            name="custom_steps",
            description="Run an explicit custom step list",
            order=80,
        ),
    ),
)
