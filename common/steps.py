"""Common setup steps."""

from __future__ import annotations

from .common_steps import (
    update_and_upgrade_packages,
    ensure_sudo_installed,
    configure_locale,
    setup_user,
    copy_ssh_keys_to_user,
    generate_ssh_key,
    configure_time_sync,
    install_cli_tools,
    check_restart_required,
    install_ruby,
    install_go,
    install_node,
    install_mail_utils,
)

from .swap_steps import configure_swap

__all__ = [
    'update_and_upgrade_packages',
    'ensure_sudo_installed',
    'configure_locale',
    'setup_user',
    'copy_ssh_keys_to_user',
    'generate_ssh_key',
    'configure_time_sync',
    'install_cli_tools',
    'check_restart_required',
    'install_ruby',
    'install_go',
    'install_node',
    'install_mail_utils',
    'configure_swap',
]
