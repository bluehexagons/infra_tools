"""Sync built-in capability plugin definitions and custom-step exports."""

from __future__ import annotations

from typing import TYPE_CHECKING, Mapping

from lib.plugin_registry import PluginDefinition

if TYPE_CHECKING:
    from lib.types import StepFunc


PLUGIN = PluginDefinition(
    name="sync",
    module=__name__,
    plugin_kind="capability",
    dependencies=("core",),
    custom_steps=(
        "install_rsync",
        "create_sync_service",
        "install_par2",
        "create_scrub_service",
    ),
    custom_step_provider="plugins.sync:get_custom_step_functions",
    validators=("parse_sync_spec", "parse_scrub_spec"),
    validator_provider="plugins.sync:get_validator_functions",
)


def get_custom_step_functions() -> Mapping[str, StepFunc]:
    """Return plugin-owned custom step functions exported by the sync capability."""

    from sync.steps import create_scrub_service, create_sync_service, install_par2, install_rsync

    return {
        "install_rsync": install_rsync,
        "create_sync_service": create_sync_service,
        "install_par2": install_par2,
        "create_scrub_service": create_scrub_service,
    }


def get_validator_functions() -> Mapping[str, object]:
    """Return plugin-owned validator and parser functions for sync flows."""

    from sync.scrub_steps import parse_scrub_spec
    from sync.sync_steps import parse_sync_spec

    return {
        "parse_sync_spec": parse_sync_spec,
        "parse_scrub_spec": parse_scrub_spec,
    }
