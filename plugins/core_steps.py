"""Plugin-local step builders for the core plugin."""

from __future__ import annotations

from typing import TYPE_CHECKING

from lib.types import StepFunc

if TYPE_CHECKING:
    from lib.config import SetupConfig


def build_custom_steps(config: SetupConfig) -> list[tuple[str, StepFunc]]:
    """Build the explicit custom step list for the core plugin."""

    from lib.plugin_steps import build_custom_steps as _build_custom_steps

    return _build_custom_steps(config)
