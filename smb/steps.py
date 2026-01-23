"""SMB/Samba setup steps."""

from __future__ import annotations

# Import from lib modules
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import functions from the original files
from lib.samba_steps import (
    install_samba,
    configure_samba_firewall,
    configure_samba_global_settings,
    configure_samba_fail2ban,
    setup_samba_share,
)

from lib.smb_mount_steps import (
    configure_smb_mount,
)

# Re-export all functions
__all__ = [
    'install_samba',
    'configure_samba_firewall',
    'configure_samba_global_settings',
    'configure_samba_fail2ban',
    'setup_samba_share',
    'configure_smb_mount',
]
