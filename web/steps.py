"""Web server setup steps."""

from __future__ import annotations

from .web_steps import (
    install_nginx,
    configure_nginx_security,
    create_hello_world_site,
    configure_default_site,
)

__all__ = [
    'install_nginx',
    'configure_nginx_security',
    'create_hello_world_site',
    'configure_default_site',
]
