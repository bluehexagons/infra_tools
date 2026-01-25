#!/usr/bin/env python3

from __future__ import annotations

import argparse


from lib.config import SYSTEM_TYPES, MACHINE_TYPES, DEFAULT_MACHINE_TYPE


def create_setup_argument_parser(
    description: str,
    for_remote: bool = False,
    allow_steps: bool = False
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    
    if not for_remote:
        parser.add_argument("host", help="IP address or hostname of the remote host")
        parser.add_argument("username", nargs="?", default=None, 
                           help="Username (defaults to current user)")
        parser.add_argument("-k", "--key", dest="ssh_key", help="SSH private key path")
    
    parser.add_argument("-p", "--password", help="User password")
    parser.add_argument("-t", "--timezone", help="Timezone (defaults to UTC)")
    parser.add_argument("--machine", dest="machine_type",
                       choices=MACHINE_TYPES,
                       default=DEFAULT_MACHINE_TYPE,
                       help=f"Machine type: unprivileged (LXC, default), vm, privileged, hardware, oci (Docker/Podman)")
    
    if not for_remote:
        parser.add_argument("--name", dest="friendly_name", help="Friendly name for this configuration")
        parser.add_argument("--tags", dest="tags", help="Comma-separated list of tags for this configuration")
    
    if for_remote:
        parser.add_argument("--system-type", dest="system_type", 
                           choices=SYSTEM_TYPES,
                           help="System type to setup")
        parser.add_argument("--username", default=None,
                           help="Username (defaults to current user, not used for server_proxmox)")
    
    if allow_steps or for_remote:
        parser.add_argument("--steps", dest="custom_steps", 
                           help="Space-separated list of steps to run (e.g., 'install_ruby install_node')")
    parser.add_argument("--rdp", dest="enable_rdp", 
                       action=argparse.BooleanOptionalAction, 
                       default=None if not for_remote else False,
                       help="Enable RDP/XRDP setup" + ("" if for_remote else " (default: enabled for workstation setups)"))
    parser.add_argument("--audio", dest="enable_audio", 
                       action=argparse.BooleanOptionalAction if not for_remote else "store_true", 
                       default=None if not for_remote else False,
                       help="Enable audio setup (desktop only)")
    parser.add_argument("--desktop", choices=["xfce", "i3", "cinnamon"], 
                       default="xfce" if for_remote else None,
                       help="Desktop environment to install (default: xfce)")
    parser.add_argument("--browser", choices=["brave", "firefox", "browsh", "vivaldi", "lynx"], 
                       default=None,
                       help="Web browser to install (default: brave for desktop setups)")
    parser.add_argument("--flatpak", dest="use_flatpak", 
                       action=argparse.BooleanOptionalAction if not for_remote else "store_true", 
                       default=None if not for_remote else False,
                       help="Install desktop apps via Flatpak when available (non-containerized environments)")
    parser.add_argument("--office", dest="install_office", 
                       action=argparse.BooleanOptionalAction if not for_remote else "store_true", 
                       default=None if not for_remote else False,
                       help="Install LibreOffice (desktop only)")
    
    # Development tools
    parser.add_argument("--ruby", dest="install_ruby", 
                       action=argparse.BooleanOptionalAction if not for_remote else "store_true", 
                       default=None if not for_remote else False,
                       help="Install rbenv + latest Ruby version")
    parser.add_argument("--go", dest="install_go", 
                       action=argparse.BooleanOptionalAction if not for_remote else "store_true", 
                       default=None if not for_remote else False,
                       help="Install latest Go version")
    parser.add_argument("--node", dest="install_node", 
                       action=argparse.BooleanOptionalAction if not for_remote else "store_true", 
                       default=None if not for_remote else False,
                       help="Install nvm + latest Node.JS + PNPM + update NPM")
    
    # Deployment options
    parser.add_argument("--deploy", dest="deploy_specs", 
                       action="append", nargs=2, metavar=("DOMAIN_OR_PATH", "GIT_URL"),
                       help="Deploy a git repository (domain.com/path or /path) to auto-configure nginx (can be used multiple times)")
    
    if for_remote:
        parser.add_argument("--lite-deploy", action="store_true",
                           help="Use pre-uploaded repository files instead of cloning (for remote execution)")
    
    parser.add_argument("--full-deploy", dest="full_deploy", action="store_true",
                       help="Always rebuild deployments even if they haven't changed (default: skip unchanged deployments)")
    parser.add_argument("--ssl", dest="enable_ssl", 
                       action=argparse.BooleanOptionalAction if not for_remote else "store_true", 
                       default=None if not for_remote else False,
                       help="Enable Let's Encrypt SSL/TLS certificates for deployed domains")
    parser.add_argument("--ssl-email", dest="ssl_email",
                       help="Email address for Let's Encrypt registration (optional)")
    parser.add_argument("--cloudflare", dest="enable_cloudflare", 
                       action=argparse.BooleanOptionalAction if not for_remote else "store_true", 
                       default=None if not for_remote else False,
                       help="Preconfigure server for Cloudflare tunnel (disables public HTTP/HTTPS ports)")
    parser.add_argument("--api-subdomain", dest="api_subdomain", 
                       action=argparse.BooleanOptionalAction if not for_remote else "store_true", 
                       default=None if not for_remote else False,
                       help="Deploy Rails API as a subdomain (api.domain.com) instead of a subdirectory (domain.com/api)")
    
    parser.add_argument("--samba", dest="enable_samba", 
                       action=argparse.BooleanOptionalAction if not for_remote else "store_true", 
                       default=None if not for_remote else False,
                       help="Install and configure Samba for SMB file sharing")
    parser.add_argument("--share", dest="samba_shares", 
                       action="append", nargs=4, metavar=("ACCESS_TYPE", "SHARE_NAME", "PATHS", "USERS"),
                       help="Configure Samba share: access_type (read|write), share_name, comma-separated paths, comma-separated username:password pairs (can be used multiple times)")
    
    parser.add_argument("--smbclient", dest="enable_smbclient", 
                       action=argparse.BooleanOptionalAction if not for_remote else "store_true", 
                       default=None if not for_remote else False,
                       help="Install SMB/CIFS client packages for connecting to network shares (default: enabled for pc_dev)")
    
    parser.add_argument("--mount-smb", dest="smb_mounts",
                       action="append", nargs=5, metavar=("MOUNTPOINT", "IP", "CREDENTIALS", "SHARE", "SUBDIR"),
                       help="Mount SMB share: /mnt/path, ip_address, username:password, share_name, /share/subdirectory (can be used multiple times). Auto-enables --smbclient")
    
    parser.add_argument("--sync", dest="sync_specs", 
                       action="append", nargs=3, metavar=("SOURCE", "DESTINATION", "INTERVAL"),
                       help="Configure directory synchronization: source_path, destination_path, interval (hourly|daily|weekly|monthly). Uses rsync with systemd timer (can be used multiple times)")
    
    parser.add_argument("--scrub", dest="scrub_specs",
                       action="append", nargs=4, metavar=("DIRECTORY", "DATABASE_PATH", "REDUNDANCY", "FREQUENCY"),
                       help="Configure data integrity checking: /path/to/directory, relative/or/absolute/path/to/.pardatabase, redundancy%%, frequency (hourly|daily|weekly|monthly). Uses par2 with systemd timer (can be used multiple times)")
    
    parser.add_argument("--dry-run", action="store_true",
                       help="Show what would be done without executing commands")
    
    return parser
