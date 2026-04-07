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
    """Build an explicit custom step list from plugin-owned step providers."""

    from lib.plugin_registry import resolve_custom_step

    if not config.custom_steps:
        return []

    steps: list[tuple[str, StepFunc]] = []
    for step_name in config.custom_steps.split():
        steps.append((f"Running {step_name}", resolve_custom_step(step_name)))
    return steps
