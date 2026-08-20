#!/usr/bin/env python3

from __future__ import annotations

import argparse
import ipaddress
import shlex
from dataclasses import dataclass, asdict
from typing import Optional, cast
from lib.plugin_registry import get_system_type_definition, get_system_type_names
from lib.types import StrList, NestedStrList, JSONDict, MaybeStr


SYSTEM_TYPES = get_system_type_names()

AUTO_MACHINE_TYPE = "auto"
MACHINE_TYPES = [AUTO_MACHINE_TYPE, "unprivileged", "vm", "privileged", "hardware", "oci"]
DEFAULT_MACHINE_TYPE = AUTO_MACHINE_TYPE

DESKTOP_SYSTEMS = [
    system_type.name
    for system_type in (get_system_type_definition(name) for name in SYSTEM_TYPES)
    if system_type.include_desktop
]
CLI_SYSTEMS = [
    system_type.name
    for system_type in (get_system_type_definition(name) for name in SYSTEM_TYPES)
    if system_type.include_cli_tools
]

AGENT_TOOLS = ("gh", "codex", "claude", "opencode")
DESKTOP_INTERFACES = ("t3code",)
WEB_INTERFACES = ("t3code",)
DEVICE_PAIRING_PROVIDERS = ("t3code",)
BROWSER_AUTOMATION_PROVIDERS = ("playwright",)
GIT_ACCESS_POLICIES = ("none", "read", "read-write")


def _resolve_machine_type(
    args: argparse.Namespace,
    *,
    is_hosted: bool,
) -> str:
    explicit_machine_type = getattr(args, "machine_type", None)
    if explicit_machine_type:
        return explicit_machine_type

    # Proxmox provisioning creates a guest before remote setup runs, so it cannot use
    # target-side detection. Keep the existing VM default for that path;
    # callers can select an LXC explicitly with --machine unprivileged.
    if is_hosted:
        return "vm"

    return DEFAULT_MACHINE_TYPE


def _default_machine_type_for_setup(
    system_type: str,
    *,
    is_build_server: bool = False,
) -> str:
    del system_type, is_build_server
    return DEFAULT_MACHINE_TYPE


def _validate_non_negative_int(name: str, value: int) -> int:
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _optional_bool_arg(args: argparse.Namespace, name: str) -> Optional[bool]:
    value = getattr(args, name, None)
    return value if isinstance(value, bool) else None


def _optional_int_arg(args: argparse.Namespace, name: str) -> Optional[int]:
    value = getattr(args, name, None)
    return value if isinstance(value, int) else None


def _optional_str_arg(args: argparse.Namespace, name: str) -> Optional[str]:
    value = getattr(args, name, None)
    return value if isinstance(value, str) else None


def _normalize_nested_specs(value: NestedStrList | list[str] | None) -> Optional[NestedStrList]:
    if not value:
        return None

    if isinstance(value, list) and value and isinstance(value[0], str):
        normalized: NestedStrList = []
        normalized.append(cast(list[str], value))
        return normalized

    if isinstance(value, list):
        normalized: NestedStrList = []
        for spec in value:
            normalized.append(cast(list[str], spec))
        return normalized

    return None


def _strip_passwords_from_share_users(users_field: str) -> str:
    sanitized_users: StrList = []
    for user_spec in users_field.split(','):
        normalized_user = user_spec.strip()
        if not normalized_user:
            continue
        if ':' in normalized_user:
            username, _ = normalized_user.split(':', 1)
            sanitized_users.append(username.strip())
        else:
            sanitized_users.append(normalized_user)
    return ','.join(sanitized_users)


def redact_share_user_passwords(users_field: str) -> str:
    redacted_users: StrList = []
    for user_spec in users_field.split(','):
        normalized_user = user_spec.strip()
        if not normalized_user:
            continue
        if ':' in normalized_user:
            username, _ = normalized_user.split(':', 1)
            redacted_users.append(f"{username.strip()}:[REDACTED]")
        else:
            redacted_users.append(normalized_user)
    return ','.join(redacted_users)


def _strip_passwords_from_samba_shares(value: Optional[NestedStrList]) -> Optional[NestedStrList]:
    if not value:
        return value

    sanitized_shares: NestedStrList = []
    for share_spec in value:
        sanitized_share = list(share_spec)
        if len(sanitized_share) >= 4:
            sanitized_share[3] = _strip_passwords_from_share_users(sanitized_share[3])
        sanitized_shares.append(sanitized_share)
    return sanitized_shares


def _strip_passwords_from_smb_mounts(value: Optional[NestedStrList]) -> Optional[NestedStrList]:
    if not value:
        return value

    sanitized_mounts: NestedStrList = []
    for mount_spec in value:
        sanitized_mount = list(mount_spec)
        if len(sanitized_mount) >= 3 and ':' in sanitized_mount[2]:
            username, _ = sanitized_mount[2].split(':', 1)
            sanitized_mount[2] = username.strip()
        sanitized_mounts.append(sanitized_mount)
    return sanitized_mounts


def redact_mount_credentials(credentials_field: str) -> str:
    if ':' not in credentials_field:
        return credentials_field
    username, _ = credentials_field.split(':', 1)
    return f"{username}:[REDACTED]"


@dataclass
class SetupConfig:
    """Configuration for system setup.
    
    Note on browser fields:
    - browser: The primary/default browser. If browsers list is set, this will be browsers[0]
    - browsers: Optional list of browsers to install. When set, browser is the first element
    """
    host: str
    username: str
    system_type: str
    machine_type: str = DEFAULT_MACHINE_TYPE
    password: MaybeStr = None
    ssh_key: MaybeStr = None
    timezone: str = "UTC"
    system_hostname: MaybeStr = None
    static_ipv4: MaybeStr = None
    static_ipv6: MaybeStr = None
    network_gateway4: MaybeStr = None
    network_gateway6: MaybeStr = None
    network_dns: Optional[StrList] = None
    network_interface: MaybeStr = None
    activate_network: bool = False
    friendly_name: MaybeStr = None
    tags: Optional[StrList] = None
    enable_rdp: bool = False
    rdp_existing_password: bool = False
    rdp_bind_address: str = "0.0.0.0"
    rdp_allowed_sources: Optional[StrList] = None
    rdp_clipboard: bool = True
    rdp_drive_redirection: bool = False
    rdp_audio: bool = False
    rdp_max_sessions: int = 10
    rdp_kill_disconnected: bool = False
    rdp_disconnected_timeout: int = 0
    rdp_idle_timeout: int = 0
    desktop: str = "xfce"
    browser: Optional[str] = "librewolf"  # Primary browser, or first from browsers list
    browsers: Optional[StrList] = None  # List of browsers to install
    use_flatpak: bool = False
    install_office: bool = False
    apt_packages: Optional[StrList] = None
    flatpak_packages: Optional[StrList] = None
    dark_theme: bool = False
    dry_run: bool = False
    refresh_packages: bool = False
    install_ruby: bool = False
    install_go: bool = False
    install_node: bool = False
    install_python: bool = False
    install_gh: bool = False
    install_codex: bool = False
    install_claude: bool = False
    install_opencode: bool = False
    agent_tools: Optional[StrList] = None
    desktop_interfaces: Optional[StrList] = None
    web_interfaces: Optional[StrList] = None
    web_interface_host: MaybeStr = None
    web_interface_port: int = 3773
    web_interface_sources: Optional[StrList] = None
    device_pairing_providers: Optional[StrList] = None
    device_pairing_port: int = 3774
    device_pairing_auth_file: MaybeStr = None
    device_pairing_auth_username: MaybeStr = None
    device_pairing_auth_password: MaybeStr = None
    device_pairing_payload: bool = False
    disable_device_pairing: bool = False
    browser_automation: MaybeStr = None
    copy_agent_keys: bool = False
    copy_agent_config: bool = False
    agent_repos: Optional[StrList] = None
    git_access: str = "none"
    git_host: str = "github.com"
    git_auth_source: MaybeStr = None
    git_auth_file: MaybeStr = None
    git_auth_token: MaybeStr = None
    agent_auth_source: MaybeStr = None
    agent_auth_files: Optional[NestedStrList] = None
    agent_config_source: MaybeStr = None
    agent_payload: bool = False
    agent_workspace: MaybeStr = None
    install_git_lfs: bool = False
    custom_steps: Optional[str] = None
    deploy_specs: Optional[NestedStrList] = None
    deployment_mode: str = "default"  # "default" (smart cache), "lite" (cached only), "full" (always fresh)
    full_deploy: bool = False
    deploy_latest: bool = False
    reset_migrations: bool = False
    enable_ssl: bool = False
    ssl_email: Optional[str] = None
    enable_cloudflare: bool = False
    enable_cicd: bool = False
    is_build_server: bool = False
    is_app_server: bool = False
    deploy_targets: Optional[StrList] = None
    api_subdomain: bool = False
    enable_samba: bool = False
    samba_shares: Optional[NestedStrList] = None
    share_credentials: Optional[NestedStrList] = None
    enable_smbclient: bool = False
    smb_mounts: Optional[NestedStrList] = None
    sync_specs: Optional[NestedStrList] = None
    backup_specs: Optional[NestedStrList] = None
    scrub_specs: Optional[NestedStrList] = None
    notify_specs: Optional[NestedStrList] = None
    antistatic_server: MaybeStr = None  # "DOMAIN[:port]" spec
    antistatic_admin: MaybeStr = None  # Username; password stays in the credential store
    antistatic_db: MaybeStr = None  # "DOMAIN[:port]" spec
    gogs: Optional[StrList] = None  # ["DOMAIN[:port]", "DATA_PATH"?]
    gogs_sources: Optional[StrList] = None
    auto_restart: bool = True
    auto_restart_force_days: int = 7
    auto_restart_grace: int = 5
    # Proxmox guest provisioning
    hosted_node: MaybeStr = None
    hosted_user: str = "root"
    hosted_key: MaybeStr = None
    hosted_bridge: MaybeStr = None
    container_memory: MaybeStr = None
    vm_balloon_min: MaybeStr = None
    container_storage: Optional[NestedStrList] = None  # [[name, pool, amount?], ...]
    storage_mounts: Optional[NestedStrList] = None  # [[name, path, filesystem?, policy?], ...]
    container_cores: int = 1
    container_base: str = "debian"
    vm_image: MaybeStr = None  # HTTPS URL or 'storage:import/file.qcow2'
    vm_image_sha512: MaybeStr = None  # Required for custom HTTPS VM images
    vm_image_storage: MaybeStr = None  # Storage for downloaded VM image sources
    include_desktop: bool = False
    include_cli_tools: bool = False
    include_control_plane_tools: bool = False
    include_desktop_apps: bool = False
    include_workstation_dev_apps: bool = False
    include_pc_dev_apps: bool = False
    include_web_server: bool = False
    include_web_firewall: bool = False

    def __post_init__(self) -> None:
        # "full" deployment mode means "always pull fresh repositories and
        # rebuild everything" (a full redeploy). That necessarily implies
        # full_deploy, so keep the two in sync. Without this, passing
        # --deployment-full alone would still report "Full deploy: No" and
        # should_redeploy() could skip unchanged deployments, contradicting
        # the requested full redeploy.
        if self.deployment_mode == "full":
            self.full_deploy = True

        if self.git_access not in GIT_ACCESS_POLICIES:
            raise ValueError(
                f"git_access must be one of: {', '.join(GIT_ACCESS_POLICIES)}"
            )
        if not isinstance(self.git_host, str) or not self.git_host or any(
            character.isspace() or ord(character) < 32 for character in self.git_host
        ):
            raise ValueError("git_host must be a non-empty hostname")

        selected = list(self.agent_tools or [])
        for tool in selected:
            if tool not in AGENT_TOOLS:
                raise ValueError(f"Unsupported agent tool: {tool}")
        selected = list(dict.fromkeys(selected))
        self.agent_tools = selected or None
        self.install_gh = "gh" in selected or self.install_gh
        self.install_codex = "codex" in selected or self.install_codex
        self.install_claude = "claude" in selected or self.install_claude
        self.install_opencode = "opencode" in selected or self.install_opencode
        desktop_interfaces = list(dict.fromkeys(self.desktop_interfaces or []))
        web_interfaces = list(dict.fromkeys(self.web_interfaces or []))
        for interface in desktop_interfaces:
            if interface not in DESKTOP_INTERFACES:
                raise ValueError(f"Unsupported desktop interface: {interface}")
        for interface in web_interfaces:
            if interface not in WEB_INTERFACES:
                raise ValueError(f"Unsupported web interface: {interface}")
        self.desktop_interfaces = desktop_interfaces or None
        self.web_interfaces = web_interfaces or None
        pairing_providers = list(dict.fromkeys(self.device_pairing_providers or []))
        if self.disable_device_pairing:
            pairing_providers = []
            self.device_pairing_port = 3774
        for provider in pairing_providers:
            if provider not in DEVICE_PAIRING_PROVIDERS:
                raise ValueError(f"Unsupported device pairing provider: {provider}")
        self.device_pairing_providers = pairing_providers or None
        if (
            self.device_pairing_providers
            and self.device_pairing_auth_password is not None
            and not self.device_pairing_auth_file
            and not self.device_pairing_auth_username
        ):
            self.device_pairing_auth_username = self.username
        if self.desktop_interfaces or self.web_interfaces:
            if not self.install_codex and not self.install_claude and not self.install_opencode:
                raise ValueError(
                    "T3 Code requires at least one provider CLI: "
                    "--agent-tool codex, claude, or opencode"
                )
        if self.desktop_interfaces and not self.include_desktop:
            raise ValueError(
                "--desktop-interface requires a desktop-capable setup or --rdp"
            )
        if self.web_interfaces:
            if self.web_interface_host is None:
                self.web_interface_host = (
                    "0.0.0.0" if self.web_interface_sources else "127.0.0.1"
                )
            if not 1 <= self.web_interface_port <= 65535:
                raise ValueError("web_interface_port must be between 1 and 65535")
            # T3 Code's headless server requires the Node runtime even when
            # the operator did not select --node separately.
            self.install_node = True
        if self.device_pairing_providers:
            if not 1 <= self.device_pairing_port <= 65535:
                raise ValueError("device_pairing_port must be between 1 and 65535")
            if self.device_pairing_port == self.web_interface_port:
                raise ValueError(
                    "device_pairing_port must differ from web_interface_port"
                )

    def selected_agent_tools(self) -> StrList:
        """Return selected coding agents in stable display/install order."""
        tools: StrList = []
        for name, enabled in (
            ("gh", self.install_gh),
            ("codex", self.install_codex),
            ("claude", self.install_claude),
            ("opencode", self.install_opencode),
        ):
            if enabled:
                tools.append(name)
        return tools

    def to_remote_args(self) -> StrList:
        """Generate command line arguments for remote execution."""
        args: StrList = []
        
        args.append(f"--system-type {shlex.quote(self.system_type)}")
        args.append(f"--username {shlex.quote(self.username)}")
        args.append(f"--machine {shlex.quote(self.machine_type)}")
        for storage_spec in _normalize_nested_specs(self.container_storage) or []:
            if not storage_spec or storage_spec[0] in {"root", "template"}:
                continue
            escaped_spec = " ".join(shlex.quote(str(part)) for part in storage_spec)
            args.append(f"--storage {escaped_spec}")
        for mount_spec in _normalize_nested_specs(self.storage_mounts) or []:
            escaped_spec = " ".join(shlex.quote(str(part)) for part in mount_spec)
            args.append(f"--storage-mount {escaped_spec}")
        if self.include_control_plane_tools:
            args.append("--control-plane")
        
        if self.password:
            args.append(f"--password {shlex.quote(self.password)}")
        
        if self.timezone:
            args.append(f"--timezone {shlex.quote(self.timezone)}")

        if self.system_hostname:
            args.append(f"--hostname {shlex.quote(self.system_hostname)}")

        if self.static_ipv4:
            args.append(f"--ip {shlex.quote(self.static_ipv4)}")

        if self.static_ipv6:
            args.append(f"--ipv6 {shlex.quote(self.static_ipv6)}")

        if self.network_gateway4:
            args.append(f"--gateway {shlex.quote(self.network_gateway4)}")

        if self.network_gateway6:
            args.append(f"--gateway6 {shlex.quote(self.network_gateway6)}")

        for dns_server in self.network_dns or []:
            args.append(f"--dns {shlex.quote(dns_server)}")

        if self.network_interface:
            args.append(f"--network-interface {shlex.quote(self.network_interface)}")

        if self.activate_network:
            args.append("--activate-network")
        
        if self.friendly_name:
            args.append(f"--name {shlex.quote(self.friendly_name)}")
        
        if self.enable_rdp:
            args.append("--rdp")
            if self.rdp_existing_password:
                args.append("--rdp-existing-password")
            args.append(f"--rdp-bind-address {shlex.quote(self.rdp_bind_address)}")
            for source in self.rdp_allowed_sources or []:
                args.append(f"--rdp-source {shlex.quote(source)}")
            if not self.rdp_clipboard:
                args.append("--no-rdp-clipboard")
            if self.rdp_drive_redirection:
                args.append("--rdp-drive-redirection")
            if self.rdp_audio:
                args.append("--rdp-audio")
            args.append(f"--rdp-max-sessions {self.rdp_max_sessions}")
            if self.rdp_kill_disconnected:
                args.append("--rdp-kill-disconnected")
            args.append(
                f"--rdp-disconnected-timeout {self.rdp_disconnected_timeout}"
            )
            args.append(f"--rdp-idle-timeout {self.rdp_idle_timeout}")
        
        if self.desktop:
            args.append(f"--desktop {shlex.quote(self.desktop)}")
        
        # Send browsers - only use browsers list if available, otherwise use browser
        if self.browsers:
            for browser in self.browsers:
                args.append(f"--browser {shlex.quote(browser)}")
        elif self.browser:
            args.append(f"--browser {shlex.quote(self.browser)}")
        
        if self.use_flatpak:
            args.append("--flatpak")
        
        if self.install_office:
            args.append("--office")
        
        if self.apt_packages:
            for package in self.apt_packages:
                args.append(f"--apt-install {shlex.quote(package)}")
        
        if self.flatpak_packages:
            for package in self.flatpak_packages:
                args.append(f"--flatpak-install {shlex.quote(package)}")
        
        if self.dark_theme:
            args.append("--dark")

        if self.refresh_packages:
            args.append("--refresh-packages")
        
        if self.dry_run:
            args.append("--dry-run")
        
        if self.install_ruby:
            args.append("--ruby")
        
        if self.install_go:
            args.append("--go")
        
        if self.install_node:
            args.append("--node")
        
        if self.install_python:
            args.append("--python")

        for tool in self.selected_agent_tools():
            args.append(f"--agent-tool {shlex.quote(tool)}")

        for interface in self.desktop_interfaces or []:
            args.append(f"--desktop-interface {shlex.quote(interface)}")
        for interface in self.web_interfaces or []:
            args.append(f"--web-interface {shlex.quote(interface)}")
        if self.web_interfaces:
            args.append(
                f"--web-interface-host {shlex.quote(self.web_interface_host or '127.0.0.1')}"
            )
            args.append(f"--web-interface-port {self.web_interface_port}")
            for source in self.web_interface_sources or []:
                args.append(f"--web-interface-source {shlex.quote(source)}")
        for provider in self.device_pairing_providers or []:
            args.append(f"--device-pairing {shlex.quote(provider)}")
        if self.device_pairing_providers:
            args.append(f"--device-pairing-port {self.device_pairing_port}")
        if self.device_pairing_payload:
            args.append("--device-pairing-payload")

        if self.browser_automation:
            args.append(
                f"--browser-automation {shlex.quote(self.browser_automation)}"
            )

        if self.git_access != "none":
            args.append(f"--git-access {shlex.quote(self.git_access)}")
        if self.git_host != "github.com":
            args.append(f"--git-host {shlex.quote(self.git_host)}")
        if self.copy_agent_config or self.copy_agent_keys or self.agent_payload:
            args.append("--agent-payload")

        if self.agent_repos:
            for git_url in self.agent_repos:
                args.append(f"--repo {shlex.quote(git_url)}")
        if self.agent_workspace:
            args.append(f"--agent-workspace {shlex.quote(self.agent_workspace)}")
        if self.install_git_lfs:
            args.append("--git-lfs")
        
        if self.custom_steps:
            args.append(f"--steps {shlex.quote(self.custom_steps)}")
        
        if self.deploy_specs:
            if self.deployment_mode == "lite":
                args.append("--deployment-lite")
            elif self.deployment_mode == "full":
                # --deployment-full already implies a full rebuild on the remote
                args.append("--deployment-full")
            elif self.full_deploy:
                args.append("--full-deploy")
            # Use --deploy-latest for each spec if deploy_latest is set, otherwise --deploy
            flag = "--deploy-latest" if self.deploy_latest else "--deploy"
            for deploy_spec, git_url in self.deploy_specs:
                args.append(f"{flag} {shlex.quote(deploy_spec)} {shlex.quote(git_url)}")
        elif self.deploy_latest:
            # deploy_latest without specs doesn't make sense, but keep for backward compat
            args.append("--deploy-latest")
        
        if self.reset_migrations:
            args.append("--reset-migrations")
        
        if self.enable_ssl:
            args.append("--ssl")
            if self.ssl_email:
                args.append(f"--ssl-email {shlex.quote(self.ssl_email)}")
        
        if self.enable_cloudflare:
            args.append("--cloudflare")
        
        if self.enable_cicd:
            args.append("--cicd")
        
        if self.is_build_server:
            args.append("--build-server")
        
        if self.is_app_server:
            args.append("--app-server")
        
        if self.deploy_targets:
            for target in self.deploy_targets:
                args.append(f"--deploy-target {shlex.quote(target)}")
        
        if self.api_subdomain:
            args.append("--api-subdomain")
        
        if self.enable_samba:
            args.append("--samba")
        
        if self.samba_shares:
            for share_spec in self.samba_shares:
                escaped_spec = ' '.join(shlex.quote(str(s)) for s in share_spec)
                args.append(f"--share {escaped_spec}")

        if self.share_credentials:
            for credential_spec in self.share_credentials:
                escaped_spec = ' '.join(shlex.quote(str(s)) for s in credential_spec)
                args.append(f"--credential {escaped_spec}")
        
        if self.enable_smbclient:
            args.append("--smbclient")
        
        if self.smb_mounts:
            for mount_spec in self.smb_mounts:
                escaped_spec = ' '.join(shlex.quote(str(s)) for s in mount_spec)
                args.append(f"--mount-smb {escaped_spec}")
        
        if self.sync_specs:
            for sync_spec in self.sync_specs:
                escaped_spec = ' '.join(shlex.quote(str(s)) for s in sync_spec)
                args.append(f"--sync {escaped_spec}")

        if self.backup_specs:
            for backup_spec in self.backup_specs:
                escaped_spec = ' '.join(shlex.quote(str(s)) for s in backup_spec)
                args.append(f"--backup {escaped_spec}")
        
        if self.scrub_specs:
            for scrub_spec in self.scrub_specs:
                escaped_spec = ' '.join(shlex.quote(str(s)) for s in scrub_spec)
                args.append(f"--scrub {escaped_spec}")
        
        if self.notify_specs:
            for notify_spec in self.notify_specs:
                escaped_spec = ' '.join(shlex.quote(str(s)) for s in notify_spec)
                args.append(f"--notify {escaped_spec}")
        
        if self.antistatic_server:
            args.append(f"--antistatic-server {shlex.quote(self.antistatic_server)}")

        if self.antistatic_admin:
            args.append(f"--antistatic-admin {shlex.quote(self.antistatic_admin)}")

        if self.antistatic_db:
            args.append(f"--antistatic-db {shlex.quote(self.antistatic_db)}")

        if self.gogs:
            escaped_gogs = " ".join(shlex.quote(str(part)) for part in self.gogs)
            args.append(f"--gogs {escaped_gogs}")
        for source in self.gogs_sources or []:
            args.append(f"--gogs-source {shlex.quote(source)}")
        
        if self.auto_restart:
            args.append("--auto-restart")
        else:
            args.append("--no-auto-restart")
        args.append(f"--auto-restart-force-days {self.auto_restart_force_days}")
        args.append(f"--auto-restart-grace {self.auto_restart_grace}")
                
        return args
    
    def to_setup_command(self, include_username: bool = True) -> StrList:
        """Generate command line for the unified setup entry point.
        
        Returns a list of command parts that can be joined with spaces or newlines.
        """
        setup_host = self.host
        provisioned_ipv4 = False
        if self.hosted_node and self.static_ipv4:
            try:
                guest_interface = ipaddress.ip_interface(self.static_ipv4)
            except ValueError:
                guest_interface = None
            if isinstance(guest_interface, ipaddress.IPv4Interface):
                provisioned_ipv4 = True
                setup_host = str(guest_interface.ip)
                if guest_interface.network.prefixlen != 24:
                    setup_host = str(guest_interface)

        cmd_parts: StrList = [
            f"infra-tools setup {shlex.quote(self.system_type)}",
            shlex.quote(setup_host),
        ]
        
        # Add username if different from current user or if requested
        if include_username:
            cmd_parts.append(self.username)
        
        # SSH key
        if self.ssh_key:
            cmd_parts.append(f"-k {shlex.quote(self.ssh_key)}")

        if self.hosted_node:
            cmd_parts.append(f"--provision-on {shlex.quote(self.hosted_node)}")
            if self.hosted_user != "root":
                cmd_parts.append(f"--provision-user {shlex.quote(self.hosted_user)}")
            if self.hosted_key and self.hosted_key != self.ssh_key:
                cmd_parts.append(f"--provision-key {shlex.quote(self.hosted_key)}")
            if self.hosted_bridge:
                cmd_parts.append(f"--bridge {shlex.quote(self.hosted_bridge)}")
            if self.container_memory:
                cmd_parts.append(f"--memory {shlex.quote(self.container_memory)}")
            if self.vm_balloon_min:
                cmd_parts.append(f"--balloon-min {shlex.quote(self.vm_balloon_min)}")
            for storage_spec in _normalize_nested_specs(self.container_storage) or []:
                escaped_spec = " ".join(shlex.quote(str(part)) for part in storage_spec)
                cmd_parts.append(f"--storage {escaped_spec}")
            for mount_spec in _normalize_nested_specs(self.storage_mounts) or []:
                escaped_spec = " ".join(shlex.quote(str(part)) for part in mount_spec)
                cmd_parts.append(f"--storage-mount {escaped_spec}")
            if self.container_cores != 1:
                cmd_parts.append(f"--cores {self.container_cores}")
            if self.container_base != "debian":
                cmd_parts.append(f"--base {shlex.quote(self.container_base)}")
            if self.vm_image:
                cmd_parts.append(f"--image {shlex.quote(self.vm_image)}")
            if self.vm_image_sha512:
                cmd_parts.append(
                    f"--image-sha512 {shlex.quote(self.vm_image_sha512)}"
                )
            if self.vm_image_storage:
                cmd_parts.append(
                    f"--image-storage {shlex.quote(self.vm_image_storage)}"
                )
        
        # Password is intentionally not included in the command line for security reasons.
        # If a password is required, it should be provided interactively or via a secure
        # mechanism instead of as a command-line argument.
        
        # Timezone
        if self.timezone and self.timezone != "UTC":
            cmd_parts.append(f"-t {shlex.quote(self.timezone)}")

        if self.system_hostname:
            cmd_parts.append(f"--hostname {shlex.quote(self.system_hostname)}")

        if self.static_ipv4 and not provisioned_ipv4:
            cmd_parts.append(f"--ip {shlex.quote(self.static_ipv4)}")

        if self.static_ipv6:
            cmd_parts.append(f"--ipv6 {shlex.quote(self.static_ipv6)}")

        if self.network_gateway4:
            cmd_parts.append(f"--gateway {shlex.quote(self.network_gateway4)}")

        if self.network_gateway6:
            cmd_parts.append(f"--gateway6 {shlex.quote(self.network_gateway6)}")

        for dns_server in self.network_dns or []:
            cmd_parts.append(f"--dns {shlex.quote(dns_server)}")

        if self.network_interface:
            cmd_parts.append(f"--network-interface {shlex.quote(self.network_interface)}")

        if self.activate_network:
            cmd_parts.append("--activate-network")
        
        # Machine type (if not the current setup default for this flow)
        default_machine_type = (
            "vm"
            if self.hosted_node
            else _default_machine_type_for_setup(
                self.system_type,
                is_build_server=self.is_build_server,
            )
        )
        if self.machine_type != default_machine_type:
            cmd_parts.append(f"--machine {shlex.quote(self.machine_type)}")

        system_type_defaults = get_system_type_definition(self.system_type)
        if (
            self.include_control_plane_tools
            and not system_type_defaults.include_control_plane_tools
        ):
            cmd_parts.append("--control-plane")
        
        # Name and tags
        if self.friendly_name:
            cmd_parts.append(f"--name {shlex.quote(self.friendly_name)}")
        
        if self.tags and len(self.tags) > 0:
            cmd_parts.append(f"--tags {shlex.quote(','.join(self.tags))}")
        
        # Desktop/workstation flags
        if self.enable_rdp:
            cmd_parts.append("--rdp")
            if self.rdp_existing_password:
                cmd_parts.append("--rdp-existing-password")
            if self.rdp_bind_address != "0.0.0.0":
                cmd_parts.append(
                    f"--rdp-bind-address {shlex.quote(self.rdp_bind_address)}"
                )
            for source in self.rdp_allowed_sources or []:
                cmd_parts.append(f"--rdp-source {shlex.quote(source)}")
            if not self.rdp_clipboard:
                cmd_parts.append("--no-rdp-clipboard")
            if self.rdp_drive_redirection:
                cmd_parts.append("--rdp-drive-redirection")
            if self.rdp_audio:
                cmd_parts.append("--rdp-audio")
            if self.rdp_max_sessions != 10:
                cmd_parts.append(f"--rdp-max-sessions {self.rdp_max_sessions}")
            if self.rdp_kill_disconnected:
                cmd_parts.append("--rdp-kill-disconnected")
            if self.rdp_disconnected_timeout != 0:
                cmd_parts.append(
                    f"--rdp-disconnected-timeout {self.rdp_disconnected_timeout}"
                )
            if self.rdp_idle_timeout != 0:
                cmd_parts.append(f"--rdp-idle-timeout {self.rdp_idle_timeout}")
        
        if self.desktop and self.desktop != "xfce":
            cmd_parts.append(f"--desktop {shlex.quote(self.desktop)}")
        
        # Only include browser args if not default or if using multiple browsers
        if self.browsers:
            for browser in self.browsers:
                cmd_parts.append(f"--browser {shlex.quote(browser)}")
        elif self.browser and self.browser != "librewolf":
            cmd_parts.append(f"--browser {shlex.quote(self.browser)}")
        
        if self.use_flatpak:
            cmd_parts.append("--flatpak")
        
        if self.install_office:
            cmd_parts.append("--office")
        
        if self.apt_packages:
            for package in self.apt_packages:
                cmd_parts.append(f"--apt-install {shlex.quote(package)}")
        
        if self.flatpak_packages:
            for package in self.flatpak_packages:
                cmd_parts.append(f"--flatpak-install {shlex.quote(package)}")
        
        if self.dark_theme:
            cmd_parts.append("--dark")

        # Development tools
        if self.install_ruby:
            cmd_parts.append("--ruby")
        
        if self.install_go:
            cmd_parts.append("--go")
        
        if self.install_node:
            cmd_parts.append("--node")
        
        if self.install_python:
            cmd_parts.append("--python")

        for tool in self.selected_agent_tools():
            cmd_parts.append(f"--agent-tool {shlex.quote(tool)}")

        for interface in self.desktop_interfaces or []:
            cmd_parts.append(f"--desktop-interface {shlex.quote(interface)}")
        for interface in self.web_interfaces or []:
            cmd_parts.append(f"--web-interface {shlex.quote(interface)}")
        if self.web_interfaces:
            cmd_parts.append(
                f"--web-interface-host {shlex.quote(self.web_interface_host or '127.0.0.1')}"
            )
            cmd_parts.append(f"--web-interface-port {self.web_interface_port}")
            for source in self.web_interface_sources or []:
                cmd_parts.append(f"--web-interface-source {shlex.quote(source)}")
        for provider in self.device_pairing_providers or []:
            cmd_parts.append(f"--device-pairing {shlex.quote(provider)}")
        if self.device_pairing_providers and self.device_pairing_port != 3774:
            cmd_parts.append(f"--device-pairing-port {self.device_pairing_port}")

        if self.browser_automation:
            cmd_parts.append(
                f"--browser-automation {shlex.quote(self.browser_automation)}"
            )

        if self.git_access != "none":
            cmd_parts.append(f"--git-access {shlex.quote(self.git_access)}")
        if self.git_host != "github.com":
            cmd_parts.append(f"--git-host {shlex.quote(self.git_host)}")

        if self.agent_repos:
            for git_url in self.agent_repos:
                cmd_parts.append(f"--repo {shlex.quote(git_url)}")
        if self.agent_workspace:
            cmd_parts.append(f"--agent-workspace {shlex.quote(self.agent_workspace)}")
        if self.install_git_lfs:
            cmd_parts.append("--git-lfs")
        
        # Custom steps
        if self.custom_steps:
            cmd_parts.append(f"--steps {shlex.quote(self.custom_steps)}")
        
        # Deployments
        if self.deploy_specs:
            if self.deployment_mode == "lite":
                cmd_parts.append("--deployment-lite")
            elif self.deployment_mode == "full":
                # --deployment-full already implies a full rebuild on the remote
                cmd_parts.append("--deployment-full")
            elif self.full_deploy:
                cmd_parts.append("--full-deploy")
            # Use --deploy-latest for each spec if deploy_latest is set, otherwise --deploy
            flag = "--deploy-latest" if self.deploy_latest else "--deploy"
            for deploy_spec, git_url in self.deploy_specs:
                cmd_parts.append(f"{flag} {shlex.quote(deploy_spec)} {shlex.quote(git_url)}")
        elif self.deploy_latest:
            # deploy_latest without specs doesn't make sense, but keep for backward compat
            cmd_parts.append("--deploy-latest")
        
        if self.reset_migrations:
            cmd_parts.append("--reset-migrations")
        
        # SSL
        if self.enable_ssl:
            cmd_parts.append("--ssl")
            if self.ssl_email:
                cmd_parts.append(f"--ssl-email {shlex.quote(self.ssl_email)}")
        
        # Cloudflare
        if self.enable_cloudflare:
            cmd_parts.append("--cloudflare")
        
        # CI/CD
        if self.enable_cicd:
            cmd_parts.append("--cicd")
        
        # Build/App Server
        if self.is_build_server:
            cmd_parts.append("--build-server")
        
        if self.is_app_server:
            cmd_parts.append("--app-server")
        
        if self.deploy_targets:
            for target in self.deploy_targets:
                cmd_parts.append(f"--deploy-target {shlex.quote(target)}")
        
        if self.api_subdomain:
            cmd_parts.append("--api-subdomain")
        
        # Samba
        if self.enable_samba:
            cmd_parts.append("--samba")

        SHARE_USERS_INDEX = 3
        MIN_SHARE_FIELDS = SHARE_USERS_INDEX + 1
        required_share_credentials: StrList = []
        seen_share_credentials: set[str] = set()
        if self.antistatic_admin:
            required_share_credentials.append(self.antistatic_admin)
            seen_share_credentials.add(self.antistatic_admin)
        redacted_share_specs: list[list[str]] = []
        if self.samba_shares:
            for share_spec in self.samba_shares:
                redacted_share_spec = list(share_spec)
                if len(redacted_share_spec) >= MIN_SHARE_FIELDS:
                    users_field = redacted_share_spec[SHARE_USERS_INDEX]
                    redacted_users: StrList = []
                    for user_spec in users_field.split(','):
                        user_spec = user_spec.strip()
                        if not user_spec:
                            continue
                        if ':' in user_spec:
                            username, _ = user_spec.split(':', 1)
                            redacted_users.append(f"{username.strip()}:[REDACTED]")
                        else:
                            redacted_users.append(user_spec)
                            if user_spec not in seen_share_credentials:
                                seen_share_credentials.add(user_spec)
                                required_share_credentials.append(user_spec)
                    redacted_share_spec[SHARE_USERS_INDEX] = ','.join(redacted_users)
                redacted_share_specs.append(redacted_share_spec)

        for username in required_share_credentials:
            cmd_parts.append(f"--credential {shlex.quote(username)} [REDACTED]")

        for redacted_share_spec in redacted_share_specs:
            escaped_spec = ' '.join(shlex.quote(str(s)) for s in redacted_share_spec)
            cmd_parts.append(f"--share {escaped_spec}")
        
        # SMB client
        if self.enable_smbclient:
            cmd_parts.append("--smbclient")
        
        # SMB mounts
        if self.smb_mounts:
            for mount_spec in self.smb_mounts:
                redacted_mount_spec = list(mount_spec)
                if len(redacted_mount_spec) >= 3 and ':' in redacted_mount_spec[2]:
                    redacted_mount_spec[2] = redact_mount_credentials(redacted_mount_spec[2])
                escaped_spec = ' '.join(shlex.quote(str(s)) for s in redacted_mount_spec)
                cmd_parts.append(f"--mount-smb {escaped_spec}")
        
        # Sync
        if self.sync_specs:
            for sync_spec in self.sync_specs:
                escaped_spec = ' '.join(shlex.quote(str(s)) for s in sync_spec)
                cmd_parts.append(f"--sync {escaped_spec}")

        if self.backup_specs:
            for backup_spec in self.backup_specs:
                escaped_spec = ' '.join(shlex.quote(str(s)) for s in backup_spec)
                cmd_parts.append(f"--backup {escaped_spec}")
        
        # Scrub
        if self.scrub_specs:
            for scrub_spec in self.scrub_specs:
                escaped_spec = ' '.join(shlex.quote(str(s)) for s in scrub_spec)
                cmd_parts.append(f"--scrub {escaped_spec}")
        
        # Notifications
        if self.notify_specs:
            for notify_spec in self.notify_specs:
                escaped_spec = ' '.join(shlex.quote(str(s)) for s in notify_spec)
                cmd_parts.append(f"--notify {escaped_spec}")
        
        # Antistatic lobby server
        if self.antistatic_server:
            cmd_parts.append(f"--antistatic-server {shlex.quote(self.antistatic_server)}")

        if self.antistatic_admin:
            cmd_parts.append(f"--antistatic-admin {shlex.quote(self.antistatic_admin)}")

        # Antistatic DB service
        if self.antistatic_db:
            cmd_parts.append(f"--antistatic-db {shlex.quote(self.antistatic_db)}")

        if self.gogs:
            escaped_gogs = " ".join(shlex.quote(str(part)) for part in self.gogs)
            cmd_parts.append(f"--gogs {escaped_gogs}")
        for source in self.gogs_sources or []:
            cmd_parts.append(f"--gogs-source {shlex.quote(source)}")
        
        # Restart control
        system_defaults = get_system_type_definition(self.system_type)
        if self.auto_restart != system_defaults.default_auto_restart:
            cmd_parts.append("--auto-restart" if self.auto_restart else "--no-auto-restart")
        if self.auto_restart_force_days != system_defaults.default_auto_restart_force_days:
            cmd_parts.append(f"--auto-restart-force-days {self.auto_restart_force_days}")
        if self.auto_restart_grace != 5:
            cmd_parts.append(f"--auto-restart-grace {self.auto_restart_grace}")
        
        return cmd_parts

    def to_dict(self) -> JSONDict:
        data = asdict(self)
        data.pop('host', None)
        data.pop('system_type', None)
        data.pop('password', None)
        data.pop('share_credentials', None)
        data.pop('deploy_latest', None)
        for transient_field in (
            'refresh_packages',
            'copy_agent_keys',
            'copy_agent_config',
            'git_auth_source',
            'git_auth_file',
            'git_auth_token',
            'agent_auth_source',
            'agent_auth_files',
            'agent_config_source',
            'agent_payload',
            'device_pairing_auth_file',
            'device_pairing_auth_username',
            'device_pairing_auth_password',
            'device_pairing_payload',
            'disable_device_pairing',
        ):
            data.pop(transient_field, None)
        for legacy_field in (
            'install_gh',
            'install_codex',
            'install_claude',
            'install_opencode',
        ):
            data.pop(legacy_field, None)
        data['agent_tools'] = self.selected_agent_tools() or None
        # Live activation is a one-shot controller operation. Persisting it
        # would make a later deploy retry a sensitive address change without
        # the operator explicitly requesting another handoff.
        data.pop('activate_network', None)
        data['samba_shares'] = _strip_passwords_from_samba_shares(self.samba_shares)
        data['smb_mounts'] = _strip_passwords_from_smb_mounts(self.smb_mounts)
        if self.tags:
            data['tags'] = ','.join(self.tags)
        return data
    
    @classmethod
    def from_dict(cls, host: str, system_type: str, data: JSONDict) -> 'SetupConfig':
        # Older cache entries may contain this one-shot flag. Never replay a
        # sensitive live handoff merely because a saved configuration is
        # loaded for deploy, patch, or reconstruction.
        data.pop('activate_network', None)
        tags_str = data.get('tags')
        if tags_str and isinstance(tags_str, str):
            data['tags'] = [tag.strip() for tag in tags_str.split(',') if tag.strip()]
        elif not tags_str:
            data['tags'] = None

        data['container_storage'] = _normalize_nested_specs(data.get('container_storage'))
        data['storage_mounts'] = _normalize_nested_specs(data.get('storage_mounts'))
        system_defaults = get_system_type_definition(system_type)
        if 'auto_restart' not in data or data.get('auto_restart') is None:
            if 'no_restart' in data and data.get('no_restart') is not None:
                data['auto_restart'] = not bool(data.pop('no_restart'))
            else:
                data['auto_restart'] = system_defaults.default_auto_restart
        else:
            data.pop('no_restart', None)
        if 'auto_restart_force_days' not in data or data.get('auto_restart_force_days') is None:
            data['auto_restart_force_days'] = system_defaults.default_auto_restart_force_days
        data['auto_restart_force_days'] = _validate_non_negative_int(
            'auto_restart_force_days', int(data['auto_restart_force_days'])
        )
        if 'auto_restart_grace' not in data or data.get('auto_restart_grace') is None:
            data['auto_restart_grace'] = 5
        data['auto_restart_grace'] = _validate_non_negative_int(
            'auto_restart_grace', int(data['auto_restart_grace'])
        )
            
        if 'friendly_name' not in data:
            data['friendly_name'] = None
            
        return cls(host=host, system_type=system_type, **data)
    
    @classmethod
    def from_args(cls, args: argparse.Namespace, system_type: str) -> 'SetupConfig':
        from lib.system_utils import get_current_username, get_local_timezone

        system_type_definition = get_system_type_definition(system_type)
        tags = None
        if hasattr(args, 'tags') and args.tags:
            tags = [tag.strip() for tag in args.tags.split(',') if tag.strip()]
        
        username = args.username if args.username else get_current_username()
        timezone = args.timezone if args.timezone else get_local_timezone()
        desktop = args.desktop or "xfce"
        
        # Handle browser - support both single value and list
        browser = None
        browsers = getattr(args, 'browsers', None)
        
        # If browsers list is provided, use it
        if browsers and len(browsers) > 0:
            # First browser becomes the default
            browser = browsers[0]
        elif hasattr(args, 'browser') and args.browser:
            # Single browser provided
            browser = args.browser
        elif system_type_definition.default_browser:
            browser = system_type_definition.default_browser
        
        install_office = args.install_office
        if install_office is None and system_type_definition.default_install_office:
            install_office = True
        elif install_office is None:
            install_office = False
        
        enable_rdp = args.enable_rdp
        if enable_rdp is None and system_type_definition.default_enable_rdp:
            enable_rdp = True
        elif enable_rdp is None:
            enable_rdp = False
        
        smb_mounts = getattr(args, 'smb_mounts', None)
        enable_smbclient = getattr(args, 'enable_smbclient', None)
        if enable_smbclient is None and (system_type_definition.default_enable_smbclient or smb_mounts):
            enable_smbclient = True
        elif enable_smbclient is None:
            enable_smbclient = False

        is_build_server = bool(getattr(args, 'is_build_server', False))
        is_app_server = bool(getattr(args, 'is_app_server', False))
        machine_type = _resolve_machine_type(
            args,
            is_hosted=bool(getattr(args, 'hosted_node', None)),
        )
        
        include_desktop = (
            system_type_definition.include_desktop
            or enable_rdp
        )
        include_cli_tools = system_type_definition.include_cli_tools
        include_control_plane_tools = (
            system_type_definition.include_control_plane_tools
            or bool(getattr(args, 'control_plane', False))
        )
        include_desktop_apps = system_type_definition.include_desktop_apps
        include_workstation_dev_apps = system_type_definition.include_workstation_dev_apps
        include_pc_dev_apps = system_type_definition.include_pc_dev_apps
        include_web_server = system_type_definition.include_web_server
        include_web_firewall = system_type_definition.include_web_firewall
        
        auto_restart = _optional_bool_arg(args, 'auto_restart')
        if auto_restart is None:
            auto_restart = system_type_definition.default_auto_restart

        auto_restart_force_days = _optional_int_arg(args, 'auto_restart_force_days')
        if auto_restart_force_days is None:
            auto_restart_force_days = system_type_definition.default_auto_restart_force_days
        auto_restart_force_days = _validate_non_negative_int(
            'auto_restart_force_days', auto_restart_force_days
        )

        auto_restart_grace = _optional_int_arg(args, 'auto_restart_grace')
        if auto_restart_grace is None:
            auto_restart_grace = 5
        auto_restart_grace = _validate_non_negative_int('auto_restart_grace', auto_restart_grace)

        raw_agent_tools = getattr(args, 'agent_tools', None)
        agent_tools = raw_agent_tools if isinstance(raw_agent_tools, list) else None
        browser_automation = _optional_str_arg(args, 'browser_automation')
        raw_agent_repos = getattr(args, 'agent_repos', None)
        agent_repos = raw_agent_repos if isinstance(raw_agent_repos, list) else None
        raw_git_access = getattr(args, 'git_access', 'none')
        git_access = raw_git_access if raw_git_access in GIT_ACCESS_POLICIES else 'none'
        raw_git_host = getattr(args, 'git_host', 'github.com')
        git_host = raw_git_host if isinstance(raw_git_host, str) else 'github.com'
        raw_agent_auth_files = getattr(args, 'agent_auth_files', None)
        agent_auth_files = (
            raw_agent_auth_files if isinstance(raw_agent_auth_files, list) else None
        )
        git_auth_source = _optional_str_arg(args, 'git_auth_source')
        git_auth_file = _optional_str_arg(args, 'git_auth_file')
        git_auth_token = _optional_str_arg(args, 'git_auth_token')
        agent_auth_source = _optional_str_arg(args, 'agent_auth_source')
        agent_config_source = _optional_str_arg(args, 'agent_config_source')
        device_pairing_port = _optional_int_arg(args, 'device_pairing_port')
        if device_pairing_port is None:
            device_pairing_port = 3774
        
        return cls(
            host=args.host,
            username=username,
            system_type=system_type,
            machine_type=machine_type,
            password=getattr(args, 'password', None),
            ssh_key=getattr(args, 'ssh_key', None),
            timezone=timezone,
            system_hostname=getattr(args, 'system_hostname', None),
            static_ipv4=getattr(args, 'static_ipv4', None),
            static_ipv6=getattr(args, 'static_ipv6', None),
            network_gateway4=getattr(args, 'network_gateway4', None),
            network_gateway6=getattr(args, 'network_gateway6', None),
            network_dns=getattr(args, 'network_dns', None),
            network_interface=getattr(args, 'network_interface', None),
            activate_network=getattr(args, 'activate_network', False),
            friendly_name=getattr(args, 'friendly_name', None),
            tags=tags,
            enable_rdp=enable_rdp,
            rdp_existing_password=getattr(args, 'rdp_existing_password', False),
            rdp_bind_address=getattr(args, 'rdp_bind_address', '0.0.0.0'),
            rdp_allowed_sources=getattr(args, 'rdp_allowed_sources', None),
            rdp_clipboard=getattr(args, 'rdp_clipboard', True),
            rdp_drive_redirection=getattr(args, 'rdp_drive_redirection', False),
            rdp_audio=getattr(args, 'rdp_audio', False),
            rdp_max_sessions=getattr(args, 'rdp_max_sessions', 10),
            rdp_kill_disconnected=getattr(args, 'rdp_kill_disconnected', False),
            rdp_disconnected_timeout=getattr(args, 'rdp_disconnected_timeout', 0),
            rdp_idle_timeout=getattr(args, 'rdp_idle_timeout', 0),
            desktop=desktop,
            browser=browser,
            browsers=browsers,
            use_flatpak=getattr(args, 'use_flatpak', False),
            install_office=install_office,
            apt_packages=getattr(args, 'apt_packages', None),
            flatpak_packages=getattr(args, 'flatpak_packages', None),
            dark_theme=getattr(args, 'dark_theme', False),
            dry_run=getattr(args, 'dry_run', False),
            refresh_packages=getattr(args, 'refresh_packages', False),
            install_ruby=getattr(args, 'install_ruby', False),
            install_go=getattr(args, 'install_go', False),
            install_node=getattr(args, 'install_node', False),
            install_python=getattr(args, 'install_python', False),
            agent_tools=agent_tools,
            desktop_interfaces=getattr(args, 'desktop_interfaces', None),
            web_interfaces=getattr(args, 'web_interfaces', None),
            web_interface_host=getattr(args, 'web_interface_host', None),
            web_interface_port=getattr(args, 'web_interface_port', 3773),
            web_interface_sources=getattr(args, 'web_interface_sources', None),
            device_pairing_providers=getattr(args, 'device_pairing_providers', None),
            device_pairing_port=device_pairing_port,
            device_pairing_auth_file=_optional_str_arg(
                args, 'device_pairing_auth_file'
            ),
            device_pairing_auth_username=_optional_str_arg(
                args, 'device_pairing_auth_username'
            ),
            device_pairing_auth_password=_optional_str_arg(
                args, 'device_pairing_auth_password'
            ),
            device_pairing_payload=(
                _optional_bool_arg(args, 'device_pairing_payload') is True
            ),
            disable_device_pairing=bool(
                getattr(args, 'disable_device_pairing', False)
            ),
            browser_automation=browser_automation,
            copy_agent_keys=bool(
                git_auth_source
                or git_auth_file
                or git_auth_token
                or agent_auth_source
                or agent_auth_files
            ),
            copy_agent_config=bool(agent_config_source),
            agent_repos=agent_repos,
            git_access=git_access,
            git_host=git_host,
            git_auth_source=git_auth_source,
            git_auth_file=git_auth_file,
            git_auth_token=git_auth_token,
            agent_auth_source=agent_auth_source,
            agent_auth_files=agent_auth_files,
            agent_config_source=agent_config_source,
            agent_payload=_optional_bool_arg(args, 'agent_payload') is True,
            agent_workspace=_optional_str_arg(args, 'agent_workspace'),
            install_git_lfs=getattr(args, 'install_git_lfs', False),
            custom_steps=getattr(args, 'custom_steps', None),
            deploy_specs=getattr(args, 'deploy_specs', None),
            deployment_mode=getattr(args, 'deployment_mode', 'default'),
            full_deploy=getattr(args, 'full_deploy', False),
            deploy_latest=getattr(args, 'deploy_latest', False),
            reset_migrations=getattr(args, 'reset_migrations', False),
            enable_ssl=getattr(args, 'enable_ssl', False),
            ssl_email=getattr(args, 'ssl_email', None),
            enable_cloudflare=getattr(args, 'enable_cloudflare', False),
            enable_cicd=getattr(args, 'enable_cicd', False),
            is_build_server=is_build_server,
            is_app_server=is_app_server,
            deploy_targets=getattr(args, 'deploy_targets', None),
            api_subdomain=getattr(args, 'api_subdomain', False),
            enable_samba=getattr(args, 'enable_samba', False),
            samba_shares=getattr(args, 'samba_shares', None),
            share_credentials=getattr(args, 'share_credentials', None),
            enable_smbclient=enable_smbclient,
            smb_mounts=smb_mounts,
            sync_specs=getattr(args, 'sync_specs', None),
            backup_specs=getattr(args, 'backup_specs', None),
            scrub_specs=getattr(args, 'scrub_specs', None),
            notify_specs=getattr(args, 'notify_specs', None),
            antistatic_server=getattr(args, 'antistatic_server', None),
            antistatic_admin=getattr(args, 'antistatic_admin', None),
            antistatic_db=getattr(args, 'antistatic_db', None),
            gogs=getattr(args, 'gogs', None),
            gogs_sources=getattr(args, 'gogs_sources', None),
            auto_restart=auto_restart,
            auto_restart_force_days=auto_restart_force_days,
            auto_restart_grace=auto_restart_grace,
            hosted_node=getattr(args, 'hosted_node', None),
            hosted_user=getattr(args, 'hosted_user', 'root'),
            hosted_key=getattr(args, 'hosted_key', None),
            hosted_bridge=getattr(args, 'hosted_bridge', None),
            container_memory=getattr(args, 'container_memory', None),
            vm_balloon_min=getattr(args, 'vm_balloon_min', None),
            container_storage=_normalize_nested_specs(getattr(args, 'container_storage', None)),
            storage_mounts=_normalize_nested_specs(getattr(args, 'storage_mounts', None)),
            container_cores=getattr(args, 'container_cores', 1),
            container_base=getattr(args, 'container_base', 'debian'),
            vm_image=getattr(args, 'vm_image', None),
            vm_image_sha512=getattr(args, 'vm_image_sha512', None),
            vm_image_storage=getattr(args, 'vm_image_storage', None),
            include_desktop=include_desktop,
            include_cli_tools=include_cli_tools,
            include_control_plane_tools=include_control_plane_tools,
            include_desktop_apps=include_desktop_apps,
            include_workstation_dev_apps=include_workstation_dev_apps,
            include_pc_dev_apps=include_pc_dev_apps,
            include_web_server=include_web_server,
            include_web_firewall=include_web_firewall
        )
