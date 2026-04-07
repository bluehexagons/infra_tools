"""Server-oriented built-in plugin definitions and step builders."""

from __future__ import annotations

from typing import TYPE_CHECKING

from lib.plugin_registry import PluginDefinition, SystemTypeDefinition

if TYPE_CHECKING:
    from lib.config import SetupConfig
    from lib.types import StepFunc


PLUGIN = PluginDefinition(
    name="server",
    module=__name__,
    plugin_kind="composition",
    dependencies=("common", "core", "security", "web"),
    system_types=(
        SystemTypeDefinition(
            name="server_dev",
            description="Development server",
            order=40,
            include_cli_tools=True,
            step_builder="plugins.server:build_server_steps",
        ),
        SystemTypeDefinition(
            name="server_web",
            description="Web server",
            order=50,
            include_cli_tools=True,
            include_web_server=True,
            include_web_firewall=True,
            step_builder="plugins.server:build_server_steps",
        ),
        SystemTypeDefinition(
            name="server_lite",
            description="Lightweight server",
            order=60,
            step_builder="plugins.server:build_server_steps",
        ),
        SystemTypeDefinition(
            name="server_proxmox",
            description="Proxmox host server",
            order=70,
            default_no_restart=True,
            step_builder="plugins.server:build_server_proxmox_steps",
        ),
    ),
)


def build_server_steps(config: SetupConfig) -> list[tuple[str, StepFunc]]:
    """Build server-oriented setup steps from plugin-owned capability helpers."""

    from plugins.common import (
        extend_package_steps,
        extend_runtime_steps,
        get_cli_steps,
        get_common_steps,
        get_final_steps,
    )
    from plugins.security import get_security_steps, get_web_firewall_steps
    from plugins.web import (
        extend_app_server_steps,
        extend_build_server_steps,
        extend_cicd_steps,
        get_web_server_steps,
    )

    steps: list[tuple[str, StepFunc]] = list(get_common_steps())

    if config.include_web_firewall:
        steps.extend(get_web_firewall_steps())

    steps.extend(get_security_steps(lite=config.system_type in {"server_web", "server_lite"}))

    if config.include_web_server:
        steps.extend(get_web_server_steps())

    if config.include_cli_tools:
        steps.extend(get_cli_steps())

    extend_runtime_steps(config, steps)
    extend_package_steps(config, steps)
    extend_cicd_steps(config, steps)
    extend_app_server_steps(config, steps)
    extend_build_server_steps(config, steps)
    steps.extend(get_final_steps())
    return steps


def build_server_proxmox_steps(_: SetupConfig) -> list[tuple[str, StepFunc]]:
    """Build the dedicated Proxmox hardening flow."""

    from common.steps import check_restart_required, configure_swap
    from security.steps import (
        configure_auto_restart,
        configure_auto_updates,
        configure_cleanup_maintenance,
        create_remoteusers_group,
        harden_kernel,
        harden_ssh,
    )

    return [
        ("Creating remoteusers group", create_remoteusers_group),
        ("Configuring swap", configure_swap),
        ("Hardening SSH configuration", harden_ssh),
        ("Hardening kernel parameters", harden_kernel),
        ("Configuring automatic security updates", configure_auto_updates),
        ("Configuring cleanup maintenance service", configure_cleanup_maintenance),
        ("Configuring automatic restart service", configure_auto_restart),
        ("Checking if restart required", check_restart_required),
    ]
