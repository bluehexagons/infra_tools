"""System type definitions and step configurations."""

from __future__ import annotations

from lib.config import SetupConfig
from lib.types import StepFunc

# Import from common module
from common.steps import (
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
    install_mail_utils,
    configure_swap,
)

# Import from desktop module
from desktop.steps import (
    install_desktop,
    install_xrdp,
    harden_xrdp,
    install_desktop_apps,
    configure_default_browser,
    install_workstation_dev_apps,
    configure_vivaldi_browser,
    configure_gnome_keyring,
    install_remmina,
    install_smbclient,
    install_office_apps,
    install_browser,
    configure_xfce_for_rdp,
)

# Import from security module
from security.steps import (
    create_remoteusers_group,
    configure_firewall,
    configure_fail2ban,
    harden_ssh,
    harden_kernel,
    configure_auto_updates,
    configure_firewall_web,
    configure_auto_restart,
)

# Import from web module
from web.steps import (
    install_nginx,
    configure_nginx_security,
    create_hello_world_site,
    configure_default_site,
    install_certbot,
    configure_cloudflare_firewall,
    create_cloudflared_config_directory,
    configure_nginx_for_cloudflare,
    install_cloudflared_service_helper,
    run_cloudflare_tunnel_setup,
    configure_auto_update_node,
    configure_auto_update_ruby,
)

# Import from smb module
from smb.steps import (
    install_samba,
    configure_samba_firewall,
    configure_samba_global_settings,
    configure_samba_fail2ban,
    setup_samba_share,
    configure_smb_mount,
)

# Import from sync module
from sync.steps import (
    install_rsync,
    create_sync_service,
    install_par2,
    create_scrub_service,
)


COMMON_STEPS: list[tuple[str, StepFunc]] = [
    ("Updating and upgrading packages", update_and_upgrade_packages),
    ("Ensuring sudo is installed", ensure_sudo_installed),
    ("Configuring UTF-8 locale", configure_locale),
    ("Creating remoteusers group", create_remoteusers_group),
    ("Setting up user", setup_user),
    ("Copying SSH keys to user", copy_ssh_keys_to_user),
    ("Generating SSH key for user", generate_ssh_key),
    ("Configuring time synchronization", configure_time_sync),
    ("Configuring swap", configure_swap),
]

DESKTOP_STEPS: list[tuple[str, StepFunc]] = [
    ("Installing desktop environment", install_desktop),
    ("Configuring desktop for RDP compatibility", configure_xfce_for_rdp),
    ("Installing xRDP", install_xrdp),
    ("Configuring gnome-keyring", configure_gnome_keyring),
]

DESKTOP_SECURITY_STEPS: list[tuple[str, StepFunc]] = [
    ("Hardening xRDP with TLS and group restrictions", harden_xrdp),
    ("Installing fail2ban for RDP brute-force protection", configure_fail2ban),
]

SECURITY_STEPS: list[tuple[str, StepFunc]] = [
    ("Configuring firewall", configure_firewall),
    ("Hardening SSH configuration", harden_ssh),
    ("Hardening kernel parameters", harden_kernel),
    ("Configuring automatic security updates", configure_auto_updates),
    ("Configuring automatic restart service", configure_auto_restart),
]

FINAL_STEPS: list[tuple[str, StepFunc]] = [
    ("Checking if restart required", check_restart_required),
]

CLI_STEPS: list[tuple[str, StepFunc]] = [
    ("Installing CLI tools", install_cli_tools),
]

DESKTOP_APP_STEPS: list[tuple[str, StepFunc]] = [
    ("Installing desktop applications", install_desktop_apps),
    ("Configuring default browser", configure_default_browser),
]

PC_DEV_APP_STEPS: list[tuple[str, StepFunc]] = [
    ("Installing Remmina", install_remmina),
    ("Installing desktop applications", install_desktop_apps),
    ("Configuring default browser", configure_default_browser),
]

WORKSTATION_DEV_APP_STEPS: list[tuple[str, StepFunc]] = [
    ("Installing workstation dev applications", install_workstation_dev_apps),
    ("Configuring default browser", configure_vivaldi_browser),
]

WEB_SERVER_STEPS: list[tuple[str, StepFunc]] = [
    ("Installing nginx", install_nginx),
    ("Configuring nginx security settings", configure_nginx_security),
    ("Creating Hello World website", create_hello_world_site),
    ("Configuring default site", configure_default_site),
]

WEB_FIREWALL_STEPS: list[tuple[str, StepFunc]] = [
    ("Configuring firewall for web server", configure_firewall_web),
]

PROXMOX_HARDENING_STEPS: list[tuple[str, StepFunc]] = [
    ("Creating remoteusers group", create_remoteusers_group),
    ("Configuring swap", configure_swap),
    ("Hardening SSH configuration", harden_ssh),
    ("Hardening kernel parameters", harden_kernel),
    ("Configuring automatic security updates", configure_auto_updates),
    ("Configuring automatic restart service", configure_auto_restart),
    ("Checking if restart required", check_restart_required),
]


STEP_FUNCTIONS: dict[str, StepFunc] = {
    'install_ruby': install_ruby,
    'install_go': install_go,
    'install_node': install_node,
    'install_certbot': install_certbot,
    'update_and_upgrade_packages': update_and_upgrade_packages,
    'ensure_sudo_installed': ensure_sudo_installed,
    'configure_locale': configure_locale,
    'setup_user': setup_user,
    'copy_ssh_keys_to_user': copy_ssh_keys_to_user,
    'generate_ssh_key': generate_ssh_key,
    'configure_time_sync': configure_time_sync,
    'install_cli_tools': install_cli_tools,
    'check_restart_required': check_restart_required,
    'install_desktop': install_desktop,
    'install_xrdp': install_xrdp,
    'harden_xrdp': harden_xrdp,
    'install_desktop_apps': install_desktop_apps,
    'configure_default_browser': configure_default_browser,
    'install_workstation_dev_apps': install_workstation_dev_apps,
    'configure_vivaldi_browser': configure_vivaldi_browser,
    'configure_gnome_keyring': configure_gnome_keyring,
    'install_smbclient': install_smbclient,
    'create_remoteusers_group': create_remoteusers_group,
    'configure_firewall': configure_firewall,
    'configure_fail2ban': configure_fail2ban,
    'harden_ssh': harden_ssh,
    'harden_kernel': harden_kernel,
    'configure_auto_updates': configure_auto_updates,
    'configure_auto_restart': configure_auto_restart,
    'configure_auto_update_node': configure_auto_update_node,
    'configure_auto_update_ruby': configure_auto_update_ruby,
    'configure_firewall_web': configure_firewall_web,
    'install_nginx': install_nginx,
    'configure_nginx_security': configure_nginx_security,
    'create_hello_world_site': create_hello_world_site,
    'configure_default_site': configure_default_site,
    'configure_swap': configure_swap,
    'configure_cloudflare_firewall': configure_cloudflare_firewall,
    'create_cloudflared_config_directory': create_cloudflared_config_directory,
    'configure_nginx_for_cloudflare': configure_nginx_for_cloudflare,
    'install_cloudflared_service_helper': install_cloudflared_service_helper,
    'run_cloudflare_tunnel_setup': run_cloudflare_tunnel_setup,
    'install_samba': install_samba,
    'configure_samba_firewall': configure_samba_firewall,
    'configure_samba_global_settings': configure_samba_global_settings,
    'configure_samba_fail2ban': configure_samba_fail2ban,
    'setup_samba_share': setup_samba_share,
    'configure_smb_mount': configure_smb_mount,
    'install_rsync': install_rsync,
    'create_sync_service': create_sync_service,
    'install_par2': install_par2,
    'create_scrub_service': create_scrub_service,
}


def get_steps_for_system_type(config: SetupConfig) -> list[tuple[str, StepFunc]]:
    """Build step list based on system type and feature flags.
    
    This function uses a declarative approach where each system type is defined
    by feature flags set in SetupConfig.from_args(). This makes it easier to
    audit what steps are included for each system type.
    """
    if config.system_type == "custom_steps" and config.custom_steps:
        step_names = config.custom_steps.split()
        steps: list[tuple[str, StepFunc]] = []
        for step_name in step_names:
            if step_name in STEP_FUNCTIONS:
                func = STEP_FUNCTIONS[step_name]
                steps.append((f"Running {step_name}", func))
            else:
                raise ValueError(f"Unknown step: {step_name}")
        return steps
    
    if config.system_type == "server_proxmox":
        return PROXMOX_HARDENING_STEPS
    
    steps = []
    
    steps.extend(COMMON_STEPS)
    
    if config.include_web_firewall:
        steps.extend(WEB_FIREWALL_STEPS)
    
    if config.system_type in ["server_web", "server_lite"]:
        security_steps: list[tuple[str, StepFunc]] = [
            ("Hardening SSH configuration", harden_ssh),
            ("Hardening kernel parameters", harden_kernel),
            ("Configuring automatic security updates", configure_auto_updates),
            ("Configuring automatic restart service", configure_auto_restart),
        ]
        steps.extend(security_steps)
    else:
        steps.extend(SECURITY_STEPS)
    
    if config.include_desktop:
        desktop_steps: list[tuple[str, StepFunc]] = []
        
        desktop_steps.append(("Installing desktop environment", install_desktop))
        
        if config.enable_rdp:
            desktop_steps.append(("Installing xRDP", install_xrdp))
        
        desktop_steps.append(("Configuring gnome-keyring", configure_gnome_keyring))
        
        if config.enable_smbclient:
            desktop_steps.append(("Installing SMB client packages", install_smbclient))
        
        steps.extend(desktop_steps)
        
        if config.enable_rdp:
            steps.append(("Hardening xRDP with TLS and group restrictions", harden_xrdp))
        if config.enable_rdp:
            steps.append(("Installing fail2ban for RDP brute-force protection", configure_fail2ban))
    
    if config.include_web_server:
        steps.extend(WEB_SERVER_STEPS)
    
    if config.include_cli_tools:
        steps.extend(CLI_STEPS)
    
    if config.install_ruby:
        steps.append(("Installing Ruby (rbenv + latest version)", install_ruby))
        steps.append(("Configuring Ruby auto-update", configure_auto_update_ruby))
    if config.install_go:
        steps.append(("Installing Go (latest version)", install_go))
    if config.install_node:
        steps.append(("Installing Node.js (nvm + latest LTS + PNPM)", install_node))
        steps.append(("Configuring Node.js auto-update", configure_auto_update_node))
    
    if config.include_desktop_apps:
        steps.extend(DESKTOP_APP_STEPS)
    elif config.include_pc_dev_apps:
        steps.extend(PC_DEV_APP_STEPS)
    elif config.include_workstation_dev_apps:
        steps.extend(WORKSTATION_DEV_APP_STEPS)
    
    if config.include_desktop and config.browser and not (config.include_desktop_apps or config.include_pc_dev_apps or config.include_workstation_dev_apps):
        steps.append(("Installing browser", install_browser))
        steps.append(("Configuring default browser", configure_default_browser))
    
    if config.install_office and not (config.include_desktop_apps or config.include_pc_dev_apps):
        steps.append(("Installing Office", install_office_apps))
    
    if config.notify_specs:
        steps.append(("Installing mail utilities for notifications", install_mail_utils))
    
    steps.extend(FINAL_STEPS)
    
    return steps
