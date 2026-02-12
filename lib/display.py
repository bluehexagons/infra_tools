#!/usr/bin/env python3
from __future__ import annotations

from typing import Optional
from lib.config import SetupConfig


def print_name_and_tags(config: SetupConfig) -> None:
    if config.friendly_name:
        print(f"Name: {config.friendly_name}")
    if config.tags and len(config.tags) > 0:
        print(f"Tags: {', '.join(config.tags)}")


def print_success_header(config: SetupConfig) -> None:
    print(f"Host: {config.host}")
    print(f"Username: {config.username}")
    if config.friendly_name or config.tags:
        print()
        print_name_and_tags(config)


def print_rdp_info(config: SetupConfig) -> None:
    if config.enable_rdp:
        print(f"RDP: {config.host}:3389")
        print(f"  Client: Remmina, Microsoft Remote Desktop")


def print_setup_summary(config: SetupConfig, description: Optional[str] = None) -> None:
    """Print a summary of the setup configuration."""
    if description:
        print("=" * 60)
        print(f"{description}")
        print("=" * 60)
    
    if config.host != "localhost":
        print(f"Host: {config.host}")
    
    if config.system_type != "server_proxmox":
        print(f"User: {config.username}")
    
    print(f"Timezone: {config.timezone}")
    
    if config.enable_rdp:
        print("RDP: Yes")
    if config.enable_smbclient:
        print("SMB Client: Yes")
    
    if config.desktop != "xfce" and (config.include_desktop or config.enable_rdp):
        print(f"Desktop: {config.desktop}")
    
    if config.browser and config.browser != "brave" and (config.include_desktop or config.include_desktop_apps or config.include_pc_dev_apps or config.include_workstation_dev_apps):
        print(f"Browser: {config.browser}")
    
    if config.use_flatpak:
        print("Flatpak: Yes")
    if config.install_office:
        print("Office: Yes")
    
    if config.dry_run:
        print("Dry-run: Yes")
    
    if config.custom_steps:
        print(f"Steps: {config.custom_steps}")
    
    if config.deploy_specs:
        print(f"Deployments: {len(config.deploy_specs)} repository(ies)")
        for location, git_url in config.deploy_specs:
            print(f"  - {git_url} -> {location}")
        if config.full_deploy:
            print("Full deploy: Yes (rebuild all deployments)")
        else:
            print("Full deploy: No (skip unchanged deployments)")
        if config.enable_ssl:
            print("SSL: Yes (Let's Encrypt)")
            if config.ssl_email:
                print(f"SSL Email: {config.ssl_email}")
        if config.enable_cloudflare:
            print("Cloudflare: Yes (tunnel preconfiguration)")
            if config.api_subdomain:
                print("  - API subdomain support enabled")
    
    if config.enable_samba:
        print("Samba: Yes")
        if config.samba_shares:
            print(f"Samba Shares: {len(config.samba_shares)} share(s)")
            for share in config.samba_shares:
                print(f"  - {share[1]}_{share[0]}: {share[2]}")
    
    if config.smb_mounts:
        print(f"SMB Mounts: {len(config.smb_mounts)} mount(s)")
        for mountpoint, ip, creds, share, subdir in config.smb_mounts:
            username = creds.split(':', 1)[0] if ':' in creds else creds
            print(f"  - {mountpoint} from //{ip}/{share}{subdir} (user: {username})")
    
    if config.sync_specs:
        print(f"Sync Jobs: {len(config.sync_specs)} job(s)")
        for source, dest, interval in config.sync_specs:
            print(f"  - {source} → {dest} ({interval})")
    
    if config.scrub_specs:
        print(f"Scrub Jobs: {len(config.scrub_specs)} job(s)")
        for directory, _db_path, redundancy, frequency in config.scrub_specs:
            print(f"  - {directory} ({redundancy}, {frequency})")
    
    if config.notify_specs:
        print(f"Notifications: {len(config.notify_specs)} target(s)")
        for notify_type, target in config.notify_specs:
            print(f"  - {notify_type}: {target}")
    
    print("=" * 60)
    print()
