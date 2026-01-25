"""Desktop and workstation setup steps."""

from __future__ import annotations

from .desktop_environment_steps import (
    install_desktop,
    configure_gnome_keyring,
    install_smbclient,
    configure_xfce_for_rdp,
)

from .xrdp_steps import (
    install_xrdp,
    harden_xrdp,
    configure_audio,
)

from .browser_steps import (
    install_browser,
    configure_default_browser,
    configure_vivaldi_browser,
)

from .apps_steps import (
    is_flatpak_installed,
    install_flatpak_if_needed,
    is_flatpak_app_installed,
    install_remmina,
    install_office_apps,
    install_desktop_apps,
    install_workstation_dev_apps,
)

__all__ = [
    'install_desktop',
    'configure_gnome_keyring',
    'install_smbclient',
    'configure_xfce_for_rdp',
    'install_xrdp',
    'harden_xrdp',
    'configure_audio',
    'install_browser',
    'configure_default_browser',
    'configure_vivaldi_browser',
    'is_flatpak_installed',
    'install_flatpak_if_needed',
    'is_flatpak_app_installed',
    'install_remmina',
    'install_office_apps',
    'install_desktop_apps',
    'install_workstation_dev_apps',
]
