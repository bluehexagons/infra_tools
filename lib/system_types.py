"""Registry-backed step resolution for system types."""

from __future__ import annotations

from lib.config import SetupConfig
from lib.plugin_registry import resolve_step_builder
from lib.types import StepFunc


def get_steps_for_system_type(config: SetupConfig) -> list[tuple[str, StepFunc]]:
    """Build step list for a system type using plugin-registered step builders."""

    return resolve_step_builder(config.system_type)(config)
