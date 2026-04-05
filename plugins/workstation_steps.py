"""Plugin-local step builders for workstation-oriented plugins."""

from __future__ import annotations

from typing import TYPE_CHECKING

from lib.types import StepFunc

if TYPE_CHECKING:
    from lib.config import SetupConfig


def build_standard_steps(config: SetupConfig) -> list[tuple[str, StepFunc]]:
    """Build the standard workstation step list."""

    from lib.plugin_steps import build_standard_steps as _build_standard_steps

    return _build_standard_steps(config)
