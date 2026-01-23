"""Sync and scrub setup steps."""

from __future__ import annotations

from .sync_steps import (
    install_rsync,
    create_sync_service,
)

from .scrub_steps import (
    install_par2,
    create_scrub_service,
)

__all__ = [
    'install_rsync',
    'create_sync_service',
    'install_par2',
    'create_scrub_service',
]
