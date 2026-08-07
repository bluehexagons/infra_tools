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
        "reconcile_samba_shares",
        "configure_smb_mount",
    ),
    custom_step_provider="plugins.smb:get_custom_step_functions",
    validators=(
        "parse_share_credentials",
        "parse_share_spec",
        "validate_samba_share_credentials",
        "parse_smb_mount_spec",
    ),
    validator_provider="plugins.smb:get_validator_functions",
)


def get_custom_step_functions() -> Mapping[str, StepFunc]:
    """Return plugin-owned custom step functions exported by the SMB capability."""

    from smb.steps import (
        configure_samba_fail2ban,
        configure_samba_firewall,
        configure_samba_global_settings,
        configure_smb_mount,
        install_samba,
        reconcile_samba_shares,
    )

    return {
        "install_samba": install_samba,
        "configure_samba_firewall": configure_samba_firewall,
        "configure_samba_global_settings": configure_samba_global_settings,
        "configure_samba_fail2ban": configure_samba_fail2ban,
        "reconcile_samba_shares": reconcile_samba_shares,
        "configure_smb_mount": configure_smb_mount,
    }


def get_validator_functions() -> Mapping[str, object]:
    """Return plugin-owned validator and parser functions for SMB flows."""

    from smb.samba_steps import (
        parse_share_credentials,
        parse_share_spec,
        validate_samba_share_credentials,
    )
    from smb.smb_mount_steps import parse_smb_mount_spec

    return {
        "parse_share_credentials": parse_share_credentials,
        "parse_share_spec": parse_share_spec,
        "validate_samba_share_credentials": validate_samba_share_credentials,
        "parse_smb_mount_spec": parse_smb_mount_spec,
    }
