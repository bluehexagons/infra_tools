"""Common built-in capability plugin definitions and step helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Mapping

from lib.plugin_registry import PluginDefinition

if TYPE_CHECKING:
    from lib.config import SetupConfig
    from lib.types import StepFunc


PLUGIN = PluginDefinition(
    name="common",
    module=__name__,
    plugin_kind="capability",
    dependencies=("core",),
    custom_steps=(
        "install_ruby",
        "install_go",
        "install_node",
        "install_python",
        "configure_auto_update_uv",
        "update_and_upgrade_packages",
        "ensure_sudo_installed",
        "configure_locale",
        "setup_user",
        "copy_ssh_keys_to_user",
        "generate_ssh_key",
        "configure_time_sync",
        "install_cli_tools",
        "check_restart_required",
        "configure_auto_update_ruby",
        "install_mail_utils",
        "configure_swap",
        "install_apt_packages",
        "install_flatpak_packages",
    ),
    custom_step_provider="plugins.common:get_custom_step_functions",
)


def get_common_steps() -> list[tuple[str, StepFunc]]:
    """Return the shared foundation steps for built-in setup flows."""

    from common.steps import (
        configure_locale,
        configure_swap,
        configure_time_sync,
        copy_ssh_keys_to_user,
        ensure_sudo_installed,
        generate_ssh_key,
        setup_user,
        update_and_upgrade_packages,
    )
    from security.steps import create_remoteusers_group

    return [
        ("Updating and upgrading packages", update_and_upgrade_packages),
        ("Ensuring sudo is installed", ensure_sudo_installed),
        ("Configuring UTF-8 locale", configure_locale),
        ("Creating remoteusers group", create_remoteusers_group),
        ("Setting up user", setup_user),
        ("Copying SSH keys to user", copy_ssh_keys_to_user),
        ("Generating SSH key for user", generate_ssh_key),
        ("Configuring time synchronization", configure_time_sync),
        ("Configuring swap", configure_swap),
    ]


def get_cli_steps() -> list[tuple[str, StepFunc]]:
    """Return the shared CLI-tool steps for built-in setup flows."""

    from common.steps import install_cli_tools

    return [("Installing CLI tools", install_cli_tools)]


def get_final_steps() -> list[tuple[str, StepFunc]]:
    """Return the standard final verification steps for built-in setup flows."""

    from common.steps import check_restart_required

    return [("Checking if restart required", check_restart_required)]


def extend_runtime_steps(config: SetupConfig, steps: list[tuple[str, StepFunc]]) -> None:
    """Append optional language-runtime steps in the established order."""

    from common.steps import (
        configure_auto_update_ruby,
        configure_auto_update_uv,
        install_go,
        install_node,
        install_python,
        install_ruby,
    )
    from web.steps import configure_auto_update_node

    if config.install_ruby:
        steps.append(("Installing Ruby (apt packages)", install_ruby))
        steps.append(("Configuring Ruby auto-update", configure_auto_update_ruby))
    if config.install_go:
        steps.append(("Installing Go (latest version)", install_go))
    if config.install_node:
        steps.append(("Installing Node.js (nvm + latest LTS + PNPM)", install_node))
        steps.append(("Configuring Node.js auto-update", configure_auto_update_node))
    if config.install_python:
        steps.append(("Installing Python tooling (aliases + uv)", install_python))
        steps.append(("Configuring uv auto-update", configure_auto_update_uv))


def extend_package_steps(config: SetupConfig, steps: list[tuple[str, StepFunc]]) -> None:
    """Append optional package-install and notification steps."""

    from common.steps import install_apt_packages, install_flatpak_packages, install_mail_utils

    if config.apt_packages:
        steps.append(("Installing custom apt packages", install_apt_packages))

    if config.flatpak_packages:
        steps.append(("Installing custom flatpak packages", install_flatpak_packages))

    if config.notify_specs:
        steps.append(("Installing mail utilities for notifications", install_mail_utils))


def get_custom_step_functions() -> Mapping[str, StepFunc]:
    """Return plugin-owned custom step functions exported by the common capability."""

    from common.steps import (
        check_restart_required,
        configure_auto_update_ruby,
        configure_auto_update_uv,
        configure_locale,
        configure_swap,
        configure_time_sync,
        copy_ssh_keys_to_user,
        ensure_sudo_installed,
        generate_ssh_key,
        install_apt_packages,
        install_cli_tools,
        install_flatpak_packages,
        install_go,
        install_mail_utils,
        install_node,
        install_python,
        install_ruby,
        setup_user,
        update_and_upgrade_packages,
    )

    return {
        "install_ruby": install_ruby,
        "install_go": install_go,
        "install_node": install_node,
        "install_python": install_python,
        "configure_auto_update_uv": configure_auto_update_uv,
        "update_and_upgrade_packages": update_and_upgrade_packages,
        "ensure_sudo_installed": ensure_sudo_installed,
        "configure_locale": configure_locale,
        "setup_user": setup_user,
        "copy_ssh_keys_to_user": copy_ssh_keys_to_user,
        "generate_ssh_key": generate_ssh_key,
        "configure_time_sync": configure_time_sync,
        "install_cli_tools": install_cli_tools,
        "check_restart_required": check_restart_required,
        "configure_auto_update_ruby": configure_auto_update_ruby,
        "install_mail_utils": install_mail_utils,
        "configure_swap": configure_swap,
        "install_apt_packages": install_apt_packages,
        "install_flatpak_packages": install_flatpak_packages,
    }
