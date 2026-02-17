"""Web server setup steps."""

from __future__ import annotations

from .web_steps import (
    install_nginx,
    configure_nginx_security,
    create_hello_world_site,
    configure_default_site,
)

from .ssl_steps import install_certbot

from .cloudflare_steps import (
    configure_cloudflare_firewall,
    create_cloudflared_config_directory,
    configure_nginx_for_cloudflare,
    install_cloudflared_service_helper,
    run_cloudflare_tunnel_setup,
)

from .dev_tools_steps import (
    configure_auto_update_node,
    configure_auto_update_ruby,
)

from .cicd_steps import (
    install_cicd_dependencies,
    create_cicd_user,
    create_cicd_directories,
    generate_webhook_secret,
    create_default_webhook_config,
    create_webhook_receiver_service,
    create_cicd_executor_service,
    configure_nginx_for_webhook,
    update_cloudflare_tunnel_for_webhook,
)

__all__ = [
    'install_nginx',
    'configure_nginx_security',
    'create_hello_world_site',
    'configure_default_site',
    'install_certbot',
    'configure_cloudflare_firewall',
    'create_cloudflared_config_directory',
    'configure_nginx_for_cloudflare',
    'install_cloudflared_service_helper',
    'run_cloudflare_tunnel_setup',
    'configure_auto_update_node',
    'configure_auto_update_ruby',
    'install_cicd_dependencies',
    'create_cicd_user',
    'create_cicd_directories',
    'generate_webhook_secret',
    'create_default_webhook_config',
    'create_webhook_receiver_service',
    'create_cicd_executor_service',
    'configure_nginx_for_webhook',
    'update_cloudflare_tunnel_for_webhook',
]
