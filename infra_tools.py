#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
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
import json
import os
import sys
import time
from typing import Optional, Tuple, cast

try:
    import argcomplete
except ImportError:
    argcomplete = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.cache import get_cache_path_for_host, load_setup_command, merge_setup_configs, save_setup_command
from lib.completions import run_completion_setup
from lib.config import SetupConfig
from lib.credentials import (
    list_workspace_credentials,
    prepare_runtime_config,
    remove_workspace_credential,
    set_workspace_credential,
    store_cli_credentials,
)
from lib.display import print_name_and_tags, print_setup_summary, print_success_header
from lib.interactive_shell import run_interactive_shell
from lib.notifications import validate_notification_args
from lib.orchestrator_bootstrap import run_orchestrator_bootstrap
from lib.plugin_registry import format_system_type_help, get_system_type_names
from lib.proxmox_cli import add_proxmox_subparser, run_proxmox_command
from lib.python_setup import run_local_python_setup
from lib.recall import run_recall_command
from lib.reconstruct import run_reconstruct_command
from lib.setup_common import REMOTE_SCRIPT_PATH, run_remote_setup
from lib.system_utils import get_current_username
from lib.types import Deployments, JSONDict, JSONList, StrList
from lib.validators import validate_host, validate_username
from lib.validation import (
    validate_apt_packages,
    validate_deploy_specs,
    validate_deploy_targets,
    validate_hosted_flags,
    validate_samba_share_credentials,
    validate_samba_share_specs,
    validate_smb_mount_specs,
    validate_scrub_specs,
    validate_ssl_email,
    validate_sync_specs,
    validate_timezone_name,
    validate_workspace_dir,
)
from lib.workspace import get_setup_cache_dir, get_workspace_dir, set_workspace_dir


def _build_infra_tools_epilog() -> str:
    return f"""Available Commands:
    setup <type> <host> [args]   Run initial setup for a system type
    patch <host> [args]          Patch/update an existing system
    list [pattern]              List saved configurations
    info [pattern]              Show saved configuration details
    cmd [pattern]               Show reconstructed setup commands
    rm <pattern>                Remove saved configurations
    deploy <pattern>            Redeploy saved configurations
    recall <host> [username]    Fetch or reconstruct a remote setup command
    reconstruct                 Analyze this host and emit a setup summary
    completions                 Install shell completion for infra_tools.py
    python-tools                Install local Python aliases, uv, and completion
    bootstrap                   Install packages, launcher, and completions (alias: self-setup)
    proxmox [subcommand]        Manage Proxmox hosts and containers (interactive shell with no args)
    shell                       Interactive REPL for managing saved configurations
    credentials                 Manage workspace credentials

System Types for setup:
{format_system_type_help()}

Examples:
  infra_tools.py setup server_web 192.168.1.100 admin --ssl
  infra_tools.py patch 192.168.1.100 --deploy api.example.com https://github.com/user/api.git
  infra_tools.py list prod
  infra_tools.py deploy prod --yes
  infra_tools.py recall example.com admin
  infra_tools.py completions --shell zsh
  sudo python3 infra_tools.py self-setup --user admin
  infra_tools list prod    # after self-setup, the launcher is on PATH
 """


def _current_command_name() -> str:
    return os.path.basename(sys.argv[0]) or "infra_tools.py"


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

    list_parser = subparsers.add_parser(
        "list",
        aliases=["ls"],
        help="List saved configurations",
    )
    list_parser.add_argument("pattern", nargs="?", default=None, help="Optional host, name, or tag filter")
    list_parser.add_argument(
        "--workspace",
        help="Workspace root for saved setups, credentials, known_hosts, and history"
    )
    list_parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as a JSON array for scripting",
    )

    info_parser = subparsers.add_parser(
        "info",
        help="Show saved configuration details",
    )
    info_parser.add_argument("pattern", nargs="?", default=None, help="Optional host, name, or tag filter")
    info_parser.add_argument(
        "--workspace",
        help="Workspace root for saved setups, credentials, known_hosts, and history"
    )
    info_parser.add_argument(
        "--compact",
        action="store_true",
        help="Show one-line summary per configuration instead of full details",
    )

    cmd_parser = subparsers.add_parser(
        "cmd",
        aliases=["command"],
        help="Show reconstructed setup commands",
    )
    cmd_parser.add_argument("pattern", nargs="?", default=None, help="Optional host, name, or tag filter")
    cmd_parser.add_argument(
        "--workspace",
        help="Workspace root for saved setups, credentials, known_hosts, and history"
    )

    remove_parser = subparsers.add_parser(
        "rm",
        aliases=["remove"],
        help="Remove saved configurations",
    )
    remove_parser.add_argument("pattern", help="Host, name, or tag filter to remove")
    remove_parser.add_argument("-y", "--yes", action="store_true", help="Remove without prompting")
    remove_parser.add_argument(
        "--workspace",
        help="Workspace root for saved setups, credentials, known_hosts, and history"
    )

    deploy_parser = subparsers.add_parser(
        "deploy",
        help="Redeploy saved configurations",
    )
    deploy_parser.add_argument("pattern", help="Host, name, or tag filter to redeploy")
    deploy_parser.add_argument("-y", "--yes", action="store_true", help="Deploy without prompting")
    deploy_parser.add_argument(
        "--workspace",
        help="Workspace root for saved setups, credentials, known_hosts, and history"
    )

    recall_parser = subparsers.add_parser(
        "recall",
        help="Fetch or reconstruct a remote setup command",
    )
    recall_parser.add_argument("host", help="IP address or hostname of the remote host")
    recall_parser.add_argument(
        "username",
        nargs="?",
        default=None,
        help="Username (defaults to current user)",
    )
    recall_parser.add_argument("-k", "--key", dest="ssh_key", help="SSH private key path")

    reconstruct_parser = subparsers.add_parser(
        "reconstruct",
        help="Analyze this host and emit a reconstructed setup summary",
    )
    reconstruct_parser.add_argument(
        "--compact",
        "-c",
        action="store_true",
        help="Output compact JSON (default: pretty-printed)",
    )

    completions_parser = subparsers.add_parser(
        "completions",
        help="Install shell completion for infra_tools.py",
    )
    completions_parser.add_argument(
        "--shell",
        choices=["bash", "zsh", "fish", "tcsh", "auto"],
        default="auto",
        help="Shell type (default: auto-detect)",
    )
    completions_parser.add_argument(
        "--global",
        dest="global_install",
        action="store_true",
        help="Install completions system-wide (requires sudo/root)",
    )
    completions_parser.add_argument(
        "--user",
        action="store_true",
        help="Install completions for current user only (default)",
    )

    python_tools_parser = subparsers.add_parser(
        "python-tools",
        aliases=["admin-python"],
        help="Install local Python aliases, uv, and completion",
    )
    python_tools_parser.add_argument(
        "--shell",
        choices=["bash", "zsh", "fish", "tcsh"],
        default="bash",
        help="Shell to configure for completion (default: bash)",
    )
    python_tools_parser.add_argument(
        "--script-path",
        dest="script_path",
        default=None,
        help="Absolute path to infra_tools.py (used to install the user launcher)",
    )

    bootstrap_parser = subparsers.add_parser(
        "bootstrap",
        aliases=["self-setup"],
        help="Install local packages, launcher, and completions for infra_tools",
    )
    bootstrap_parser.add_argument(
        "--shell",
        choices=["bash", "zsh", "fish", "tcsh"],
        default="bash",
        help="Shell to configure for completion (default: bash)",
    )
    bootstrap_parser.add_argument(
        "--user",
        dest="bootstrap_user",
        help="Local user to configure (defaults to SUDO_USER or current user)",
    )
    bootstrap_parser.add_argument(
        "--skip-system-packages",
        action="store_true",
        help="Skip apt package installation and only configure infra_tools for the target user",
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

    add_proxmox_subparser(subparsers)

    shell_parser = subparsers.add_parser(
        "shell",
        help="Start the interactive infra_tools REPL",
    )
    shell_parser.add_argument(
        "--workspace",
        help="Workspace root for saved setups, credentials, known_hosts, and history",
    )

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
                       choices=["brave", "firefox", "browsh", "helium", "lynx", "librewolf"],
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


def get_all_configs(pattern: Optional[str] = None) -> Deployments:
    cache_dir = get_setup_cache_dir()
    if not os.path.exists(cache_dir):
        return []

    configs: Deployments = []
    try:
        for filename in os.listdir(cache_dir):
            if not filename.endswith(".json"):
                continue

            filepath = os.path.join(cache_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as file_obj:
                    data = cast(JSONDict, json.load(file_obj))
                    configs.append(data)
            except Exception:
                continue
    except Exception as exc:
        print(f"Error reading configurations: {exc}")
        return []

    if pattern:
        needle = pattern.lower()
        filtered: Deployments = []
        for config in configs:
            if needle in str(config.get("host", "")).lower():
                filtered.append(config)
                continue
            if needle in str(config.get("name", "")).lower():
                filtered.append(config)
                continue
            tags = cast(StrList, config.get("tags", []))
            for tag in tags:
                if needle in tag.lower():
                    filtered.append(config)
                    break
        configs = filtered

    configs.sort(key=lambda item: item.get("host", ""))
    return configs


def reconstruct_command(config: SetupConfig) -> str:
    """Reconstruct the user-facing setup command from cached configuration."""
    return " ".join(config.to_setup_command())


def list_configurations(
    pattern: Optional[str] = None, *, json_output: bool = False
) -> int:
    from datetime import datetime

    configs = get_all_configs(pattern)
    if not configs:
        if json_output:
            print("[]")
            return 0
        if pattern:
            print(f"No configurations found matching '{pattern}'")
        else:
            print("No saved configurations found.")
        return 1

    if json_output:
        print(json.dumps(list(configs), indent=2, default=str))
        return 0

    host_width = 30
    name_width = 20
    type_width = 20
    user_width = 15
    date_width = 20
    status_width = 10
    total_width = host_width + name_width + type_width + user_width + date_width + status_width

    print(
        f"{'HOST':<{host_width}} {'NAME':<{name_width}} {'TYPE':<{type_width}} "
        f"{'USER':<{user_width}} {'LAST RUN':<{date_width}} {'STATUS':<{status_width}}"
    )
    print("-" * total_width)

    for config in configs:
        host = config.get("host", "Unknown")
        name = config.get("name", "")
        system_type = config.get("system_type", "Unknown")
        args = cast(JSONDict, config.get("args", {}))
        username = args.get("username", "Unknown")

        last_start_time = config.get("last_start_time")
        last_end_time = config.get("last_end_time")
        last_success = config.get("last_success")

        if last_start_time and last_end_time:
            start_dt = datetime.fromtimestamp(last_start_time)
            end_dt = datetime.fromtimestamp(last_end_time)
            duration = end_dt - start_dt
            last_run_str = f"{start_dt.strftime('%m/%d %H:%M')} ({duration.total_seconds():.0f}s)"
        elif last_start_time:
            start_dt = datetime.fromtimestamp(last_start_time)
            last_run_str = f"{start_dt.strftime('%m/%d %H:%M')} (running)"
        else:
            last_run_str = "Never"

        if last_success is True:
            status_str = "PASS"
        elif last_success is False:
            status_str = "FAIL"
        else:
            status_str = "UNKNOWN"

        print(
            f"{host:<{host_width}} {name:<{name_width}} {system_type:<{type_width}} "
            f"{username:<{user_width}} {last_run_str:<{date_width}} {status_str:<{status_width}}"
        )

    return 0


def show_info(pattern: Optional[str] = None, *, compact: bool = False) -> int:
    from datetime import datetime

    configs = get_all_configs(pattern)
    if not configs:
        if pattern:
            print(f"No configurations found matching '{pattern}'")
        else:
            print("No saved configurations found.")
        return 1

    for config in configs:
        host = config.get("host", "Unknown")
        name = config.get("name")
        tags = cast(StrList, config.get("tags", []))
        system_type = config.get("system_type", "Unknown")
        args = cast(JSONDict, config.get("args", {}))
        username = args.get("username", "Unknown")

        if compact:
            label = f"{host}"
            if name:
                label += f"/{name}"
            status = "PASS" if config.get("last_success") is True else (
                "FAIL" if config.get("last_success") is False else "UNKNOWN"
            )
            print(f"{label}  {system_type}  {username}  {status}")
            continue

        print("=" * 60)
        print(f"Host: {host}")
        if name:
            print(f"Name: {name}")
        if tags:
            print(f"Tags: {', '.join(tags)}")
        print(f"Type: {system_type}")
        print(f"User: {username}")
        print("-" * 60)

        deploy_specs = cast(JSONList, args.get("deploy_specs", []))
        if deploy_specs:
            print("Deployments:")
            for spec in deploy_specs:
                if isinstance(spec, list):
                    try:
                        print(f"  - {spec[1]} -> {spec[0]}")
                    except Exception:
                        print(f"  - {spec}")
                else:
                    print(f"  - {spec}")
        else:
            print("Deployments: None")

        features: StrList = []
        if args.get("enable_ssl"):
            features.append("SSL")
        if args.get("enable_cloudflare"):
            features.append("Cloudflare")
        if args.get("install_ruby"):
            features.append("Ruby")
        if args.get("install_node"):
            features.append("Node")
        if args.get("install_go"):
            features.append("Go")
        if args.get("install_python"):
            features.append("Python")
        if args.get("install_office"):
            features.append("Office")
        if args.get("use_flatpak"):
            features.append("Flatpak")
        if args.get("enable_samba"):
            features.append("Samba")

        if features:
            print(f"Features: {', '.join(features)}")

        samba_shares = cast(JSONList, args.get("samba_shares", []))
        if samba_shares:
            print("Samba Shares:")
            for share in samba_shares:
                if isinstance(share, list):
                    try:
                        share_list = cast(JSONList, share)
                        print(f"  - {share_list[1]}_{share_list[0]}: {share_list[2]}")
                    except Exception:
                        continue

        last_start_time = config.get("last_start_time")
        last_end_time = config.get("last_end_time")
        last_success = config.get("last_success")

        if last_start_time:
            start_dt = datetime.fromtimestamp(last_start_time)
            print(f"Last Run: {start_dt.strftime('%Y-%m-%d %H:%M:%S')}")
            if last_end_time:
                end_dt = datetime.fromtimestamp(last_end_time)
                duration = end_dt - start_dt
                print(f"Duration: {duration.total_seconds():.1f}s")
                print(f"Status: {'PASS' if last_success else 'FAIL'}")
            else:
                print("Status: In Progress")
        else:
            print("Last Run: Never")

        print()

    return 0


def show_command(pattern: Optional[str] = None) -> int:
    configs = get_all_configs(pattern)
    if not configs:
        if pattern:
            print(f"No configurations found matching '{pattern}'")
        else:
            print("No saved configurations found.")
        return 1

    for config_data in configs:
        host = config_data.get("host", "Unknown")
        system_type = config_data.get("system_type", "Unknown")
        args_dict = cast(JSONDict, config_data.get("args", {}))

        print("=" * 60)
        print(f"Host: {host}")
        print(f"System Type: {system_type}")
        print("-" * 60)

        try:
            config = SetupConfig.from_dict(str(host), str(system_type), args_dict)
            print(reconstruct_command(config))
        except Exception as exc:
            print(f"Error reconstructing command: {exc}")
        print()

    return 0


def remove_configurations(pattern: str, force: bool) -> int:
    configs = get_all_configs(pattern)
    if not configs:
        print(f"No configurations found matching '{pattern}'")
        return 1

    print(f"Found {len(configs)} configuration(s) to remove:")
    for config in configs:
        print(f"  - {config.get('host')}")

    if not force:
        response = input("\nAre you sure you want to remove these configurations? [y/N] ")
        if response.lower() != "y":
            print("Aborted.")
            return 0

    count = 0
    for config in configs:
        host = config.get("host")
        if not host:
            continue
        cache_path = get_cache_path_for_host(str(host))
        try:
            if os.path.exists(cache_path):
                os.remove(cache_path)
                print(f"Removed {host}")
                count += 1
        except Exception as exc:
            print(f"Error removing {host}: {exc}")

    print(f"\nRemoved {count} configuration(s).")
    return 0


def _execute_patch_config(config: SetupConfig) -> int:
    if not validate_username(config.username):
        print(f"Error: Invalid username: {config.username}")
        return 1

    if not os.path.exists(REMOTE_SCRIPT_PATH):
        print(f"Error: Remote setup script not found: {REMOTE_SCRIPT_PATH}")
        return 1

    print("=" * 60)
    print(f"Patching System: {config.system_type}")
    print("=" * 60)
    print(f"Host: {config.host}")
    print(f"User: {config.username}")
    print(f"Timezone: {config.timezone}")
    print("=" * 60)
    print()

    try:
        runtime_config = prepare_runtime_config(config)
        validate_timezone_name(runtime_config.timezone)
        validate_apt_packages(runtime_config.apt_packages)
        validate_notification_args(runtime_config.notify_specs)
        validate_ssl_email(runtime_config.ssl_email)
        validate_deploy_specs(runtime_config.deploy_specs)
        validate_deploy_targets(runtime_config.deploy_targets)
        validate_sync_specs(runtime_config.sync_specs)
        validate_scrub_specs(runtime_config.scrub_specs)
        validate_smb_mount_specs(runtime_config.smb_mounts)
        validate_samba_share_specs(runtime_config.samba_shares, runtime_config.share_credentials)
        validate_hosted_flags(runtime_config)
        validate_samba_share_credentials(runtime_config)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    start_time = time.time()
    returncode = 1
    try:
        if not config.dry_run:
            store_cli_credentials(config)
        returncode = run_remote_setup(runtime_config)
    finally:
        end_time = time.time()
        success = returncode == 0
        if not config.dry_run:
            save_setup_command(config, start_time, end_time, success, operation="patch")

    if returncode != 0:
        print(f"\n✗ Patch failed (exit code: {returncode})")
        return 1

    print()
    print("=" * 60)
    print("Patch Complete!")
    print("=" * 60)
    print(f"Host: {config.host}")
    print("System has been updated with new configuration")

    if config.friendly_name or config.tags:
        print()
        print_name_and_tags(config)

    print("=" * 60)
    return 0


def deploy_configurations(pattern: str, force: bool) -> int:
    configs = get_all_configs(pattern)
    if not configs:
        print(f"No configurations found matching '{pattern}'")
        return 1

    print(f"Found {len(configs)} configuration(s) to deploy:")
    for config in configs:
        host = config.get("host")
        deploy_specs = cast(JSONList, cast(JSONDict, config.get("args", {})).get("deploy_specs", []))
        print(f"  - {host} ({len(deploy_specs)} deployments)")

    if not force:
        response = input("\nAre you sure you want to deploy to these hosts? [y/N] ")
        if response.lower() != "y":
            print("Aborted.")
            return 0

    failures = 0
    for config_data in configs:
        host = config_data.get("host")
        system_type = config_data.get("system_type")
        args_dict = config_data.get("args", {})

        print(f"\nDeploying to {host}...")
        try:
            if not isinstance(host, str) or not isinstance(system_type, str) or not isinstance(args_dict, dict):
                raise ValueError("Invalid cached configuration format")
            config = SetupConfig.from_dict(host, system_type, cast(JSONDict, args_dict))
            if _execute_patch_config(config) != 0:
                failures += 1
        except Exception as exc:
            print(f"Error creating config for {host}: {exc}")
            failures += 1

    if failures > 0:
        print(f"\nCompleted with {failures} failure(s).")
        return 1

    print("\nAll deployments completed successfully.")
    return 0


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
        validate_timezone_name(runtime_config.timezone)
        validate_apt_packages(runtime_config.apt_packages)
        validate_notification_args(runtime_config.notify_specs)
        validate_ssl_email(runtime_config.ssl_email)
        validate_deploy_specs(runtime_config.deploy_specs)
        validate_deploy_targets(runtime_config.deploy_targets)
        validate_sync_specs(runtime_config.sync_specs)
        validate_scrub_specs(runtime_config.scrub_specs)
        validate_smb_mount_specs(runtime_config.smb_mounts)
        validate_samba_share_specs(runtime_config.samba_shares, runtime_config.share_credentials)
        validate_hosted_flags(runtime_config)
        validate_samba_share_credentials(runtime_config)
    except ValueError as e:
        print(f"Error: {e}")
        return 1
    
    description = f"{args.system_type.replace('_', ' ').title()} Setup"
    print_setup_summary(config, description)
    
    if not config.dry_run:
        store_cli_credentials(config)
        save_setup_command(config, operation="setup")
    
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
            save_setup_command(config, start_time, end_time, success, operation="setup")
    
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
    return _execute_patch_config(merged_config)


def main() -> int:
    """Main entry point for infra_tools."""
    parser, setup_parser, patch_parser = create_infra_tools_parser()
    
    # Add common arguments to both subparsers
    add_common_arguments(setup_parser, for_patch=False)
    add_common_arguments(patch_parser, for_patch=True)

    if argcomplete:
        argcomplete.autocomplete(parser)

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
    elif args.command in {"list", "ls"}:
        return list_configurations(args.pattern, json_output=getattr(args, "json", False))
    elif args.command == "info":
        return show_info(args.pattern, compact=getattr(args, "compact", False))
    elif args.command in {"cmd", "command"}:
        return show_command(args.pattern)
    elif args.command in {"rm", "remove"}:
        return remove_configurations(args.pattern, args.yes)
    elif args.command == "deploy":
        return deploy_configurations(args.pattern, args.yes)
    elif args.command == "reconstruct":
        return run_reconstruct_command(args.compact)
    elif args.command == "recall":
        username = args.username if args.username else get_current_username()
        if not validate_host(args.host):
            print(f"Error: Invalid IP address or hostname: {args.host}")
            return 1
        if not validate_username(username):
            print(f"Error: Invalid username: {username}")
            return 1
        return run_recall_command(args.host, username, args.ssh_key)
    elif args.command == "completions":
        return run_completion_setup(
            shell=args.shell,
            global_install=args.global_install,
            command_name=_current_command_name(),
        )
    elif args.command in {"python-tools", "admin-python"}:
        return run_local_python_setup(
            args.shell,
            command_name=_current_command_name(),
            script_path=getattr(args, "script_path", None) or sys.argv[0],
        )
    elif args.command in {"bootstrap", "self-setup"}:
        return run_orchestrator_bootstrap(
            script_path=sys.argv[0],
            shell=args.shell,
            requested_user=args.bootstrap_user,
            skip_system_packages=args.skip_system_packages,
        )
    elif args.command == "proxmox":
        return run_proxmox_command(args)
    elif args.command == "shell":
        return run_interactive_shell(getattr(args, "workspace", None))
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
