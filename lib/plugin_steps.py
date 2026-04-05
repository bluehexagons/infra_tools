"""Shared step catalogs and step builders for built-in plugins."""

from __future__ import annotations

from typing import TYPE_CHECKING

from lib.types import StepFunc

if TYPE_CHECKING:
    from lib.config import SetupConfig

from common.steps import (
    check_restart_required,
    configure_auto_update_ruby,
    configure_auto_update_uv,
    configure_locale,
    configure_swap,
    configure_time_sync,
    copy_ssh_keys_to_user,
    ensure_sudo_installed,
    generate_ssh_key,
    install_apt_packages,
    install_cli_tools,
    install_flatpak_packages,
    install_go,
    install_mail_utils,
    install_node,
    install_python,
    install_ruby,
    setup_user,
    update_and_upgrade_packages,
)
from desktop.steps import (
    configure_dark_theme,
    configure_default_browser,
    configure_vivaldi_browser,
    configure_xfce_for_rdp,
    harden_xrdp,
    install_browser,
    install_desktop,
    install_desktop_apps,
    install_office_apps,
    install_remmina,
    install_smbclient,
    install_workstation_dev_apps,
    install_xrdp,
)
from security.steps import (
    configure_auto_restart,
    configure_auto_updates,
    configure_cleanup_maintenance,
    configure_fail2ban,
    configure_firewall,
    configure_firewall_web,
    create_remoteusers_group,
    harden_kernel,
    harden_ssh,
)
from smb.steps import (
    configure_samba_fail2ban,
    configure_samba_firewall,
    configure_samba_global_settings,
    configure_smb_mount,
    install_samba,
    setup_samba_share,
)
from sync.steps import create_scrub_service, create_sync_service, install_par2, install_rsync
from web.steps import (
    configure_app_nginx,
    configure_auto_update_node,
    configure_cloudflare_firewall,
    configure_deploy_targets,
    configure_deploy_known_hosts,
    configure_deploy_ssh_access,
    configure_deploy_sudoers,
    configure_default_site,
    configure_nginx_for_cloudflare,
    configure_nginx_for_webhook,
    configure_nginx_security,
    create_app_directories,
    create_build_workspace_dirs,
    create_cicd_directories,
    create_cicd_executor_service,
    create_cicd_user,
    create_cloudflared_config_directory,
    create_default_webhook_config,
    create_deploy_user,
    create_hello_world_site,
    create_webhook_receiver_service,
    generate_deploy_ssh_key,
    generate_webhook_secret,
    install_app_server_dependencies,
    install_build_dependencies,
    install_certbot,
    install_cicd_dependencies,
    install_cloudflared_service_helper,
    install_nginx,
    install_webhook_manager_helper,
    run_cloudflare_tunnel_setup,
    update_cloudflare_tunnel_for_webhook,
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

SECURITY_STEPS: list[tuple[str, StepFunc]] = [
    ("Configuring firewall", configure_firewall),
    ("Hardening SSH configuration", harden_ssh),
    ("Hardening kernel parameters", harden_kernel),
    ("Configuring automatic security updates", configure_auto_updates),
    ("Configuring cleanup maintenance service", configure_cleanup_maintenance),
    ("Configuring automatic restart service", configure_auto_restart),
]

LITE_SECURITY_STEPS: list[tuple[str, StepFunc]] = [
    ("Hardening SSH configuration", harden_ssh),
    ("Hardening kernel parameters", harden_kernel),
    ("Configuring automatic security updates", configure_auto_updates),
    ("Configuring cleanup maintenance service", configure_cleanup_maintenance),
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
    ("Configuring cleanup maintenance service", configure_cleanup_maintenance),
    ("Configuring automatic restart service", configure_auto_restart),
    ("Checking if restart required", check_restart_required),
]

STEP_FUNCTIONS: dict[str, StepFunc] = {
    "install_ruby": install_ruby,
    "install_go": install_go,
    "install_node": install_node,
    "install_python": install_python,
    "configure_auto_update_uv": configure_auto_update_uv,
    "install_certbot": install_certbot,
    "update_and_upgrade_packages": update_and_upgrade_packages,
    "ensure_sudo_installed": ensure_sudo_installed,
    "configure_locale": configure_locale,
    "setup_user": setup_user,
    "copy_ssh_keys_to_user": copy_ssh_keys_to_user,
    "generate_ssh_key": generate_ssh_key,
    "configure_time_sync": configure_time_sync,
    "install_cli_tools": install_cli_tools,
    "check_restart_required": check_restart_required,
    "install_desktop": install_desktop,
    "install_xrdp": install_xrdp,
    "harden_xrdp": harden_xrdp,
    "install_desktop_apps": install_desktop_apps,
    "configure_default_browser": configure_default_browser,
    "install_workstation_dev_apps": install_workstation_dev_apps,
    "configure_vivaldi_browser": configure_vivaldi_browser,
    "install_smbclient": install_smbclient,
    "configure_dark_theme": configure_dark_theme,
    "install_apt_packages": install_apt_packages,
    "install_flatpak_packages": install_flatpak_packages,
    "create_remoteusers_group": create_remoteusers_group,
    "configure_firewall": configure_firewall,
    "configure_fail2ban": configure_fail2ban,
    "harden_ssh": harden_ssh,
    "harden_kernel": harden_kernel,
    "configure_auto_updates": configure_auto_updates,
    "configure_cleanup_maintenance": configure_cleanup_maintenance,
    "configure_auto_restart": configure_auto_restart,
    "configure_auto_update_node": configure_auto_update_node,
    "configure_auto_update_ruby": configure_auto_update_ruby,
    "configure_firewall_web": configure_firewall_web,
    "install_nginx": install_nginx,
    "configure_nginx_security": configure_nginx_security,
    "create_hello_world_site": create_hello_world_site,
    "configure_default_site": configure_default_site,
    "configure_swap": configure_swap,
    "configure_cloudflare_firewall": configure_cloudflare_firewall,
    "create_cloudflared_config_directory": create_cloudflared_config_directory,
    "configure_nginx_for_cloudflare": configure_nginx_for_cloudflare,
    "install_cloudflared_service_helper": install_cloudflared_service_helper,
    "run_cloudflare_tunnel_setup": run_cloudflare_tunnel_setup,
    "install_cicd_dependencies": install_cicd_dependencies,
    "create_cicd_user": create_cicd_user,
    "create_cicd_directories": create_cicd_directories,
    "generate_webhook_secret": generate_webhook_secret,
    "create_default_webhook_config": create_default_webhook_config,
    "create_webhook_receiver_service": create_webhook_receiver_service,
    "create_cicd_executor_service": create_cicd_executor_service,
    "configure_nginx_for_webhook": configure_nginx_for_webhook,
    "update_cloudflare_tunnel_for_webhook": update_cloudflare_tunnel_for_webhook,
    "install_webhook_manager_helper": install_webhook_manager_helper,
    "install_app_server_dependencies": install_app_server_dependencies,
    "create_deploy_user": create_deploy_user,
    "configure_deploy_sudoers": configure_deploy_sudoers,
    "create_app_directories": create_app_directories,
    "configure_deploy_ssh_access": configure_deploy_ssh_access,
    "configure_app_nginx": configure_app_nginx,
    "generate_deploy_ssh_key": generate_deploy_ssh_key,
    "configure_deploy_targets": configure_deploy_targets,
    "configure_deploy_known_hosts": configure_deploy_known_hosts,
    "create_build_workspace_dirs": create_build_workspace_dirs,
    "install_build_dependencies": install_build_dependencies,
    "install_samba": install_samba,
    "configure_samba_firewall": configure_samba_firewall,
    "configure_samba_global_settings": configure_samba_global_settings,
    "configure_samba_fail2ban": configure_samba_fail2ban,
    "setup_samba_share": setup_samba_share,
    "configure_smb_mount": configure_smb_mount,
    "install_rsync": install_rsync,
    "create_sync_service": create_sync_service,
    "install_par2": install_par2,
    "create_scrub_service": create_scrub_service,
}


def build_custom_steps(config: SetupConfig) -> list[tuple[str, StepFunc]]:
    """Build an explicit custom step list."""

    if not config.custom_steps:
        return []

    steps: list[tuple[str, StepFunc]] = []
    for step_name in config.custom_steps.split():
        if step_name not in STEP_FUNCTIONS:
            raise ValueError(f"Unknown step: {step_name}")
        steps.append((f"Running {step_name}", STEP_FUNCTIONS[step_name]))
    return steps


def build_server_proxmox_steps(_: SetupConfig) -> list[tuple[str, StepFunc]]:
    """Build the dedicated Proxmox hardening step list."""

    return list(PROXMOX_HARDENING_STEPS)


def build_standard_steps(config: SetupConfig) -> list[tuple[str, StepFunc]]:
    """Build standard setup steps from registry-driven feature flags."""

    steps: list[tuple[str, StepFunc]] = list(COMMON_STEPS)

    if config.include_web_firewall:
        steps.extend(WEB_FIREWALL_STEPS)

    if config.system_type in ["server_web", "server_lite"]:
        steps.extend(LITE_SECURITY_STEPS)
    else:
        steps.extend(SECURITY_STEPS)

    if config.include_desktop:
        steps.append(("Installing desktop environment", install_desktop))
        if config.enable_rdp:
            steps.append(("Installing xRDP", install_xrdp))
            steps.append(("Configuring desktop for RDP compatibility", configure_xfce_for_rdp))
        if config.enable_smbclient:
            steps.append(("Installing SMB client packages", install_smbclient))
        if config.dark_theme:
            steps.append(("Configuring dark theme", configure_dark_theme))
        if config.enable_rdp:
            steps.append(("Hardening xRDP with TLS and group restrictions", harden_xrdp))
            steps.append(("Installing fail2ban for RDP brute-force protection", configure_fail2ban))

    if config.include_web_server:
        steps.extend(WEB_SERVER_STEPS)

    if config.include_cli_tools:
        steps.extend(CLI_STEPS)

    if config.install_ruby:
        steps.append(("Installing Ruby (apt packages)", install_ruby))
        steps.append(("Configuring Ruby auto-update", configure_auto_update_ruby))
    if config.install_go:
        steps.append(("Installing Go (latest version)", install_go))
    if config.install_node:
        steps.append(("Installing Node.js (nvm + latest LTS + PNPM)", install_node))
        steps.append(("Configuring Node.js auto-update", configure_auto_update_node))
    if config.install_python:
        steps.append(("Installing Python tooling (aliases + uv)", install_python))
        steps.append(("Configuring uv auto-update", configure_auto_update_uv))

    if config.include_desktop_apps:
        steps.extend(DESKTOP_APP_STEPS)
    elif config.include_pc_dev_apps:
        steps.extend(PC_DEV_APP_STEPS)
    elif config.include_workstation_dev_apps:
        steps.extend(WORKSTATION_DEV_APP_STEPS)

    if config.include_desktop and (config.browser or config.browsers) and not (
        config.include_desktop_apps or config.include_pc_dev_apps or config.include_workstation_dev_apps
    ):
        steps.append(("Installing browser", install_browser))
        steps.append(("Configuring default browser", configure_default_browser))

    if config.install_office and not (config.include_desktop_apps or config.include_pc_dev_apps):
        steps.append(("Installing Office", install_office_apps))

    if config.apt_packages:
        steps.append(("Installing custom apt packages", install_apt_packages))

    if config.flatpak_packages:
        steps.append(("Installing custom flatpak packages", install_flatpak_packages))

    if config.notify_specs:
        steps.append(("Installing mail utilities for notifications", install_mail_utils))

    if config.enable_cicd:
        steps.extend(
            [
                ("Installing CI/CD dependencies", install_cicd_dependencies),
                ("Creating CI/CD user", create_cicd_user),
                ("Creating CI/CD directories", create_cicd_directories),
                ("Generating webhook secret", generate_webhook_secret),
                ("Creating default webhook configuration", create_default_webhook_config),
                ("Creating webhook receiver service", create_webhook_receiver_service),
                ("Creating CI/CD executor service", create_cicd_executor_service),
                ("Configuring nginx for webhook endpoint", configure_nginx_for_webhook),
                ("Updating Cloudflare tunnel for webhook", update_cloudflare_tunnel_for_webhook),
                ("Installing webhook manager helper", install_webhook_manager_helper),
            ]
        )

    if config.is_app_server:
        steps.extend(
            [
                ("Installing app server dependencies", install_app_server_dependencies),
                ("Creating deploy user", create_deploy_user),
                ("Configuring deploy sudoers", configure_deploy_sudoers),
                ("Creating app directories", create_app_directories),
                ("Configuring deploy SSH access", configure_deploy_ssh_access),
                ("Configuring nginx for app server", configure_app_nginx),
            ]
        )

    if config.is_build_server:
        steps.extend(
            [
                ("Installing build dependencies", install_build_dependencies),
                ("Installing CI/CD dependencies", install_cicd_dependencies),
                ("Creating CI/CD user", create_cicd_user),
                ("Creating build workspace directories", create_build_workspace_dirs),
                ("Generating webhook secret", generate_webhook_secret),
                ("Creating default webhook configuration", create_default_webhook_config),
                ("Creating webhook receiver service", create_webhook_receiver_service),
                ("Creating CI/CD executor service", create_cicd_executor_service),
                ("Generating deploy SSH key", generate_deploy_ssh_key),
                ("Configuring deploy targets", configure_deploy_targets),
                ("Configuring deploy known hosts", configure_deploy_known_hosts),
                ("Configuring nginx for webhook endpoint", configure_nginx_for_webhook),
                ("Updating Cloudflare tunnel for webhook", update_cloudflare_tunnel_for_webhook),
                ("Installing webhook manager helper", install_webhook_manager_helper),
            ]
        )

    steps.extend(FINAL_STEPS)
    return steps
