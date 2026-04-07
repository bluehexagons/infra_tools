"""SMB built-in capability plugin definitions and custom-step exports."""

from __future__ import annotations

from typing import TYPE_CHECKING, Mapping

from lib.plugin_registry import PluginDefinition

if TYPE_CHECKING:
    from lib.types import StepFunc


PLUGIN = PluginDefinition(
    name="smb",
    module=__name__,
    plugin_kind="capability",
    dependencies=("core",),
    custom_steps=(
        "install_samba",
        "configure_samba_firewall",
        "configure_samba_global_settings",
        "configure_samba_fail2ban",
        "setup_samba_share",
        "configure_smb_mount",
    ),
    custom_step_provider="plugins.smb:get_custom_step_functions",
)


def get_custom_step_functions() -> Mapping[str, StepFunc]:
    """Return plugin-owned custom step functions exported by the SMB capability."""

    from smb.steps import (
        configure_samba_fail2ban,
        configure_samba_firewall,
        configure_samba_global_settings,
        configure_smb_mount,
        install_samba,
        setup_samba_share,
    )

    return {
        "install_samba": install_samba,
        "configure_samba_firewall": configure_samba_firewall,
        "configure_samba_global_settings": configure_samba_global_settings,
        "configure_samba_fail2ban": configure_samba_fail2ban,
        "setup_samba_share": setup_samba_share,
        "configure_smb_mount": configure_smb_mount,
    }
