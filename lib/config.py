#!/usr/bin/env python3

from __future__ import annotations

import argparse
import shlex
from dataclasses import dataclass, asdict
from typing import Optional
from lib.types import StrList, NestedStrList, JSONDict, MaybeStr


SYSTEM_TYPES = [
    "workstation_desktop",
    "pc_dev",
    "workstation_dev",
    "server_dev",
    "server_web",
    "server_lite",
    "server_proxmox",
    "custom_steps"
]

MACHINE_TYPES = ["unprivileged", "vm", "privileged", "hardware", "oci"]
DEFAULT_MACHINE_TYPE = "unprivileged"

DESKTOP_SYSTEMS = ["workstation_desktop", "pc_dev", "workstation_dev"]
CLI_SYSTEMS = ["workstation_desktop", "pc_dev", "workstation_dev", "server_dev", "server_web"]


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
    enable_audio: bool = False
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
    custom_steps: Optional[str] = None
    deploy_specs: Optional[NestedStrList] = None
    full_deploy: bool = False
    enable_ssl: bool = False
    ssl_email: Optional[str] = None
    enable_cloudflare: bool = False
    api_subdomain: bool = False
    enable_samba: bool = False
    samba_shares: Optional[NestedStrList] = None
    enable_smbclient: bool = False
    smb_mounts: Optional[NestedStrList] = None
    sync_specs: Optional[NestedStrList] = None
    scrub_specs: Optional[NestedStrList] = None
    notify_specs: Optional[NestedStrList] = None
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
        
        if self.enable_rdp:
            args.append("--rdp")
        
        if self.enable_audio:
            args.append("--audio")
        
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
        
        if self.custom_steps:
            args.append(f"--steps {shlex.quote(self.custom_steps)}")
        
        if self.deploy_specs:
            args.append("--lite-deploy")
            if self.full_deploy:
                args.append("--full-deploy")
            for deploy_spec, git_url in self.deploy_specs:
                args.append(f"--deploy {shlex.quote(deploy_spec)} {shlex.quote(git_url)}")
        
        if self.enable_ssl:
            args.append("--ssl")
            if self.ssl_email:
                args.append(f"--ssl-email {shlex.quote(self.ssl_email)}")
        
        if self.enable_cloudflare:
            args.append("--cloudflare")
        
        if self.api_subdomain:
            args.append("--api-subdomain")
        
        if self.enable_samba:
            args.append("--samba")
        
        if self.samba_shares:
            for share_spec in self.samba_shares:
                escaped_spec = ' '.join(shlex.quote(str(s)) for s in share_spec)
                args.append(f"--share {escaped_spec}")
        
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
                
        return args
    
    def to_setup_command(self, include_username: bool = True) -> StrList:
        """Generate command line for user-facing setup script.
        
        Returns a list of command parts that can be joined with spaces or newlines.
        """
        cmd_parts: StrList = [f"python3 setup_{self.system_type}.py", self.host]
        
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
        
        # Machine type (if not default)
        if self.machine_type != DEFAULT_MACHINE_TYPE:
            cmd_parts.append(f"--machine {shlex.quote(self.machine_type)}")
        
        # Name and tags
        if self.friendly_name:
            cmd_parts.append(f"--name {shlex.quote(self.friendly_name)}")
        
        if self.tags and len(self.tags) > 0:
            cmd_parts.append(f"--tags {shlex.quote(','.join(self.tags))}")
        
        # Desktop/workstation flags
        if self.enable_rdp:
            cmd_parts.append("--rdp")
        
        if self.enable_audio:
            cmd_parts.append("--audio")
        
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
        
        # Custom steps
        if self.custom_steps:
            cmd_parts.append(f"--steps {shlex.quote(self.custom_steps)}")
        
        # Deployments
        if self.deploy_specs:
            if self.full_deploy:
                cmd_parts.append("--full-deploy")
            for deploy_spec, git_url in self.deploy_specs:
                cmd_parts.append(f"--deploy {shlex.quote(deploy_spec)} {shlex.quote(git_url)}")
        
        # SSL
        if self.enable_ssl:
            cmd_parts.append("--ssl")
            if self.ssl_email:
                cmd_parts.append(f"--ssl-email {shlex.quote(self.ssl_email)}")
        
        # Cloudflare
        if self.enable_cloudflare:
            cmd_parts.append("--cloudflare")
        
        if self.api_subdomain:
            cmd_parts.append("--api-subdomain")
        
        # Samba
        if self.enable_samba:
            cmd_parts.append("--samba")
        
        if self.samba_shares:
            for share_spec in self.samba_shares:
                escaped_spec = ' '.join(shlex.quote(str(s)) for s in share_spec)
                cmd_parts.append(f"--share {escaped_spec}")
        
        # SMB client
        if self.enable_smbclient:
            cmd_parts.append("--smbclient")
        
        # SMB mounts
        if self.smb_mounts:
            for mount_spec in self.smb_mounts:
                escaped_spec = ' '.join(shlex.quote(str(s)) for s in mount_spec)
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
        
        return cmd_parts

    def to_dict(self) -> JSONDict:
        data = asdict(self)
        data.pop('host', None)
        data.pop('system_type', None)
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
            
        if 'friendly_name' not in data:
            data['friendly_name'] = None
            
        return cls(host=host, system_type=system_type, **data)
    
    @classmethod
    def from_args(cls, args: argparse.Namespace, system_type: str) -> 'SetupConfig':
        from lib.system_utils import get_current_username, get_local_timezone
        
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
        elif system_type in DESKTOP_SYSTEMS:
            # Default browser for desktop systems
            browser = "librewolf"
        
        install_office = args.install_office
        if system_type == "pc_dev" and install_office is None:
            install_office = True
        elif install_office is None:
            install_office = False
        
        enable_rdp = args.enable_rdp
        if enable_rdp is None and system_type in DESKTOP_SYSTEMS:
            enable_rdp = True
        elif enable_rdp is None:
            enable_rdp = False
        
        enable_audio = getattr(args, 'enable_audio', False)
        
        smb_mounts = getattr(args, 'smb_mounts', None)
        enable_smbclient = getattr(args, 'enable_smbclient', None)
        if enable_smbclient is None and (system_type == "pc_dev" or smb_mounts):
            enable_smbclient = True
        elif enable_smbclient is None:
            enable_smbclient = False
        
        include_desktop = (
            system_type in DESKTOP_SYSTEMS
            or enable_rdp
        )
        include_cli_tools = system_type in CLI_SYSTEMS
        include_desktop_apps = system_type == "workstation_desktop"
        include_workstation_dev_apps = system_type == "workstation_dev"
        include_pc_dev_apps = system_type == "pc_dev"
        include_web_server = system_type == "server_web"
        include_web_firewall = system_type == "server_web"
        
        return cls(
            host=args.host,
            username=username,
            system_type=system_type,
            machine_type=getattr(args, 'machine_type', None) or DEFAULT_MACHINE_TYPE,
            password=getattr(args, 'password', None),
            ssh_key=getattr(args, 'ssh_key', None),
            timezone=timezone,
            friendly_name=getattr(args, 'friendly_name', None),
            tags=tags,
            enable_rdp=enable_rdp,
            enable_audio=enable_audio,
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
            custom_steps=getattr(args, 'custom_steps', None),
            deploy_specs=getattr(args, 'deploy_specs', None),
            full_deploy=getattr(args, 'full_deploy', False),
            enable_ssl=getattr(args, 'enable_ssl', False),
            ssl_email=getattr(args, 'ssl_email', None),
            enable_cloudflare=getattr(args, 'enable_cloudflare', False),
            api_subdomain=getattr(args, 'api_subdomain', False),
            enable_samba=getattr(args, 'enable_samba', False),
            samba_shares=getattr(args, 'samba_shares', None),
            enable_smbclient=enable_smbclient,
            smb_mounts=smb_mounts,
            sync_specs=getattr(args, 'sync_specs', None),
            scrub_specs=getattr(args, 'scrub_specs', None),
            notify_specs=getattr(args, 'notify_specs', None),
            include_desktop=include_desktop,
            include_cli_tools=include_cli_tools,
            include_desktop_apps=include_desktop_apps,
            include_workstation_dev_apps=include_workstation_dev_apps,
            include_pc_dev_apps=include_pc_dev_apps,
            include_web_server=include_web_server,
            include_web_firewall=include_web_firewall
        )
