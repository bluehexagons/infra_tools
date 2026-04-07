"""Web built-in capability plugin definitions and step helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from lib.plugin_registry import PluginDefinition

if TYPE_CHECKING:
    from lib.config import SetupConfig
    from lib.types import StepFunc


PLUGIN = PluginDefinition(
    name="web",
    module=__name__,
    plugin_kind="capability",
    dependencies=("core",),
)


def get_web_server_steps() -> list[tuple[str, StepFunc]]:
    """Return the default web-server setup steps."""

    from web.steps import (
        configure_default_site,
        configure_nginx_security,
        create_hello_world_site,
        install_nginx,
    )

    return [
        ("Installing nginx", install_nginx),
        ("Configuring nginx security settings", configure_nginx_security),
        ("Creating Hello World website", create_hello_world_site),
        ("Configuring default site", configure_default_site),
    ]


def extend_cicd_steps(config: SetupConfig, steps: list[tuple[str, StepFunc]]) -> None:
    """Append the CI/CD service setup steps when enabled."""

    from web.steps import (
        configure_nginx_for_webhook,
        create_cicd_directories,
        create_cicd_executor_service,
        create_cicd_user,
        create_default_webhook_config,
        create_webhook_receiver_service,
        generate_webhook_secret,
        install_cicd_dependencies,
        install_webhook_manager_helper,
        update_cloudflare_tunnel_for_webhook,
    )

    if not config.enable_cicd:
        return

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


def extend_app_server_steps(config: SetupConfig, steps: list[tuple[str, StepFunc]]) -> None:
    """Append app-server deployment steps when enabled."""

    from web.steps import (
        configure_app_nginx,
        configure_deploy_ssh_access,
        configure_deploy_sudoers,
        create_app_directories,
        create_deploy_user,
        install_app_server_dependencies,
    )

    if not config.is_app_server:
        return

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


def extend_build_server_steps(config: SetupConfig, steps: list[tuple[str, StepFunc]]) -> None:
    """Append build-server deployment steps when enabled."""

    from web.steps import (
        configure_deploy_known_hosts,
        configure_deploy_targets,
        configure_nginx_for_webhook,
        create_build_workspace_dirs,
        create_cicd_executor_service,
        create_cicd_user,
        create_default_webhook_config,
        create_webhook_receiver_service,
        generate_deploy_ssh_key,
        generate_webhook_secret,
        install_build_dependencies,
        install_cicd_dependencies,
        install_webhook_manager_helper,
        update_cloudflare_tunnel_for_webhook,
    )

    if not config.is_build_server:
        return

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
