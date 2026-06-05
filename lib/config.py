#!/usr/bin/env python3

from __future__ import annotations

import argparse
import shlex
from dataclasses import dataclass, asdict
from typing import Optional, cast
from lib.plugin_registry import get_system_type_definition, get_system_type_names
from lib.types import StrList, NestedStrList, JSONDict, MaybeStr


SYSTEM_TYPES = get_system_type_names()

MACHINE_TYPES = ["unprivileged", "vm", "privileged", "hardware", "oci"]
DEFAULT_MACHINE_TYPE = "unprivileged"

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


def _resolve_machine_type(
    args: argparse.Namespace,
    *,
    system_default: Optional[str],
    is_build_server: bool,
) -> str:
    explicit_machine_type = getattr(args, "machine_type", None)
    if explicit_machine_type:
        return explicit_machine_type
    if is_build_server:
        return "vm"
    if system_default:
        return system_default
    return DEFAULT_MACHINE_TYPE


def _default_machine_type_for_setup(
    system_type: str,
    *,
    is_build_server: bool = False,
) -> str:
    if is_build_server:
        return "vm"
    system_default = get_system_type_definition(system_type).default_machine_type
    return system_default or DEFAULT_MACHINE_TYPE


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


def _normalize_container_storage(value: NestedStrList | list[str] | None) -> Optional[NestedStrList]:
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
    friendly_name: MaybeStr = None
    tags: Optional[StrList] = None
    enable_rdp: bool = False
    desktop: str = "xfce"
    browser: Optional[str] = "librewolf"  # Primary browser, or first from browsers list
    browsers: Optional[StrList] = None  # List of browsers to install
    use_flatpak: bool = False
    install_office: bool = False
    apt_packages: Optional[StrList] = None
    flatpak_packages: Optional[StrList] = None
    dark_theme: bool = False
    dry_run: bool = False
    install_ruby: bool = False
    install_go: bool = False
    install_node: bool = False
    install_python: bool = False
    custom_steps: Optional[str] = None
    deploy_specs: Optional[NestedStrList] = None
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
    scrub_specs: Optional[NestedStrList] = None
    notify_specs: Optional[NestedStrList] = None
    antistatic_server: MaybeStr = None  # "DOMAIN[:port]" spec
    antistatic_db: MaybeStr = None  # "DOMAIN[:port]" spec
    gogs: Optional[StrList] = None  # ["DOMAIN[:port]", "DATA_PATH"?]
    auto_restart: bool = True
    auto_restart_force_days: int = 7
    auto_restart_grace: int = 5
    # Hosted guest provisioning (Proxmox VM/LXC)
    hosted_node: MaybeStr = None
    hosted_user: str = "root"
    hosted_key: MaybeStr = None
    container_memory: MaybeStr = None
    container_storage: Optional[NestedStrList] = None  # [[type, pool, amount?], ...]
    container_cores: int = 1
    container_base: str = "debian"
    vm_image: MaybeStr = None  # http(s) URL or 'storage:iso/file.qcow2'
    include_desktop: bool = False
    include_cli_tools: bool = False
    include_desktop_apps: bool = False
    include_workstation_dev_apps: bool = False
    include_pc_dev_apps: bool = False
    include_web_server: bool = False
    include_web_firewall: bool = False
    
    def to_remote_args(self) -> StrList:
        """Generate command line arguments for remote execution."""
        args: StrList = []
        
        args.append(f"--system-type {shlex.quote(self.system_type)}")
        args.append(f"--username {shlex.quote(self.username)}")
        args.append(f"--machine {shlex.quote(self.machine_type)}")
        
        if self.password:
            args.append(f"--password {shlex.quote(self.password)}")
        
        if self.timezone:
            args.append(f"--timezone {shlex.quote(self.timezone)}")
        
        if self.friendly_name:
            args.append(f"--name {shlex.quote(self.friendly_name)}")
        
        if self.enable_rdp:
            args.append("--rdp")
        
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
        
        if self.custom_steps:
            args.append(f"--steps {shlex.quote(self.custom_steps)}")
        
        if self.deploy_latest:
            args.append("--deploy-latest")

        if self.deploy_specs:
            args.append("--lite-deploy")
            if self.full_deploy:
                args.append("--full-deploy")
            for deploy_spec, git_url in self.deploy_specs:
                args.append(f"--deploy {shlex.quote(deploy_spec)} {shlex.quote(git_url)}")
        
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

        if self.antistatic_db:
            args.append(f"--antistatic-db {shlex.quote(self.antistatic_db)}")

        if self.gogs:
            escaped_gogs = " ".join(shlex.quote(str(part)) for part in self.gogs)
            args.append(f"--gogs {escaped_gogs}")
        
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
        cmd_parts: StrList = [
            f"python3 infra_tools.py setup {shlex.quote(self.system_type)}",
            self.host,
        ]
        
        # Add username if different from current user or if requested
        if include_username:
            cmd_parts.append(self.username)
        
        # SSH key
        if self.ssh_key:
            cmd_parts.append(f"-k {shlex.quote(self.ssh_key)}")
        
        # Password is intentionally not included in the command line for security reasons.
        # If a password is required, it should be provided interactively or via a secure
        # mechanism instead of as a command-line argument.
        
        # Timezone
        if self.timezone and self.timezone != "UTC":
            cmd_parts.append(f"-t {shlex.quote(self.timezone)}")
        
        # Machine type (if not the current setup default for this flow)
        default_machine_type = _default_machine_type_for_setup(
            self.system_type,
            is_build_server=self.is_build_server,
        )
        if self.machine_type != default_machine_type:
            cmd_parts.append(f"--machine {shlex.quote(self.machine_type)}")
        
        # Name and tags
        if self.friendly_name:
            cmd_parts.append(f"--name {shlex.quote(self.friendly_name)}")
        
        if self.tags and len(self.tags) > 0:
            cmd_parts.append(f"--tags {shlex.quote(','.join(self.tags))}")
        
        # Desktop/workstation flags
        if self.enable_rdp:
            cmd_parts.append("--rdp")
        
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
        
        # Custom steps
        if self.custom_steps:
            cmd_parts.append(f"--steps {shlex.quote(self.custom_steps)}")
        
        # Deployments
        if self.deploy_latest:
            cmd_parts.append("--deploy-latest")

        if self.deploy_specs:
            if self.full_deploy:
                cmd_parts.append("--full-deploy")
            for deploy_spec, git_url in self.deploy_specs:
                cmd_parts.append(f"--deploy {shlex.quote(deploy_spec)} {shlex.quote(git_url)}")
        
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

        # Antistatic DB service
        if self.antistatic_db:
            cmd_parts.append(f"--antistatic-db {shlex.quote(self.antistatic_db)}")

        if self.gogs:
            escaped_gogs = " ".join(shlex.quote(str(part)) for part in self.gogs)
            cmd_parts.append(f"--gogs {escaped_gogs}")
        
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
        data.pop('share_credentials', None)
        data['samba_shares'] = _strip_passwords_from_samba_shares(self.samba_shares)
        data['smb_mounts'] = _strip_passwords_from_smb_mounts(self.smb_mounts)
        if self.tags:
            data['tags'] = ','.join(self.tags)
        return data
    
    @classmethod
    def from_dict(cls, host: str, system_type: str, data: JSONDict) -> 'SetupConfig':
        tags_str = data.get('tags')
        if tags_str and isinstance(tags_str, str):
            data['tags'] = [tag.strip() for tag in tags_str.split(',') if tag.strip()]
        elif not tags_str:
            data['tags'] = None

        data['container_storage'] = _normalize_container_storage(data.get('container_storage'))
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
            system_default=system_type_definition.default_machine_type,
            is_build_server=is_build_server,
        )
        
        include_desktop = (
            system_type_definition.include_desktop
            or enable_rdp
        )
        include_cli_tools = system_type_definition.include_cli_tools
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
        
        return cls(
            host=args.host,
            username=username,
            system_type=system_type,
            machine_type=machine_type,
            password=getattr(args, 'password', None),
            ssh_key=getattr(args, 'ssh_key', None),
            timezone=timezone,
            friendly_name=getattr(args, 'friendly_name', None),
            tags=tags,
            enable_rdp=enable_rdp,
            desktop=desktop,
            browser=browser,
            browsers=browsers,
            use_flatpak=getattr(args, 'use_flatpak', False),
            install_office=install_office,
            apt_packages=getattr(args, 'apt_packages', None),
            flatpak_packages=getattr(args, 'flatpak_packages', None),
            dark_theme=getattr(args, 'dark_theme', False),
            dry_run=getattr(args, 'dry_run', False),
            install_ruby=getattr(args, 'install_ruby', False),
            install_go=getattr(args, 'install_go', False),
            install_node=getattr(args, 'install_node', False),
            install_python=getattr(args, 'install_python', False),
            custom_steps=getattr(args, 'custom_steps', None),
            deploy_specs=getattr(args, 'deploy_specs', None),
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
            scrub_specs=getattr(args, 'scrub_specs', None),
            notify_specs=getattr(args, 'notify_specs', None),
            antistatic_server=getattr(args, 'antistatic_server', None),
            antistatic_db=getattr(args, 'antistatic_db', None),
            gogs=getattr(args, 'gogs', None),
            auto_restart=auto_restart,
            auto_restart_force_days=auto_restart_force_days,
            auto_restart_grace=auto_restart_grace,
            hosted_node=getattr(args, 'hosted_node', None),
            hosted_user=getattr(args, 'hosted_user', 'root'),
            hosted_key=getattr(args, 'hosted_key', None),
            container_memory=getattr(args, 'container_memory', None),
            container_storage=_normalize_container_storage(getattr(args, 'container_storage', None)),
            container_cores=getattr(args, 'container_cores', 1),
            container_base=getattr(args, 'container_base', 'debian'),
            vm_image=getattr(args, 'vm_image', None),
            include_desktop=include_desktop,
            include_cli_tools=include_cli_tools,
            include_desktop_apps=include_desktop_apps,
            include_workstation_dev_apps=include_workstation_dev_apps,
            include_pc_dev_apps=include_pc_dev_apps,
            include_web_server=include_web_server,
            include_web_firewall=include_web_firewall
        )
