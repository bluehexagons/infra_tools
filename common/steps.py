"""Common setup steps."""

from __future__ import annotations

from .common_steps import (
    check_debian_package_sources,
    update_and_upgrade_packages,
    ensure_sudo_installed,
    configure_locale,
    configure_ipv4_preference,
    setup_user,
    copy_ssh_keys_to_user,
    generate_ssh_key,
    configure_time_sync,
    install_cli_tools,
    install_data_analysis_tools,
    install_control_plane_tools,
    check_restart_required,
    install_go,
    install_node,
    install_python,
    configure_auto_update_gogs,
    configure_auto_update_uv,
    install_mail_utils,
    install_apt_packages,
    install_flatpak_packages,
)

from .swap_steps import configure_swap
from .network_steps import (
    configure_mdns,
    configure_static_network,
    configure_system_hostname,
)
from .godot_steps import (
    configure_auto_update_godot,
    install_godot,
    install_godot_bundles,
)

__all__ = [
    'check_debian_package_sources',
    'update_and_upgrade_packages',
    'ensure_sudo_installed',
    'configure_locale',
    'configure_ipv4_preference',
    'setup_user',
    'copy_ssh_keys_to_user',
    'generate_ssh_key',
    'configure_time_sync',
    'install_cli_tools',
    'install_data_analysis_tools',
    'install_control_plane_tools',
    'check_restart_required',
    'install_go',
    'install_node',
    'install_python',
    'install_godot',
    'install_godot_bundles',
    'configure_auto_update_gogs',
    'configure_auto_update_uv',
    'configure_auto_update_godot',
    'install_mail_utils',
    'configure_swap',
    'install_apt_packages',
    'install_flatpak_packages',
    'configure_static_network',
    'configure_system_hostname',
    'configure_mdns',
]
