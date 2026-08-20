#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
"""
infra_tools - Unified entry point for infrastructure setup and management.

This script provides a unified interface to all infra_tools functionality,
combining setup and patch operations into a single command-line tool.

Usage:
    infra-tools setup <system_type> <host> [options]
    infra-tools patch <host> [options]
    infra-tools --help

System Types:
    control_plane         Infrastructure control plane setup
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
import getpass
import ipaddress
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

from lib.arg_parser import add_setup_arguments
from lib.agent_cli import add_agent_subparser, run_agent_command
from lib.cache import get_cache_path_for_host, load_setup_command, merge_setup_configs, save_setup_command
from lib.channel_manager import (
    ChannelError,
    get_channel_info,
    managed_repository_path,
    switch_channel,
    upgrade_channel,
)
from lib.completions import run_completion_setup
from lib.config import SetupConfig
from lib.credentials import (
    list_workspace_credentials,
    prepare_runtime_config,
    remove_workspace_credential,
    set_workspace_credential,
    store_cli_credentials,
)
from lib.github_maintenance import add_maintenance_subparser, run_maintenance_command
from lib.display import print_name_and_tags, print_setup_summary, print_success_header
from lib.interactive_shell import run_interactive_shell
from lib.notifications import validate_notification_args
from lib.orchestrator_bootstrap import LAUNCHER_NAME, run_orchestrator_bootstrap
from lib.plugin_registry import format_system_type_help, get_system_type_names
from lib.network_cli import add_network_subparser, run_network_command
from lib.local_cli import add_local_subparser, run_local_command
from lib.proxmox_cli import add_proxmox_subparser, run_proxmox_command
from lib.sysadmin_cli import add_sysadmin_subparsers, run_sysadmin_command
from lib.python_setup import run_local_python_setup
from lib.recall import run_recall_command
from lib.reconstruct import run_reconstruct_command
from lib.remote_utils import confirm_unsupported_environment
from lib.setup_common import (
    REMOTE_SCRIPT_PATH,
    _apply_hosted_proxmox_defaults,
    adopt_verified_network_host,
    register_proxmox_setup_host,
    remove_replaced_setup_cache,
    run_remote_setup,
)
from lib.system_utils import get_current_username
from lib.types import Deployments, JSONDict, JSONList, StrList
from lib.validators import validate_host, validate_username
from lib.validation import (
    validate_apt_packages,
    validate_agent_repositories,
    validate_antistatic_settings,
    validate_deploy_specs,
    validate_deploy_targets,
    validate_gogs_settings,
    validate_hosted_flags,
    validate_network_setup_settings,
    validate_rdp_settings,
    validate_samba_share_credentials,
    validate_samba_share_name,
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
    shares <host> [args]         Reconcile Samba shares without full setup
    list [pattern]              List saved configurations
    info [pattern]              Show saved configuration details
    cmd [pattern]               Show reconstructed setup commands
    rm <pattern>                Remove saved configurations
    deploy <pattern>            Redeploy saved configurations
    recall <host> [username]    Fetch or reconstruct a remote setup command
    reconstruct                 Analyze this host and emit a setup summary
    completions                 Install shell completion for infra-tools
    python-tools                Install local Python aliases, uv, and completion
    bootstrap                   Install packages, launcher, and completions (alias: self-setup)
    channel [CHANNEL]           Show or switch the installed source channel
    upgrade                     Upgrade the installed source on its selected channel
    agent doctor|update|auth   Check, update, or rotate agent credentials
    maintenance github ...      Audit/prune GitHub releases, artifacts, and caches
    network [subcommand]        Manage generic network inventory profiles
    local [subcommand]          Maintain this local Debian system
    proxmox [subcommand]        Manage Proxmox hosts and containers (interactive shell with no args)
    shell                       Interactive REPL for managing saved configurations
    credentials                 Manage workspace credentials

Sysadmin Shortcuts:
    mount <host:path> <local>   Mount a remote directory via sshfs
    umount <local|host>         Unmount an sshfs mount
    health <host>               Show uptime, disk, memory, failed units, pending upgrades
    ssh <host> [-- cmd]         Open SSH session using saved config
    push <local> <host:path>    Rsync a local path to a remote host
    pull <host:path> [local]    Rsync a remote path to local
    key push <host>             Install local public key on a remote host
    df <host> [<host2> ...]     Multi-host disk usage table (>85% highlighted)
    fan <host> [..] -- <cmd>    Run a command on multiple hosts in parallel
    svc <host> <unit> [action]  Manage a systemd service (status/restart/start/stop/…)
    logs <host> <unit>          Show or follow journalctl output for a service
    upgrade <host> [<host2>…]   Run apt upgrade in parallel; report reboot-required
    reachable [hosts|pattern]   Check which saved hosts are reachable via SSH
    ssh-key enroll <host>       Enroll and verify a workspace SSH host key

System Types for setup:
{format_system_type_help()}

Examples:
  infra-tools setup server_web 192.168.1.100 admin --ssl
  infra-tools patch 192.168.1.100 --deploy api.example.com https://github.com/user/api.git
  infra-tools shares 192.168.1.100 --share write media /srv/media alice,bob
  infra-tools list prod
  infra-tools deploy prod --yes
  infra-tools recall example.com admin
  infra-tools completions --shell zsh
  sudo infra-tools self-setup --user admin [--qemu-guest-agent]
  infra-tools list prod    # after self-setup, the launcher is on PATH
 """


def _current_command_name() -> str:
    return LAUNCHER_NAME


def _is_local_host(host: str) -> bool:
    """Return whether a command targets this orchestration host."""

    return host in {"localhost", "127.0.0.1", "::1"}


def _managed_repository() -> str:
    return managed_repository_path(__file__)


def run_channel_command(args: argparse.Namespace) -> int:
    """Show or switch the channel selected for the installed worktree."""

    try:
        repository = _managed_repository()
        if args.channel_name is None:
            info = get_channel_info(repository)
            if info.get("managed"):
                print(f"Channel: {info['channel']}")
            else:
                print("Channel: unmanaged checkout")
            print(f"Commit: {str(info['commit'])[:12]}")
            if info.get("branch"):
                print(f"Branch: {info['branch']}")
            return 0

        info = switch_channel(repository, args.channel_name)
        print(f"Switched to channel {info['channel']} at {str(info['commit'])[:12]}")
        return 0
    except (ChannelError, ValueError, OSError) as exc:
        print(f"Error: {exc}")
        return 1


def run_tool_upgrade_command(args: argparse.Namespace | None = None) -> int:
    """Upgrade the installed source to the latest commit on its channel."""

    del args
    try:
        info = upgrade_channel(_managed_repository())
        if info.get("updated"):
            print(f"Upgraded {info['channel']} to {str(info['commit'])[:12]}")
        else:
            print(f"infra-tools is already up to date on {info['channel']} ({str(info['commit'])[:12]})")
        return 0
    except (ChannelError, ValueError, OSError) as exc:
        print(f"Error: {exc}")
        return 1


def create_infra_tools_parser() -> Tuple[argparse.ArgumentParser, argparse.ArgumentParser, argparse.ArgumentParser]:
    """Create the main argument parser for infra_tools."""
    parser = argparse.ArgumentParser(
        prog=LAUNCHER_NAME,
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
        epilog="Run 'infra-tools setup --help' for full options"
    )
    add_setup_arguments(setup_parser, allow_steps=True, include_system_type=True)
    
    # Patch subcommand
    patch_parser = subparsers.add_parser(
        "patch",
        help="Patch/update an existing system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Run 'infra-tools patch --help' for full options"
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
    add_setup_arguments(patch_parser, allow_steps=True, include_host=False)

    shares_parser = subparsers.add_parser(
        "shares",
        help="Quickly reconcile Samba shares on an existing system",
    )
    shares_parser.add_argument("host", help="Host with a saved setup configuration")
    shares_parser.add_argument("username", nargs="?", default=None)
    shares_parser.add_argument("-k", "--key", dest="ssh_key", help="SSH private key path")
    shares_parser.add_argument(
        "--share",
        dest="samba_shares",
        action="append",
        nargs=4,
        metavar=("ACCESS_TYPE", "SHARE_NAME", "PATH", "USERS"),
        help="Add or replace a share by name; repeat as needed",
    )
    shares_parser.add_argument(
        "--remove-share",
        action="append",
        default=[],
        metavar="SHARE_NAME",
        help="Remove a managed share by name; repeat as needed",
    )
    shares_parser.add_argument(
        "--credential",
        dest="share_credentials",
        action="append",
        nargs=2,
        metavar=("USERNAME", "PASSWORD"),
        help="Save or update a share user's workspace credential",
    )
    shares_parser.add_argument("--dry-run", action="store_true")
    shares_parser.add_argument(
        "--workspace",
        help="Workspace root for saved setups, credentials, known_hosts, and history",
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
    add_deploy_command_arguments(deploy_parser, include_workspace=True)

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
        help="Install shell completion for infra-tools",
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
        help="Install local packages, launcher, and completions for infra-tools",
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
        help="Skip local system-package installation and only configure infra-tools for the target user",
    )
    bootstrap_parser.add_argument(
        "--qemu-guest-agent",
        action="store_true",
        help="Install, start, and enable Proxmox's qemu-guest-agent (requires root)",
    )

    channel_parser = subparsers.add_parser(
        "channel",
        help="Show or switch the installed source channel",
        description=(
            "Select the Git source used by the installed launcher. Channels are "
            "stable, dev, v<version>, branch-<branch>, or commit-<hash>."
        ),
    )
    channel_parser.add_argument(
        "channel_name",
        nargs="?",
        help="Channel to select; omit to show the current channel",
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
    credentials_set_parser.add_argument(
        "password",
        nargs="?",
        help="Credential password (omit to enter it without exposing it in process arguments)",
    )

    credentials_subparsers.add_parser("list", help="List saved credential usernames")

    credentials_remove_parser = credentials_subparsers.add_parser("remove", help="Remove a saved credential")
    credentials_remove_parser.add_argument("username", help="Credential username to remove")

    add_network_subparser(subparsers)
    add_local_subparser(subparsers)
    add_proxmox_subparser(subparsers)
    add_maintenance_subparser(subparsers)
    add_sysadmin_subparsers(subparsers)
    add_agent_subparser(subparsers)

    shell_parser = subparsers.add_parser(
        "shell",
        help="Start the interactive infra-tools REPL",
    )
    shell_parser.add_argument(
        "--workspace",
        help="Workspace root for saved setups, credentials, known_hosts, and history",
    )

    return parser, setup_parser, patch_parser

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
        if args.get("install_gh"):
            features.append("GitHub CLI")
        if args.get("install_codex"):
            features.append("Codex CLI")
        if args.get("install_claude"):
            features.append("Claude Code")
        if args.get("install_opencode"):
            features.append("OpenCode")
        if args.get("install_t3code"):
            features.append("T3 Code")
        if args.get("install_office"):
            features.append("Office")
        if args.get("use_flatpak"):
            features.append("Flatpak")
        if args.get("enable_samba"):
            features.append("Samba")
        if args.get("gogs"):
            features.append("Gogs")

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
        runtime_config = _prepare_runtime_config_for_cli(config)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    previous_host = config.host
    replaced_cache_host: Optional[str] = None
    start_time = time.time()
    returncode = 1
    try:
        if not config.dry_run:
            store_cli_credentials(config)
        returncode = run_remote_setup(runtime_config)
        if returncode == 0:
            replaced_cache_host = adopt_verified_network_host(
                config,
                runtime_config,
                previous_host,
            )
    finally:
        end_time = time.time()
        success = returncode == 0
        if not config.dry_run:
            save_setup_command(config, start_time, end_time, success, operation="patch")

    if replaced_cache_host:
        remove_replaced_setup_cache(replaced_cache_host, config.host)

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


def _patch_preserve_keys(args: argparse.Namespace) -> set[str]:
    preserve_keys: set[str] = set()
    if getattr(args, "machine_type", None) is None:
        preserve_keys.add("machine_type")
    if getattr(args, "hosted_node", None) is None:
        preserve_keys.update(
            {
                "hosted_node",
                "hosted_user",
                "hosted_key",
                "hosted_bridge",
                "container_memory",
                "vm_balloon_min",
                "container_storage",
                "storage_mounts",
                "container_cores",
                "container_base",
                "vm_image",
            }
        )
    return preserve_keys


_PROVISIONING_CHANGE_ARGS = (
    "machine_type",
    "hosted_bridge",
    "container_memory",
    "vm_balloon_min",
    "container_storage",
    "storage_mounts",
    "container_cores",
    "container_base",
    "vm_image",
    "vm_image_storage",
)

_CACHED_PROVISIONING_FIELDS = (
    "machine_type",
    "hosted_node",
    "hosted_user",
    "hosted_key",
    "hosted_bridge",
    "container_memory",
    "vm_balloon_min",
    "container_storage",
    "storage_mounts",
    "container_cores",
    "container_base",
    "vm_image",
    "vm_image_storage",
)


def _provisioning_changes_requested(
    config: SetupConfig,
    cached_config: SetupConfig,
    args: argparse.Namespace,
) -> bool:
    """Return whether explicit guest-shape arguments differ from local state."""
    return any(
        getattr(args, field, None) is not None
        and getattr(config, field) != getattr(cached_config, field)
        for field in _PROVISIONING_CHANGE_ARGS
    )


def _reuse_cached_provisioning_metadata(
    config: SetupConfig,
    args: argparse.Namespace,
) -> bool:
    """Hydrate an existing guest from local state and skip Proxmox discovery."""
    if not config.hosted_node:
        return False

    cache_target = config.host
    if "/" in cache_target:
        try:
            target_interface = ipaddress.ip_interface(cache_target)
        except ValueError:
            pass
        else:
            cache_target = str(target_interface.ip)

    cached_config = load_setup_command(cache_target)
    if cached_config is None or not cached_config.hosted_node:
        return False
    if _provisioning_changes_requested(config, cached_config, args):
        return False

    for field in _CACHED_PROVISIONING_FIELDS:
        setattr(config, field, getattr(cached_config, field))

    if config.ssh_key is None:
        config.ssh_key = cached_config.ssh_key
    if getattr(args, "static_ipv4", None) is None and cached_config.static_ipv4:
        config.static_ipv4 = cached_config.static_ipv4

    return True


def _prepare_runtime_config_for_cli(config: SetupConfig) -> SetupConfig:
    _apply_hosted_proxmox_defaults(config, None)
    runtime_config = prepare_runtime_config(config)
    validate_timezone_name(runtime_config.timezone)
    validate_apt_packages(runtime_config.apt_packages)
    validate_agent_repositories(runtime_config.agent_repos)
    validate_notification_args(runtime_config.notify_specs)
    validate_ssl_email(runtime_config.ssl_email)
    validate_deploy_specs(runtime_config.deploy_specs)
    validate_deploy_targets(runtime_config.deploy_targets)
    validate_sync_specs(runtime_config.sync_specs)
    validate_scrub_specs(runtime_config.scrub_specs)
    validate_smb_mount_specs(runtime_config.smb_mounts)
    validate_samba_share_specs(
        runtime_config.samba_shares,
        runtime_config.share_credentials,
    )
    validate_gogs_settings(runtime_config)
    validate_antistatic_settings(runtime_config)
    validate_hosted_flags(runtime_config)
    validate_network_setup_settings(runtime_config)
    validate_rdp_settings(runtime_config)
    validate_samba_share_credentials(runtime_config)
    return runtime_config


def add_deploy_command_arguments(
    parser: argparse.ArgumentParser,
    *,
    include_workspace: bool = False,
) -> None:
    parser.add_argument("pattern", help="Host, name, or tag filter to redeploy")
    parser.add_argument("-y", "--yes", action="store_true", help="Deploy without prompting")
    parser.add_argument(
        "--deploy-latest",
        dest="deploy_latest",
        action="store_true",
        help="Deploy the latest versions of packages and releases, bypassing the release age policy",
    )
    if include_workspace:
        parser.add_argument(
            "--workspace",
            help="Workspace root for saved setups, credentials, known_hosts, and history"
        )


class DeployArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        usage = self.format_usage().strip()
        if usage.startswith("usage:"):
            usage = "Usage:" + usage[len("usage:"):]
        raise ValueError(f"{usage}\n{message}")


def parse_deploy_command_args(args: list[str]) -> argparse.Namespace:
    parser = DeployArgumentParser(prog="deploy", add_help=False)
    add_deploy_command_arguments(parser)
    return parser.parse_args(args)


def run_deploy_command(args: argparse.Namespace) -> int:
    return deploy_configurations(
        args.pattern,
        args.yes,
        getattr(args, "deploy_latest", False),
    )


def deploy_configurations(pattern: str, force: bool, deploy_latest: bool = False) -> int:
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
            config.deploy_latest = deploy_latest
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
    explicit_ipv4 = getattr(args, "static_ipv4", None)
    if getattr(args, "hosted_node", None) and isinstance(explicit_ipv4, str) and explicit_ipv4:
        print(
            "Error: --ip is redundant with --provision-on; put the guest address "
            "and optional prefix in the positional HOST[/PREFIX] target"
        )
        return 1

    config = SetupConfig.from_args(args, args.system_type)

    reuse_cached_provisioning = _reuse_cached_provisioning_metadata(config, args)

    if not validate_username(config.username):
        print(f"Error: Invalid username: {config.username}")
        return 1

    if config.hosted_node and config.activate_network is True:
        print(
            "Error: --activate-network is for patching an already saved Proxmox "
            "guest; provisioned guests boot directly on their requested address"
        )
        return 1
    
    try:
        runtime_config = _prepare_runtime_config_for_cli(config)
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    if not validate_host(config.host):
        print(f"Error: Invalid IP address or hostname: {config.host}")
        return 1
    
    description = f"{args.system_type.replace('_', ' ').title()} Setup"
    print_setup_summary(config, description)

    if config.hosted_node and reuse_cached_provisioning:
        print("  ✓ Guest already provisioned in local metadata; skipping Proxmox host check")
    elif config.hosted_node:
        if config.machine_type == "vm":
            from lib.proxmox_vm import provision_vm, VMAlreadyExists

            print(f"\n{'='*60}")
            print(f"Provisioning VM on {config.hosted_node}...")
            print(f"{'='*60}")
            try:
                provision_vm(config, image=config.vm_image)
            except VMAlreadyExists:
                if config.storage_mounts:
                    print(
                        "Error: named VM data disks are provisioning-only; "
                        "refusing to adopt disks on an existing unsaved VM"
                    )
                    return 1
                print("  ✓ VM already provisioned, skipping creation")
            except Exception as e:
                print(f"\n✗ Failed to provision VM: {e}")
                return 1
        else:
            from lib.proxmox_node import provision_container, ContainerAlreadyExists

            print(f"\n{'='*60}")
            print(f"Provisioning LXC container on {config.hosted_node}...")
            print(f"{'='*60}")
            try:
                provision_container(config)
            except ContainerAlreadyExists:
                print("  ✓ Container already provisioned, skipping creation")
            except Exception as e:
                print(f"\n✗ Failed to provision container: {e}")
                return 1

        try:
            runtime_config = _prepare_runtime_config_for_cli(config)
        except ValueError as e:
            print(f"Error: {e}")
            return 1

    if not config.dry_run:
        store_cli_credentials(config)
        save_setup_command(config, operation="setup")

    if not os.path.exists(REMOTE_SCRIPT_PATH):
        print(f"Error: Remote setup script not found: {REMOTE_SCRIPT_PATH}")
        return 1
    
    previous_host = config.host
    replaced_cache_host: Optional[str] = None
    start_time = time.time()
    returncode = 1
    try:
        returncode = run_remote_setup(runtime_config)
        if returncode == 0:
            replaced_cache_host = adopt_verified_network_host(
                config,
                runtime_config,
                previous_host,
            )
    finally:
        end_time = time.time()
        success = (returncode == 0)
        if not config.dry_run:
            save_setup_command(config, start_time, end_time, success, operation="setup")

    if replaced_cache_host:
        remove_replaced_setup_cache(replaced_cache_host, config.host)
    
    if returncode != 0:
        print(f"\n✗ Setup failed (exit code: {returncode})")
        return 1

    try:
        register_proxmox_setup_host(config)
    except ValueError as exc:
        print(f"\n✗ Setup completed, but Proxmox host registration failed: {exc}")
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
        print(f"Please run the initial setup first using 'infra-tools setup <system_type> {args.host}'")
        return 1
    
    new_config = SetupConfig.from_args(args, cached_config.system_type)
    merged_config = merge_setup_configs(
        cached_config,
        new_config,
        preserve_keys=_patch_preserve_keys(args),
    )
    return _execute_patch_config(merged_config)


def _apply_share_updates(config: SetupConfig, args: argparse.Namespace) -> None:
    """Apply share CLI mutations to a cached configuration in place."""

    remove_names = set(args.remove_share)
    for share_name in remove_names:
        validate_samba_share_name(share_name)

    updated_by_name = {
        share_spec[1]: list(share_spec)
        for share_spec in config.samba_shares or []
        if share_spec[1] not in remove_names
    }
    for share_spec in args.samba_shares or []:
        updated_by_name[share_spec[1]] = list(share_spec)

    config.samba_shares = list(updated_by_name.values()) or None
    config.enable_samba = True
    config.share_credentials = args.share_credentials
    config.dry_run = args.dry_run
    if args.username:
        config.username = args.username
    if args.ssh_key:
        config.ssh_key = args.ssh_key


def run_shares_command(args: argparse.Namespace) -> int:
    """Reconcile only Samba shares without running the full setup lifecycle."""

    cached_config = load_setup_command(args.host)
    if not cached_config:
        print(f"Error: No cached setup found for {args.host}")
        return 1

    try:
        _apply_share_updates(cached_config, args)
        if not validate_username(cached_config.username):
            raise ValueError(f"Invalid username: {cached_config.username}")
        share_config = SetupConfig(
            host=cached_config.host,
            username=cached_config.username,
            system_type=cached_config.system_type,
            machine_type=cached_config.machine_type,
            ssh_key=cached_config.ssh_key,
            dry_run=cached_config.dry_run,
            enable_samba=True,
            samba_shares=cached_config.samba_shares,
            share_credentials=cached_config.share_credentials,
            scrub_specs=cached_config.scrub_specs,
        )
        runtime_config = prepare_runtime_config(share_config)
        validate_samba_share_specs(
            runtime_config.samba_shares,
            runtime_config.share_credentials,
        )
        validate_scrub_specs(runtime_config.scrub_specs)
        validate_samba_share_credentials(runtime_config)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    runtime_config.custom_steps = "reconcile_samba_shares"
    start_time = time.time()
    if not cached_config.dry_run:
        store_cli_credentials(cached_config)
    returncode = run_remote_setup(runtime_config)
    end_time = time.time()

    if not cached_config.dry_run:
        save_setup_command(
            cached_config,
            start_time,
            end_time,
            returncode == 0,
            operation="shares",
        )
    if returncode != 0:
        print(f"\n✗ Samba share update failed (exit code: {returncode})")
        return 1

    print(f"\n✓ Samba shares updated on {cached_config.host}")
    return 0


def main() -> int:
    """Main entry point for infra-tools."""
    parser, _setup_parser, _patch_parser = create_infra_tools_parser()

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
    
    if args.command in {"setup", "patch", "shares"} and _is_local_host(args.host):
        if not confirm_unsupported_environment(f"{args.command} on the local host"):
            return 1

    if args.command == "setup":
        return run_setup_command(args)
    elif args.command == "patch":
        return run_patch_command(args)
    elif args.command == "shares":
        return run_shares_command(args)
    elif args.command in {"list", "ls"}:
        return list_configurations(args.pattern, json_output=getattr(args, "json", False))
    elif args.command == "info":
        return show_info(args.pattern, compact=getattr(args, "compact", False))
    elif args.command in {"cmd", "command"}:
        return show_command(args.pattern)
    elif args.command in {"rm", "remove"}:
        return remove_configurations(args.pattern, args.yes)
    elif args.command == "deploy":
        return run_deploy_command(args)
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
        if not args.skip_system_packages and not confirm_unsupported_environment("local bootstrap"):
            return 1
        return run_orchestrator_bootstrap(
            script_path=sys.argv[0],
            shell=args.shell,
            requested_user=args.bootstrap_user,
            skip_system_packages=args.skip_system_packages,
            install_qemu_guest_agent=args.qemu_guest_agent,
        )
    elif args.command == "channel":
        return run_channel_command(args)
    elif args.command == "upgrade" and not getattr(args, "hosts", None):
        if getattr(args, "check", False):
            print("Error: --check requires at least one remote host")
            return 1
        return run_tool_upgrade_command(args)
    elif args.command == "network":
        return run_network_command(args)
    elif args.command == "local":
        if not confirm_unsupported_environment("local maintenance"):
            return 1
        return run_local_command(args)
    elif args.command == "proxmox":
        return run_proxmox_command(args)
    elif args.command == "maintenance":
        return run_maintenance_command(args)
    elif args.command == "agent":
        return run_agent_command(args)
    elif args.command in {"mount", "umount", "health", "ssh", "push", "pull", "key", "ssh-key", "df", "fan", "svc", "logs", "upgrade", "reachable"}:
        return run_sysadmin_command(args)
    elif args.command == "shell":
        return run_interactive_shell(getattr(args, "workspace", None))
    elif args.command == "credentials":
        try:
            if args.credentials_command == "set":
                password = args.password
                if password is None:
                    password = getpass.getpass(f"Password for {args.username}: ")
                set_workspace_credential(args.username, password)
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
