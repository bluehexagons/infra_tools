"""Core plugin definitions and builder entry points."""

from __future__ import annotations

from typing import TYPE_CHECKING

from lib.plugin_registry import PluginDefinition, SystemTypeDefinition

if TYPE_CHECKING:
    from lib.config import SetupConfig
    from lib.types import StepFunc


PLUGIN = PluginDefinition(
    name="core",
    module=__name__,
    plugin_kind="base",
    system_types=(
        SystemTypeDefinition(
            name="custom_steps",
            description="Run an explicit custom step list",
            order=80,
            step_builder="plugins.core:build_custom_steps",
        ),
    ),
)


def build_custom_steps(config: SetupConfig) -> list[tuple[str, StepFunc]]:
    """Delegate custom-step resolution to the shared custom-step catalog."""

    from lib.plugin_steps import build_custom_steps as _build_custom_steps

    return _build_custom_steps(config)
