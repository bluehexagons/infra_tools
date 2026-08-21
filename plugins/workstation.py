"""Workstation-oriented built-in plugin definitions and step builders."""

from __future__ import annotations

from typing import TYPE_CHECKING

from lib.plugin_registry import PluginDefinition, SystemTypeDefinition

if TYPE_CHECKING:
    from lib.config import SetupConfig
    from lib.types import StepFunc


PLUGIN = PluginDefinition(
    name="workstation",
    module=__name__,
    plugin_kind="composition",
    dependencies=("common", "core", "desktop", "security", "web"),
    system_types=(
        SystemTypeDefinition(
            name="workstation_desktop",
            description="Desktop workstation with GUI",
            order=10,
            include_desktop=True,
            include_cli_tools=True,
            include_desktop_apps=True,
            default_browser="librewolf",
            step_builder="plugins.workstation:build_workstation_steps",
        ),
        SystemTypeDefinition(
            name="pc_dev",
            description="PC development environment",
            order=20,
            include_desktop=True,
            include_cli_tools=True,
            include_pc_dev_apps=True,
            default_install_office=True,
            default_enable_smbclient=True,
            default_browser="librewolf",
            step_builder="plugins.workstation:build_workstation_steps",
        ),
        SystemTypeDefinition(
            name="workstation_dev",
            description="Developer workstation",
            order=30,
            include_desktop=True,
            include_cli_tools=True,
            include_workstation_dev_apps=True,
            default_browser="firefox",
            step_builder="plugins.workstation:build_workstation_steps",
        ),
    ),
)


def build_workstation_steps(config: SetupConfig) -> list[tuple[str, StepFunc]]:
    """Build workstation-oriented setup steps from plugin-owned capability helpers."""

    from plugins.common import (
        extend_agent_steps,
        extend_control_plane_steps,
        extend_package_steps,
        extend_runtime_steps,
        get_cli_steps,
        get_common_steps,
        get_final_steps,
    )
    from plugins.desktop import (
        extend_desktop_app_steps,
        extend_desktop_browser_and_office_steps,
        extend_desktop_steps,
    )
    from plugins.security import get_security_steps, get_web_firewall_steps
    from plugins.web import (
        extend_app_server_steps,
        extend_build_server_steps,
        extend_cicd_steps,
        get_web_server_steps,
    )

    steps: list[tuple[str, StepFunc]] = list(get_common_steps(config))

    if config.include_web_firewall:
        steps.extend(get_web_firewall_steps())

    steps.extend(get_security_steps(lite=False))
    extend_desktop_steps(config, steps)

    if config.include_web_server:
        steps.extend(get_web_server_steps())

    if config.include_cli_tools:
        steps.extend(get_cli_steps())

    extend_control_plane_steps(config, steps)
    extend_runtime_steps(config, steps)
    extend_desktop_app_steps(config, steps)
    extend_desktop_browser_and_office_steps(config, steps)
    extend_package_steps(config, steps)
    extend_agent_steps(config, steps)
    extend_cicd_steps(config, steps)
    extend_app_server_steps(config, steps)
    extend_build_server_steps(config, steps)
    steps.extend(get_final_steps(config))
    return steps
