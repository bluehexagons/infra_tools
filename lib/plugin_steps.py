"""Custom step catalog for the core plugin."""

from __future__ import annotations

from typing import TYPE_CHECKING

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
    configure_deploy_known_hosts,
    configure_deploy_ssh_access,
    configure_deploy_sudoers,
    configure_deploy_targets,
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
    install_cloudflared_service_helper,
    install_cicd_dependencies,
    install_nginx,
    install_webhook_manager_helper,
    run_cloudflare_tunnel_setup,
    update_cloudflare_tunnel_for_webhook,
)

if TYPE_CHECKING:
    from lib.config import SetupConfig
    from lib.types import StepFunc


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
