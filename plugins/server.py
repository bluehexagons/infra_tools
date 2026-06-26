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
            default_machine_type="vm",
            include_cli_tools=True,
            step_builder="plugins.server:build_server_steps",
        ),
        SystemTypeDefinition(
            name="server_web",
            description="Web server",
            order=50,
            default_machine_type="vm",
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
    ),
)


def extend_antistatic_steps(config: SetupConfig, steps: list[tuple[str, StepFunc]]) -> None:
    """Append Antistatic service setup steps when configured."""
    if config.antistatic_server:
        from game.antistatic_steps import setup_antistatic_server

        steps.append(("Setting up antistatic lobby server", setup_antistatic_server))

    if config.antistatic_db:
        from game.antistatic_steps import setup_antistatic_db

        steps.append(("Setting up antistatic-db service", setup_antistatic_db))


def extend_gogs_steps(config: SetupConfig, steps: list[tuple[str, StepFunc]]) -> None:
    """Append Gogs setup and update steps when configured."""
    if not config.gogs:
        return

    from common.steps import configure_auto_update_gogs
    from web.gogs_steps import setup_gogs

    steps.append(("Setting up Gogs service", setup_gogs))
    steps.append(("Configuring Gogs auto-update", configure_auto_update_gogs))


def build_server_steps(config: SetupConfig) -> list[tuple[str, StepFunc]]:
    """Build server-oriented setup steps from plugin-owned capability helpers."""

    from plugins.common import (
        extend_package_steps,
        extend_agent_steps,
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
    extend_agent_steps(config, steps)
    extend_cicd_steps(config, steps)
    extend_app_server_steps(config, steps)
    extend_build_server_steps(config, steps)
    extend_antistatic_steps(config, steps)
    extend_gogs_steps(config, steps)
    steps.extend(get_final_steps())
    return steps
