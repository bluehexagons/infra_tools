#!/usr/bin/env python3
"""
infra_tools - Unified entry point for infrastructure setup and management.

This script provides a unified interface to all infra_tools functionality,
combining setup and patch operations into a single command-line tool.

Usage:
    infra_tools.py setup <system_type> <host> [options]
    infra_tools.py patch <host> [options]
    infra_tools.py --help

System Types:
    workstation_desktop  Desktop workstation setup
    pc_dev              PC development environment
    workstation_dev     Developer workstation setup
    server_dev          Development server setup
    server_web          Web server setup
    server_lite         Lightweight server setup
    server_proxmox      Proxmox server setup
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.cache import load_setup_command, merge_setup_configs, save_setup_command
from lib.config import SetupConfig
from lib.credentials import (
    list_workspace_credentials,
    prepare_runtime_config,
    remove_workspace_credential,
    set_workspace_credential,
    store_cli_credentials,
)
from lib.display import print_name_and_tags, print_setup_summary, print_success_header
from lib.notifications import validate_notification_args
from lib.plugin_registry import format_system_type_help, get_system_type_names
from lib.setup_common import REMOTE_SCRIPT_PATH, run_remote_setup
from lib.system_utils import get_current_username
from lib.validators import validate_host, validate_username
from lib.validation import validate_workspace_dir
from lib.workspace import get_workspace_dir, set_workspace_dir
from smb.samba_steps import validate_samba_share_credentials


def _build_infra_tools_epilog() -> str:
    return f"""Available Commands:
  setup <type> <host> [args]   Run initial setup for a system type
  patch <host> [args]          Patch/update an existing system

System Types for setup:
{format_system_type_help()}

Examples:
  infra_tools.py setup server_web 192.168.1.100 admin --ssl
  infra_tools.py patch 192.168.1.100 --deploy api.example.com https://github.com/user/api.git
"""


def create_infra_tools_parser() -> Tuple[argparse.ArgumentParser, argparse.ArgumentParser, argparse.ArgumentParser]:
    """Create the main argument parser for infra_tools."""
    parser = argparse.ArgumentParser(
        prog="infra_tools.py",
        description="Unified infrastructure setup and management tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_build_infra_tools_epilog()
    )
    parser.add_argument(
        "--workspace",
        help="Workspace root for saved setups, credentials, known_hosts, and history"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Setup subcommand
    setup_parser = subparsers.add_parser(
        "setup",
        help="Run initial setup for a system type",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Run 'infra_tools.py setup --help' for full options"
    )
    setup_parser.add_argument(
        "system_type",
        choices=get_system_type_names(),
        help="Type of system to set up"
    )
    setup_parser.add_argument(
        "host",
        help="IP address or hostname of the remote host"
    )
    setup_parser.add_argument(
        "username",
        nargs="?",
        default=None,
        help="Username (defaults to current user)"
    )
    
    # Patch subcommand
    patch_parser = subparsers.add_parser(
        "patch",
        help="Patch/update an existing system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Run 'infra_tools.py patch --help' for full options"
    )
    patch_parser.add_argument(
        "host",
        help="IP address or hostname of the remote host"
    )
    patch_parser.add_argument(
        "username",
        nargs="?",
        default=None,
        help="Username (defaults to current user)"
    )

    credentials_parser = subparsers.add_parser(
        "credentials",
        help="Manage workspace credentials",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    credentials_parser.add_argument(
        "--workspace",
        help="Workspace root for saved setups, credentials, known_hosts, and history"
    )
    credentials_subparsers = credentials_parser.add_subparsers(dest="credentials_command", help="Credential commands")

    credentials_set_parser = credentials_subparsers.add_parser("set", help="Save or replace a credential")
    credentials_set_parser.add_argument("username", help="Credential username")
    credentials_set_parser.add_argument("password", help="Credential password")

    credentials_subparsers.add_parser("list", help="List saved credential usernames")

    credentials_remove_parser = credentials_subparsers.add_parser("remove", help="Remove a saved credential")
    credentials_remove_parser.add_argument("username", help="Credential username to remove")
    
    return parser, setup_parser, patch_parser


def add_common_arguments(parser: argparse.ArgumentParser, for_patch: bool = False) -> None:
    """Add common setup/patch arguments to a parser."""
    parser.add_argument(
        "--workspace",
        help="Workspace root for saved setups, credentials, known_hosts, and history"
    )
    parser.add_argument("-k", "--key", dest="ssh_key", help="SSH private key path")
    parser.add_argument("-p", "--password", help="User password")
    parser.add_argument("-t", "--timezone", help="Timezone (defaults to UTC)")
    parser.add_argument("--machine", dest="machine_type",
                       choices=["unprivileged", "vm", "privileged", "hardware", "oci"],
                       default="unprivileged",
                       help="Machine type: unprivileged (LXC, default), vm, privileged, hardware, oci")
    
    parser.add_argument("--name", dest="friendly_name", help="Friendly name for this configuration")
    parser.add_argument("--tags", dest="tags", help="Comma-separated list of tags for this configuration")
    
    parser.add_argument("--steps", dest="custom_steps",
                       help="Space-separated list of steps to run (e.g., 'install_ruby install_node')")
    parser.add_argument("--rdp", dest="enable_rdp",
                       action=argparse.BooleanOptionalAction,
                       default=None,
                       help="Enable RDP/XRDP setup")
    parser.add_argument("--desktop", choices=["xfce", "i3", "cinnamon", "lxqt"],
                       default=None,
                       help="Desktop environment to install (default: xfce)")
    parser.add_argument("--browser", dest="browsers",
                       action="append",
                       choices=["brave", "firefox", "browsh", "vivaldi", "lynx", "librewolf"],
                       help="Web browser to install (can be used multiple times)")
    parser.add_argument("--flatpak", dest="use_flatpak",
                       action=argparse.BooleanOptionalAction,
                       default=None,
                       help="Install desktop apps via Flatpak when available")
    parser.add_argument("--office", dest="install_office",
                       action=argparse.BooleanOptionalAction,
                       default=None,
                       help="Install LibreOffice (desktop only)")
    parser.add_argument("--apt-install", dest="apt_packages",
                       action="append",
                       metavar="PACKAGE",
                       help="Install package via apt (can be used multiple times)")
    parser.add_argument("--flatpak-install", dest="flatpak_packages",
                       action="append",
                       metavar="PACKAGE",
                       help="Install package via flatpak (can be used multiple times)")
    parser.add_argument("--dark", dest="dark_theme",
                       action=argparse.BooleanOptionalAction,
                       default=None,
                       help="Configure desktop to use dark theme")
    parser.add_argument("--ruby", dest="install_ruby",
                       action=argparse.BooleanOptionalAction,
                       default=None,
                       help="Install Ruby + Bundler from apt packages")
    parser.add_argument("--go", dest="install_go",
                       action=argparse.BooleanOptionalAction,
                       default=None,
                       help="Install latest Go version")
    parser.add_argument("--node", dest="install_node",
                       action=argparse.BooleanOptionalAction,
                       default=None,
                       help="Install nvm + latest Node.JS + PNPM + update NPM")
    parser.add_argument("--python", dest="install_python",
                       action=argparse.BooleanOptionalAction,
                       default=None,
                       help="Install Python tooling (python aliases and uv)")
    parser.add_argument("--deploy", dest="deploy_specs",
                       action="append", nargs=2, metavar=("DOMAIN_OR_PATH", "GIT_URL"),
                       help="Deploy a git repository to auto-configure nginx (can be used multiple times)")
    parser.add_argument("--full-deploy", dest="full_deploy", action="store_true",
                       help="Always rebuild deployments even if they haven't changed")
    parser.add_argument("--reset-migrations", dest="reset_migrations", action="store_true",
                       help="Reset Rails database schema using db:schema:load")
    parser.add_argument("--ssl", dest="enable_ssl",
                       action=argparse.BooleanOptionalAction,
                       default=None,
                       help="Enable Let's Encrypt SSL/TLS certificates for deployed domains")
    parser.add_argument("--ssl-email", dest="ssl_email",
                       help="Email address for Let's Encrypt registration (optional)")
    parser.add_argument("--cloudflare", dest="enable_cloudflare",
                       action=argparse.BooleanOptionalAction,
                       default=None,
                       help="Preconfigure server for Cloudflare tunnel")
    parser.add_argument("--api-subdomain", dest="api_subdomain",
                       action=argparse.BooleanOptionalAction,
                       default=None,
                       help="Deploy Rails API as a subdomain instead of subdirectory")
    parser.add_argument("--cicd", dest="enable_cicd",
                       action=argparse.BooleanOptionalAction,
                       default=None,
                       help="Install webhook-based CI/CD system for GitHub Actions")
    parser.add_argument("--build-server", dest="is_build_server",
                       action=argparse.BooleanOptionalAction,
                       default=None,
                       help="Configure as a build server that deploys to app servers")
    parser.add_argument("--app-server", dest="is_app_server",
                       action=argparse.BooleanOptionalAction,
                       default=None,
                       help="Configure as a lightweight app server to receive deployments")
    parser.add_argument("--deploy-target", dest="deploy_targets",
                       action="append", metavar="HOST",
                       help="Target app server for deployments (can be used multiple times)")
    parser.add_argument("--samba", dest="enable_samba",
                       action=argparse.BooleanOptionalAction,
                       default=None,
                       help="Install and configure Samba for SMB file sharing")
    parser.add_argument("--share", dest="samba_shares",
                       action="append", nargs=4,
                       metavar=("ACCESS_TYPE", "SHARE_NAME", "PATHS", "USERS"),
                       help="Configure Samba share (can be used multiple times)")
    parser.add_argument("--credential", dest="share_credentials",
                        action="append", nargs=2, metavar=("USERNAME", "PASSWORD"),
                        help="Save a workspace credential and let --share/--mount-smb reference the username without inline passwords")
    parser.add_argument("--smbclient", dest="enable_smbclient",
                       action=argparse.BooleanOptionalAction,
                       default=None,
                       help="Install SMB/CIFS client packages for connecting to network shares")
    parser.add_argument("--mount-smb", dest="smb_mounts",
                        action="append", nargs=5,
                        metavar=("MOUNTPOINT", "IP", "CREDENTIALS", "SHARE", "SUBDIR"),
                        help="Mount SMB share using username or username:password credentials (can be used multiple times)")
    parser.add_argument("--sync", dest="sync_specs",
                       action="append", nargs=3,
                       metavar=("SOURCE", "DESTINATION", "INTERVAL"),
                       help="Configure directory synchronization (hourly|daily|weekly|monthly)")
    parser.add_argument("--scrub", dest="scrub_specs",
                       action="append", nargs=4,
                       metavar=("DIRECTORY", "DATABASE_PATH", "REDUNDANCY", "FREQUENCY"),
                       help="Configure data integrity checking")
    parser.add_argument("--notify", dest="notify_specs",
                       action="append", nargs=2, metavar=("TYPE", "TARGET"),
                       help="Configure notification target: webhook URL or email address")
    parser.add_argument("--no-restart", dest="no_restart", action="store_true",
                       help="Disable automatic restarts after updates")
    parser.add_argument("--dry-run", action="store_true",
                       help="Show what would be done without executing commands")


def run_setup_command(args: argparse.Namespace) -> int:
    """Execute the setup command."""
    if not validate_host(args.host):
        print(f"Error: Invalid IP address or hostname: {args.host}")
        return 1
    
    username = args.username if args.username else get_current_username()
    
    if not validate_username(username):
        print(f"Error: Invalid username: {username}")
        return 1
    
    config = SetupConfig.from_args(args, args.system_type)
    
    try:
        runtime_config = prepare_runtime_config(config)
        validate_notification_args(runtime_config.notify_specs)
        validate_samba_share_credentials(runtime_config)
    except ValueError as e:
        print(f"Error: {e}")
        return 1
    
    description = f"{args.system_type.replace('_', ' ').title()} Setup"
    print_setup_summary(config, description)
    
    if not config.dry_run:
        store_cli_credentials(config)
        save_setup_command(config)
    
    if not os.path.exists(REMOTE_SCRIPT_PATH):
        print(f"Error: Remote setup script not found: {REMOTE_SCRIPT_PATH}")
        return 1
    
    start_time = time.time()
    returncode = 1
    try:
        returncode = run_remote_setup(runtime_config)
    finally:
        end_time = time.time()
        success = (returncode == 0)
        if not config.dry_run:
            save_setup_command(config, start_time, end_time, success)
    
    if returncode != 0:
        print(f"\n✗ Setup failed (exit code: {returncode})")
        return 1
    
    print()
    print("=" * 60)
    print("Setup Complete!")
    print("=" * 60)
    print_success_header(config)
    print()
    print(f"Connect via SSH: ssh {config.username}@{config.host}")
    if args.system_type == "server_web":
        print(f"View website: http://{config.host}")
    print("=" * 60)
    
    return 0


def run_patch_command(args: argparse.Namespace) -> int:
    """Execute the patch command."""
    if not validate_host(args.host):
        print(f"Error: Invalid IP address or hostname: {args.host}")
        return 1
    
    username = args.username if args.username else get_current_username()
    
    if not validate_username(username):
        print(f"Error: Invalid username: {username}")
        return 1
    
    cached_config = load_setup_command(args.host)
    if not cached_config:
        print(f"Error: No cached setup found for {args.host}")
        print(f"Please run the initial setup first using 'infra_tools.py setup <system_type> {args.host}'")
        return 1
    
    new_config = SetupConfig.from_args(args, cached_config.system_type)
    merged_config = merge_setup_configs(cached_config, new_config)
    try:
        runtime_config = prepare_runtime_config(merged_config)
        validate_notification_args(runtime_config.notify_specs)
        validate_samba_share_credentials(runtime_config)
    except ValueError as e:
        print(f"Error: {e}")
        return 1
    
    # Execute patch
    if not os.path.exists(REMOTE_SCRIPT_PATH):
        print(f"Error: Remote setup script not found: {REMOTE_SCRIPT_PATH}")
        return 1
    
    print("=" * 60)
    print(f"Patching System: {merged_config.system_type}")
    print("=" * 60)
    print(f"Host: {merged_config.host}")
    print(f"User: {merged_config.username}")
    print(f"Timezone: {merged_config.timezone}")
    print("=" * 60)
    print()
    
    start_time = time.time()
    returncode = 1
    try:
        if not merged_config.dry_run:
            store_cli_credentials(merged_config)
        returncode = run_remote_setup(runtime_config)
    finally:
        end_time = time.time()
        success = (returncode == 0)
        if not merged_config.dry_run:
            save_setup_command(merged_config, start_time, end_time, success)
    
    if returncode != 0:
        print(f"\n✗ Patch failed (exit code: {returncode})")
        return 1
    
    print()
    print("=" * 60)
    print("Patch Complete!")
    print("=" * 60)
    print(f"Host: {merged_config.host}")
    print(f"System has been updated with new configuration")
    
    if merged_config.friendly_name or merged_config.tags:
        print()
        print_name_and_tags(merged_config)
    
    print("=" * 60)
    
    return 0


def main() -> int:
    """Main entry point for infra_tools."""
    parser, setup_parser, patch_parser = create_infra_tools_parser()
    
    # Add common arguments to both subparsers
    add_common_arguments(setup_parser, for_patch=False)
    add_common_arguments(patch_parser, for_patch=True)
    
    args = parser.parse_args()
    if getattr(args, 'workspace', None):
        try:
            validate_workspace_dir(args.workspace)
        except ValueError as e:
            print(f"Error: {e}")
            return 1
        set_workspace_dir(args.workspace)
    
    if not args.command:
        parser.print_help()
        return 0
    
    if args.command == "setup":
        return run_setup_command(args)
    elif args.command == "patch":
        return run_patch_command(args)
    elif args.command == "credentials":
        try:
            if args.credentials_command == "set":
                set_workspace_credential(args.username, args.password)
                print(f"Saved credential for {args.username} in {get_workspace_dir()}")
                return 0
            if args.credentials_command == "list":
                usernames = list_workspace_credentials()
                if not usernames:
                    print("No saved credentials.")
                    return 0
                for username in usernames:
                    print(username)
                return 0
            if args.credentials_command == "remove":
                removed = remove_workspace_credential(args.username)
                if removed:
                    print(f"Removed credential for {args.username}")
                else:
                    print(f"No saved credential for {args.username}")
                return 0
        except ValueError as e:
            print(f"Error: {e}")
            return 1
        print("Error: credentials command required (set, list, remove)")
        return 1
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
