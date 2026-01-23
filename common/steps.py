"""Common setup steps."""

from __future__ import annotations

# Import from lib modules
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import functions from common_steps
from lib.common_steps import (
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

from lib.swap_steps import configure_swap
from lib.ssl_steps import install_certbot
from lib.cloudflare_steps import (
    configure_cloudflare_firewall,
    create_cloudflared_config_directory,
    configure_nginx_for_cloudflare,
    install_cloudflared_service_helper,
    run_cloudflare_tunnel_setup,
)

# Re-export all functions
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
