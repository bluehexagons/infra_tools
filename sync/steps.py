"""Sync and scrub setup steps."""

from __future__ import annotations

# Import from lib modules
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import functions from the original files
from lib.sync_steps import (
    install_rsync,
    create_sync_service,
)

from lib.scrub_steps import (
    install_par2,
    create_scrub_service,
)

# Re-export all functions
__all__ = [
    'install_rsync',
    'create_sync_service',
    'install_par2',
    'create_scrub_service',
]
