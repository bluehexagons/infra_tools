"""Security built-in capability plugin definitions and step helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Mapping

from lib.plugin_registry import PluginDefinition

if TYPE_CHECKING:
    from lib.types import StepFunc


PLUGIN = PluginDefinition(
    name="security",
    module=__name__,
    plugin_kind="capability",
    dependencies=("core",),
    custom_steps=(
        "create_remoteusers_group",
        "configure_firewall",
        "configure_fail2ban",
        "harden_ssh",
        "harden_kernel",
        "configure_auto_updates",
        "configure_firewall_web",
        "configure_auto_restart",
        "configure_cleanup_maintenance",
    ),
    custom_step_provider="plugins.security:get_custom_step_functions",
)


def get_security_steps(*, lite: bool) -> list[tuple[str, StepFunc]]:
    """Return the standard security-hardening steps for a built-in flow."""

    from security.steps import (
        configure_auto_restart,
        configure_auto_updates,
        configure_cleanup_maintenance,
        configure_firewall,
        harden_kernel,
        harden_ssh,
    )

    steps: list[tuple[str, StepFunc]] = []
    if not lite:
        steps.append(("Configuring firewall", configure_firewall))

    steps.extend(
        [
            ("Hardening SSH configuration", harden_ssh),
            ("Hardening kernel parameters", harden_kernel),
            ("Configuring automatic security updates", configure_auto_updates),
            ("Configuring cleanup maintenance service", configure_cleanup_maintenance),
            ("Configuring automatic restart service", configure_auto_restart),
        ]
    )
    return steps


def get_web_firewall_steps() -> list[tuple[str, StepFunc]]:
    """Return the additional firewall steps for web-facing systems."""

    from security.steps import configure_firewall_web

    return [("Configuring firewall for web server", configure_firewall_web)]


def get_custom_step_functions() -> Mapping[str, StepFunc]:
    """Return plugin-owned custom step functions exported by the security capability."""

    from security.steps import (
        configure_auto_restart,
        configure_auto_updates,
        configure_cleanup_maintenance,
        configure_fail2ban,
        configure_firewall,
        configure_firewall_web,
        create_remoteusers_group,
        harden_kernel,
        harden_ssh,
    )

    return {
        "create_remoteusers_group": create_remoteusers_group,
        "configure_firewall": configure_firewall,
        "configure_fail2ban": configure_fail2ban,
        "harden_ssh": harden_ssh,
        "harden_kernel": harden_kernel,
        "configure_auto_updates": configure_auto_updates,
        "configure_firewall_web": configure_firewall_web,
        "configure_auto_restart": configure_auto_restart,
        "configure_cleanup_maintenance": configure_cleanup_maintenance,
    }
