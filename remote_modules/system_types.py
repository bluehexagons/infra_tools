"""System type definitions and step configurations."""

from lib.config import SetupConfig
from .common_steps import (
    update_and_upgrade_packages,
    ensure_sudo_installed,
    configure_locale,
    setup_user,
    copy_ssh_keys_to_user,
    generate_ssh_key,
    configure_time_sync,
    install_cli_tools,
    check_restart_required,
    install_ruby as install_ruby_step,
    install_go as install_go_step,
    install_node as install_node_step,
    configure_auto_update_node,
    configure_auto_update_ruby,
)
from .desktop_steps import (
    install_desktop,
    install_xrdp,
    harden_xrdp,
    install_x2go,
    configure_xfce_for_x2go,
    harden_x2go,
    configure_audio,
    install_desktop_apps,
    configure_default_browser,
    install_workstation_dev_apps,
    configure_vivaldi_browser,
    configure_gnome_keyring,
    install_remmina,
)
from .security_steps import (
    create_remoteusers_group,
    configure_firewall,
    configure_fail2ban,
    harden_ssh,
    harden_kernel,
    configure_auto_updates,
    configure_firewall_web,
    configure_auto_restart,
)
from .web_steps import (
    install_nginx,
    configure_nginx_security,
    create_hello_world_site,
    configure_default_site,
)
from .swap_steps import configure_swap
from .ssl_steps import install_certbot
from .cloudflare_steps import (
    configure_cloudflare_firewall,
    create_cloudflared_config_directory,
    configure_nginx_for_cloudflare,
    install_cloudflared_service_helper,
    run_cloudflare_tunnel_setup,
)
from .samba_steps import (
    install_samba,
    configure_samba_firewall,
    configure_samba_global_settings,
    configure_samba_fail2ban,
    setup_samba_share,
)


COMMON_STEPS = [
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

DESKTOP_STEPS = [
    ("Installing desktop environment", install_desktop),
    ("Installing xRDP", install_xrdp),
    ("Installing X2Go", install_x2go),
    ("Configuring Xfce for X2Go", configure_xfce_for_x2go),
    ("Configuring audio for RDP", configure_audio),
    ("Configuring gnome-keyring", configure_gnome_keyring),
]

DESKTOP_SECURITY_STEPS = [
    ("Hardening xRDP with TLS and group restrictions", harden_xrdp),
    ("Hardening X2Go access", harden_x2go),
    ("Installing fail2ban for RDP brute-force protection", configure_fail2ban),
]

SECURITY_STEPS = [
    ("Configuring firewall", configure_firewall),
    ("Hardening SSH configuration", harden_ssh),
    ("Hardening kernel parameters", harden_kernel),
    ("Configuring automatic security updates", configure_auto_updates),
    ("Configuring automatic restart service", configure_auto_restart),
]

FINAL_STEPS = [
    ("Checking if restart required", check_restart_required),
]

CLI_STEPS = [
    ("Installing CLI tools", install_cli_tools),
]

DESKTOP_APP_STEPS = [
    ("Installing desktop applications", install_desktop_apps),
    ("Configuring default browser", configure_default_browser),
]

PC_DEV_APP_STEPS = [
    ("Installing Remmina", install_remmina),
    ("Installing desktop applications", install_desktop_apps),
    ("Configuring default browser", configure_default_browser),
]

WORKSTATION_DEV_APP_STEPS = [
    ("Installing workstation dev applications", install_workstation_dev_apps),
    ("Configuring default browser", configure_vivaldi_browser),
]

WEB_SERVER_STEPS = [
    ("Installing nginx", install_nginx),
    ("Configuring nginx security settings", configure_nginx_security),
    ("Creating Hello World website", create_hello_world_site),
    ("Configuring default site", configure_default_site),
]

WEB_FIREWALL_STEPS = [
    ("Configuring firewall for web server", configure_firewall_web),
]

PROXMOX_HARDENING_STEPS = [
    ("Creating remoteusers group", create_remoteusers_group),
    ("Configuring swap", configure_swap),
    ("Hardening SSH configuration", harden_ssh),
    ("Hardening kernel parameters", harden_kernel),
    ("Configuring automatic security updates", configure_auto_updates),
    ("Configuring automatic restart service", configure_auto_restart),
    ("Checking if restart required", check_restart_required),
]


STEP_FUNCTIONS = {
    'install_ruby': install_ruby_step,
    'install_go': install_go_step,
    'install_node': install_node_step,
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
    'install_x2go': install_x2go,
    'configure_xfce_for_x2go': configure_xfce_for_x2go,
    'harden_x2go': harden_x2go,
    'configure_audio': configure_audio,
    'install_desktop_apps': install_desktop_apps,
    'configure_default_browser': configure_default_browser,
    'install_workstation_dev_apps': install_workstation_dev_apps,
    'configure_vivaldi_browser': configure_vivaldi_browser,
    'configure_gnome_keyring': configure_gnome_keyring,
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
}


def get_steps_for_system_type(config: SetupConfig) -> list:
    if config.system_type == "custom_steps" and config.custom_steps:
        step_names = config.custom_steps.split()
        steps = []
        for step_name in step_names:
            if step_name in STEP_FUNCTIONS:
                func = STEP_FUNCTIONS[step_name]
                steps.append((f"Running {step_name}", func))
            else:
                raise ValueError(f"Unknown step: {step_name}")
        return steps
    
    optional_steps = []
    if config.install_ruby:
        optional_steps.append(("Installing Ruby (rbenv + latest version)", install_ruby_step))
        optional_steps.append(("Configuring Ruby auto-update", configure_auto_update_ruby))
    if config.install_go:
        optional_steps.append(("Installing Go (latest version)", install_go_step))
    if config.install_node:
        optional_steps.append(("Installing Node.js (nvm + latest LTS + PNPM)", install_node_step))
        optional_steps.append(("Configuring Node.js auto-update", configure_auto_update_node))
    
    if config.system_type == "workstation_desktop":
        # Build desktop steps based on enabled remote access methods
        desktop_steps = list(DESKTOP_STEPS)
        if not config.enable_rdp:
            desktop_steps = [s for s in desktop_steps if s[1] != install_xrdp]
        if not config.enable_x2go:
            desktop_steps = [s for s in desktop_steps if s[1] not in [install_x2go, configure_xfce_for_x2go]]
        if config.desktop != "xfce":
            desktop_steps = [s for s in desktop_steps if s[1] != configure_xfce_for_x2go]
        if not config.enable_audio:
            desktop_steps = [s for s in desktop_steps if s[1] != configure_audio]
        
        # Build security steps
        security_steps = SECURITY_STEPS
        desktop_security_steps = []
        if config.enable_rdp:
            desktop_security_steps.append(("Hardening xRDP with TLS and group restrictions", harden_xrdp))
        if config.enable_x2go:
            desktop_security_steps.append(("Hardening X2Go access", harden_x2go))
        if config.enable_rdp:  # fail2ban is for RDP brute-force protection
            desktop_security_steps.append(("Installing fail2ban for RDP brute-force protection", configure_fail2ban))
        
        return COMMON_STEPS + desktop_steps + security_steps + \
               desktop_security_steps + CLI_STEPS + optional_steps + DESKTOP_APP_STEPS + FINAL_STEPS
    elif config.system_type == "pc_dev":
        # Build desktop steps based on enabled remote access methods
        desktop_steps = list(DESKTOP_STEPS)
        if not config.enable_rdp:
            desktop_steps = [s for s in desktop_steps if s[1] != install_xrdp]
        if not config.enable_x2go:
            desktop_steps = [s for s in desktop_steps if s[1] not in [install_x2go, configure_xfce_for_x2go]]
        if config.desktop != "xfce":
            desktop_steps = [s for s in desktop_steps if s[1] != configure_xfce_for_x2go]
        if not config.enable_audio:
            desktop_steps = [s for s in desktop_steps if s[1] != configure_audio]
        
        # Build security steps
        security_steps = SECURITY_STEPS
        desktop_security_steps = []
        if config.enable_rdp:
            desktop_security_steps.append(("Hardening xRDP with TLS and group restrictions", harden_xrdp))
        if config.enable_x2go:
            desktop_security_steps.append(("Hardening X2Go access", harden_x2go))
        if config.enable_rdp:
            desktop_security_steps.append(("Installing fail2ban for RDP brute-force protection", configure_fail2ban))
        
        return COMMON_STEPS + desktop_steps + security_steps + \
               desktop_security_steps + CLI_STEPS + optional_steps + PC_DEV_APP_STEPS + FINAL_STEPS
    elif config.system_type == "workstation_dev":
        # Build desktop steps
        desktop_steps = list(DESKTOP_STEPS)
        if not config.enable_rdp:
            desktop_steps = [s for s in desktop_steps if s[1] != install_xrdp]
        if not config.enable_x2go:
            desktop_steps = [s for s in desktop_steps if s[1] not in [install_x2go, configure_xfce_for_x2go]]
        if config.desktop != "xfce":
            desktop_steps = [s for s in desktop_steps if s[1] != configure_xfce_for_x2go]
        if not config.enable_audio:
            desktop_steps = [s for s in desktop_steps if s[1] != configure_audio]
        
        # Build security steps
        security_steps = SECURITY_STEPS
        desktop_security_steps = []
        if config.enable_rdp:
            desktop_security_steps.append(("Hardening xRDP with TLS and group restrictions", harden_xrdp))
        if config.enable_x2go:
            desktop_security_steps.append(("Hardening X2Go access", harden_x2go))
        if config.enable_rdp:
            desktop_security_steps.append(("Installing fail2ban for RDP brute-force protection", configure_fail2ban))
        
        return COMMON_STEPS + desktop_steps + security_steps + \
               desktop_security_steps + CLI_STEPS + optional_steps + WORKSTATION_DEV_APP_STEPS + FINAL_STEPS
    elif config.system_type == "server_dev":
        return COMMON_STEPS + SECURITY_STEPS + CLI_STEPS + optional_steps + FINAL_STEPS
    elif config.system_type == "server_web":
        security_steps = [
            ("Hardening SSH configuration", harden_ssh),
            ("Hardening kernel parameters", harden_kernel),
            ("Configuring automatic security updates", configure_auto_updates),
            ("Configuring automatic restart service", configure_auto_restart),
        ]
        return COMMON_STEPS + WEB_FIREWALL_STEPS + security_steps + \
               WEB_SERVER_STEPS + CLI_STEPS + optional_steps + FINAL_STEPS
    elif config.system_type == "server_proxmox":
        return PROXMOX_HARDENING_STEPS
    else:
        raise ValueError(f"Unknown system type: {config.system_type}")
