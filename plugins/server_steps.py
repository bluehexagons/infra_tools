"""Plugin-local step builders for server-oriented plugins."""

from __future__ import annotations

from typing import TYPE_CHECKING

from lib.types import StepFunc

if TYPE_CHECKING:
    from lib.config import SetupConfig


def build_standard_steps(config: SetupConfig) -> list[tuple[str, StepFunc]]:
    """Build the standard server step list."""

    from lib.plugin_steps import build_standard_steps as _build_standard_steps

    return _build_standard_steps(config)


def build_server_proxmox_steps(config: SetupConfig) -> list[tuple[str, StepFunc]]:
    """Build the dedicated Proxmox hardening step list."""

    from lib.plugin_steps import build_server_proxmox_steps as _build_server_proxmox_steps

    return _build_server_proxmox_steps(config)
