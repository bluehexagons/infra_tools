"""System type definitions and step configurations."""

from .common_steps import (
    update_and_upgrade_packages,
    ensure_sudo_installed,
    configure_locale,
    setup_user,
    copy_ssh_keys_to_user,
    configure_time_sync,
    install_cli_tools,
    check_restart_required,
)
from .desktop_steps import (
    install_desktop,
    install_xrdp,
    configure_audio,
    install_desktop_apps,
    configure_default_browser,
    install_workstation_dev_apps,
    configure_vivaldi_browser,
)
from .security_steps import (
    configure_firewall,
    configure_fail2ban,
    harden_ssh,
    harden_kernel,
    configure_auto_updates,
    configure_firewall_web,
    configure_firewall_ssh_only,
)
from .web_steps import (
    install_nginx,
    configure_nginx_security,
    create_hello_world_site,
    configure_default_site,
)


# Common steps for all system types
COMMON_STEPS = [
    ("Updating and upgrading packages", update_and_upgrade_packages),
    ("Ensuring sudo is installed", ensure_sudo_installed),
    ("Configuring UTF-8 locale", configure_locale),
    ("Setting up user", setup_user),
    ("Copying SSH keys to user", copy_ssh_keys_to_user),
    ("Configuring time synchronization", configure_time_sync),
]

# Desktop-specific steps
DESKTOP_STEPS = [
    ("Installing XFCE desktop environment", install_desktop),
    ("Installing xRDP", install_xrdp),
    ("Configuring audio for RDP", configure_audio),
]

# Desktop security steps (fail2ban for RDP)
DESKTOP_SECURITY_STEPS = [
    ("Installing fail2ban for RDP brute-force protection", configure_fail2ban),
]

# Security and system hardening steps (common to most types)
SECURITY_STEPS = [
    ("Configuring firewall", configure_firewall),
    ("Hardening SSH configuration", harden_ssh),
    ("Hardening kernel parameters", harden_kernel),
    ("Configuring automatic security updates", configure_auto_updates),
]

# Final steps
FINAL_STEPS = [
    ("Checking if restart required", check_restart_required),
]

# CLI tools step (common to all)
CLI_STEPS = [
    ("Installing CLI tools", install_cli_tools),
]

# Desktop application steps
DESKTOP_APP_STEPS = [
    ("Installing desktop applications", install_desktop_apps),
    ("Configuring default browser", configure_default_browser),
]

# Workstation dev application steps
WORKSTATION_DEV_APP_STEPS = [
    ("Installing workstation dev applications", install_workstation_dev_apps),
    ("Configuring default browser", configure_vivaldi_browser),
]

# Web server steps
WEB_SERVER_STEPS = [
    ("Installing nginx", install_nginx),
    ("Configuring nginx security settings", configure_nginx_security),
    ("Creating Hello World website", create_hello_world_site),
    ("Configuring default site", configure_default_site),
]

# Web server firewall (replaces standard firewall for server_web)
WEB_FIREWALL_STEPS = [
    ("Configuring firewall for web server", configure_firewall_web),
]

# SSH-only firewall (for basic servers)
SSH_FIREWALL_STEPS = [
    ("Configuring firewall (SSH only)", configure_firewall_ssh_only),
]

# Proxmox-specific steps (minimal hardening for existing systems)
PROXMOX_STEPS = [
    ("Hardening SSH configuration", harden_ssh),
    ("Hardening kernel parameters", harden_kernel),
    ("Configuring automatic security updates", configure_auto_updates),
    ("Checking if restart required", check_restart_required),
]


def get_steps_for_system_type(system_type: str, skip_audio: bool = False) -> list:
    if system_type == "workstation_desktop":
        desktop_steps = DESKTOP_STEPS
        if skip_audio:
            desktop_steps = [s for s in DESKTOP_STEPS if s[1] != configure_audio]
        return COMMON_STEPS + desktop_steps + SECURITY_STEPS + \
               DESKTOP_SECURITY_STEPS + CLI_STEPS + DESKTOP_APP_STEPS + FINAL_STEPS
    elif system_type == "workstation_dev":
        desktop_steps = [s for s in DESKTOP_STEPS if s[1] != configure_audio]
        return COMMON_STEPS + desktop_steps + SECURITY_STEPS + \
               DESKTOP_SECURITY_STEPS + CLI_STEPS + WORKSTATION_DEV_APP_STEPS + FINAL_STEPS
    elif system_type == "server_dev":
        return COMMON_STEPS + SECURITY_STEPS + CLI_STEPS + FINAL_STEPS
    elif system_type == "server_web":
        # Web server uses web-specific firewall that allows HTTP/HTTPS
        security_steps = [
            ("Hardening SSH configuration", harden_ssh),
            ("Hardening kernel parameters", harden_kernel),
            ("Configuring automatic security updates", configure_auto_updates),
        ]
        return COMMON_STEPS + WEB_FIREWALL_STEPS + security_steps + \
               WEB_SERVER_STEPS + CLI_STEPS + FINAL_STEPS
    elif system_type == "server_proxmox":
        # Proxmox systems are already installed, just apply hardening
        return SSH_FIREWALL_STEPS + PROXMOX_STEPS
    else:
        raise ValueError(f"Unknown system type: {system_type}")
