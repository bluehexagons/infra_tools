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
    configure_auto_update_node,
    configure_auto_update_ruby,
)

from .swap_steps import configure_swap
from .ssl_steps import install_certbot
from .cloudflare_steps import (
    configure_cloudflare_firewall,
    create_cloudflared_config_directory,
    configure_nginx_for_cloudflare,
    install_cloudflared_service_helper,
    run_cloudflare_tunnel_setup,
)

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
    'configure_auto_update_node',
    'configure_auto_update_ruby',
    'configure_swap',
    'install_certbot',
    'configure_cloudflare_firewall',
    'create_cloudflared_config_directory',
    'configure_nginx_for_cloudflare',
    'install_cloudflared_service_helper',
    'run_cloudflare_tunnel_setup',
]
