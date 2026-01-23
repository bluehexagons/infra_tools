"""Desktop and workstation setup steps."""

from __future__ import annotations

from .desktop_steps import (
    is_flatpak_installed,
    install_flatpak_if_needed,
    is_flatpak_app_installed,
    install_desktop,
    install_xrdp,
    harden_xrdp,
    configure_audio,
    install_browser,
    install_remmina,
    install_office_apps,
    install_desktop_apps,
    configure_default_browser,
    install_workstation_dev_apps,
    configure_vivaldi_browser,
    configure_gnome_keyring,
    install_smbclient,
)

__all__ = [
    'is_flatpak_installed',
    'install_flatpak_if_needed',
    'is_flatpak_app_installed',
    'install_desktop',
    'install_xrdp',
    'harden_xrdp',
    'configure_audio',
    'install_browser',
    'install_remmina',
    'install_office_apps',
    'install_desktop_apps',
    'configure_default_browser',
    'install_workstation_dev_apps',
    'configure_vivaldi_browser',
    'configure_gnome_keyring',
    'install_smbclient',
]
