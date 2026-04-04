#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import os
import json
import time
import shlex

try:
    import argcomplete
except ImportError:
    argcomplete = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from typing import Optional, cast
from lib.types import Deployments, JSONDict, StrList, JSONList
from lib.config import SetupConfig, redact_share_user_passwords, redact_mount_credentials
from lib.validators import validate_host, validate_username
from lib.display import print_name_and_tags
from lib.cache import (
    load_setup_command,
    merge_setup_configs,
    save_setup_command,
    get_cache_path_for_host,
)
from lib.credentials import prepare_runtime_config, store_cli_credentials
from lib.setup_common import (
    create_argument_parser,
    run_remote_setup,
    REMOTE_SCRIPT_PATH
)
from lib.workspace import get_setup_cache_dir, set_workspace_dir

PATCH_SPECIAL_COMMANDS_HELP = """Special commands:
  patch_setup.py list [pattern]   List saved configurations
  patch_setup.py info [pattern]    Show configuration details
  patch_setup.py cmd [pattern]     Show reconstructed command
  patch_setup.py rm [pattern]      Remove saved configurations
  patch_setup.py deploy [pattern]  Redeploy matching configurations
"""

SYSTEM_TYPE_TO_SCRIPT = {
    "server_web": "setup_server_web.py",
    "server_dev": "setup_server_dev.py",
    "server_lite": "setup_server_lite.py",
    "workstation_desktop": "setup_workstation_desktop.py",
    "workstation_dev": "setup_workstation_dev.py",
    "pc_dev": "setup_pc_dev.py",
    "server_proxmox": "setup_server_proxmox.py",
    "admin_python": "setup_admin_python.py",
}


def get_all_configs(pattern: Optional[str] = None) -> Deployments:
    cache_dir = get_setup_cache_dir()
    if not os.path.exists(cache_dir):
        return []

    configs: Deployments = []
    try:
        for filename in os.listdir(cache_dir):
            if not filename.endswith('.json'):
                continue
                
            filepath = os.path.join(cache_dir, filename)
            try:
                with open(filepath, 'r') as f:
                    data = cast(JSONDict, json.load(f))
                    # Leave complex normalization to consumers; keep data as JSONDict
                    configs.append(data)
            except Exception:
                continue
    except Exception as e:
        print(f"Error reading configurations: {e}")
        return []

    if pattern:
        pattern = pattern.lower()
        filtered: Deployments = []
        for c in configs:
            if pattern in str(c.get('host', '')).lower():
                filtered.append(c)
                continue
            if pattern in str(c.get('name', '')).lower():
                filtered.append(c)
                continue
            tags: StrList = cast(StrList, c.get('tags', []))
            for tag in tags:
                # tags were normalized when loading, so tag is a str
                if pattern in tag.lower():
                    filtered.append(c)
                    break
        configs = filtered
    
    configs.sort(key=lambda x: x.get('host', ''))
    
    return configs


def reconstruct_command(config: SetupConfig) -> str:
    """Reconstruct the original command from cached configuration."""
    script_name = SYSTEM_TYPE_TO_SCRIPT.get(config.system_type, f"setup_{config.system_type}.py")
    
    cmd_parts = [f"./{script_name}", config.host]
    
    if config.username:
        cmd_parts.append(f"--username {shlex.quote(config.username)}")
    
    if config.machine_type:
        cmd_parts.append(f"--machine {shlex.quote(config.machine_type)}")
    
    if config.timezone and config.timezone != "UTC":
        cmd_parts.append(f"--timezone {shlex.quote(config.timezone)}")
    
    if config.friendly_name:
        cmd_parts.append(f"--name {shlex.quote(config.friendly_name)}")
    
    if config.enable_rdp:
        cmd_parts.append("--rdp")
    
    if config.desktop:
        cmd_parts.append(f"--desktop {shlex.quote(config.desktop)}")
    
    if config.browsers:
        for browser in config.browsers:
            cmd_parts.append(f"--browser {shlex.quote(browser)}")
    elif config.browser:
        cmd_parts.append(f"--browser {shlex.quote(config.browser)}")
    
    if config.use_flatpak:
        cmd_parts.append("--flatpak")
    
    if config.install_office:
        cmd_parts.append("--office")
    
    if config.apt_packages:
        for pkg in config.apt_packages:
            cmd_parts.append(f"--apt-install {shlex.quote(pkg)}")
    
    if config.flatpak_packages:
        for pkg in config.flatpak_packages:
            cmd_parts.append(f"--flatpak-install {shlex.quote(pkg)}")
    
    if config.dark_theme:
        cmd_parts.append("--dark")
    
    if config.dry_run:
        cmd_parts.append("--dry-run")
    
    if config.install_ruby:
        cmd_parts.append("--ruby")
    
    if config.install_go:
        cmd_parts.append("--go")
    
    if config.install_node:
        cmd_parts.append("--node")
    
    if config.install_python:
        cmd_parts.append("--python")
    
    if config.custom_steps:
        cmd_parts.append(f"--steps {shlex.quote(config.custom_steps)}")
    
    if config.deploy_specs:
        cmd_parts.append("--lite-deploy")
        if config.full_deploy:
            cmd_parts.append("--full-deploy")
        for deploy_spec, git_url in config.deploy_specs:
            cmd_parts.append(f"--deploy {shlex.quote(deploy_spec)} {shlex.quote(git_url)}")
    
    if config.reset_migrations:
        cmd_parts.append("--reset-migrations")
    
    if config.enable_ssl:
        cmd_parts.append("--ssl")
        if config.ssl_email:
            cmd_parts.append(f"--ssl-email {shlex.quote(config.ssl_email)}")
    
    if config.enable_cloudflare:
        cmd_parts.append("--cloudflare")
    
    if config.enable_cicd:
        cmd_parts.append("--cicd")
    
    if config.is_build_server:
        cmd_parts.append("--build-server")
    
    if config.is_app_server:
        cmd_parts.append("--app-server")
    
    if config.deploy_targets:
        for target in config.deploy_targets:
            cmd_parts.append(f"--deploy-target {shlex.quote(target)}")
    
    if config.api_subdomain:
        cmd_parts.append("--api-subdomain")
    
    if config.enable_samba:
        cmd_parts.append("--samba")
    
    if config.samba_shares:
        for share_spec in config.samba_shares:
            redacted_share_spec = list(share_spec)
            if len(redacted_share_spec) >= 4:
                redacted_users: list[str] = []
                for user_spec in str(redacted_share_spec[3]).split(','):
                    normalized_user = user_spec.strip()
                    if not normalized_user:
                        continue
                    if ':' in normalized_user:
                        redacted_users.append(redact_share_user_passwords(normalized_user))
                    else:
                        redacted_users.append(normalized_user)
                redacted_share_spec[3] = ','.join(redacted_users)
            escaped_spec = ' '.join(shlex.quote(str(s)) for s in redacted_share_spec)
            cmd_parts.append(f"--share {escaped_spec}")
    
    required_usernames: list[str] = []
    seen_usernames: set[str] = set()
    if config.samba_shares:
        for share_spec in config.samba_shares:
            if len(share_spec) < 4:
                continue
            for user_spec in str(share_spec[3]).split(','):
                normalized_user = user_spec.strip()
                if not normalized_user or ':' in normalized_user or normalized_user in seen_usernames:
                    continue
                seen_usernames.add(normalized_user)
                required_usernames.append(normalized_user)

    for username in required_usernames:
        cmd_parts.append(f"--credential {shlex.quote(username)} [REDACTED]")
    
    if config.enable_smbclient:
        cmd_parts.append("--smbclient")
    
    if config.smb_mounts:
        for mount_spec in config.smb_mounts:
            redacted_mount_spec = list(mount_spec)
            if len(redacted_mount_spec) >= 3 and ':' in str(redacted_mount_spec[2]):
                redacted_mount_spec[2] = redact_mount_credentials(str(redacted_mount_spec[2]))
            escaped_spec = ' '.join(shlex.quote(str(s)) for s in redacted_mount_spec)
            cmd_parts.append(f"--mount-smb {escaped_spec}")
    
    if config.sync_specs:
        for sync_spec in config.sync_specs:
            escaped_spec = ' '.join(shlex.quote(str(s)) for s in sync_spec)
            cmd_parts.append(f"--sync {escaped_spec}")
    
    if config.scrub_specs:
        for scrub_spec in config.scrub_specs:
            escaped_spec = ' '.join(shlex.quote(str(s)) for s in scrub_spec)
            cmd_parts.append(f"--scrub {escaped_spec}")
    
    if config.notify_specs:
        for notify_spec in config.notify_specs:
            escaped_spec = ' '.join(shlex.quote(str(s)) for s in notify_spec)
            cmd_parts.append(f"--notify {escaped_spec}")
    
    if config.no_restart:
        cmd_parts.append("--no-restart")
    
    if config.include_desktop:
        cmd_parts.append("--include-desktop")
    
    if config.include_cli_tools:
        cmd_parts.append("--include-cli-tools")
    
    if config.include_desktop_apps:
        cmd_parts.append("--include-desktop-apps")
    
    if config.include_workstation_dev_apps:
        cmd_parts.append("--include-workstation-dev-apps")
    
    if config.include_pc_dev_apps:
        cmd_parts.append("--include-pc-dev-apps")
    
    if config.include_web_server:
        cmd_parts.append("--include-web-server")
    
    if config.include_web_firewall:
        cmd_parts.append("--include-web-firewall")
    
    return ' '.join(cmd_parts)


def show_command(pattern: Optional[str] = None) -> None:
    configs: Deployments = get_all_configs(pattern)

    if not configs:
        if pattern:
            print(f"No configurations found matching '{pattern}'")
        else:
            print("No saved configurations found.")
        return

    for config_data in configs:
        host = config_data.get('host', 'Unknown')
        system_type = config_data.get('system_type', 'Unknown')
        args_dict = config_data.get('args', {})
        
        print("=" * 60)
        print(f"Host: {host}")
        print(f"System Type: {system_type}")
        print("-" * 60)
        
        try:
            config = SetupConfig.from_dict(host, system_type, args_dict)
            cmd = reconstruct_command(config)
            print(cmd)
        except Exception as e:
            print(f"Error reconstructing command: {e}")
        
        print()


def list_configurations(pattern: Optional[str] = None) -> None:
    from datetime import datetime
    
    configs: Deployments = get_all_configs(pattern)

    if not configs:
        if pattern:
            print(f"No configurations found matching '{pattern}'")
        else:
            print("No saved configurations found.")
        return

    host_width = 30
    name_width = 20
    type_width = 20
    user_width = 15
    date_width = 20
    status_width = 10
    total_width = host_width + name_width + type_width + user_width + date_width + status_width
    
    print(f"{'HOST':<{host_width}} {'NAME':<{name_width}} {'TYPE':<{type_width}} {'USER':<{user_width}} {'LAST RUN':<{date_width}} {'STATUS':<{status_width}}")
    print("-" * total_width)
    
    for config in configs:
        host = config.get('host', 'Unknown')
        name = config.get('name', '')
        system_type = config.get('system_type', 'Unknown')
        args = config.get('args', {})
        username = args.get('username', 'Unknown')
        
        # Format last run time
        last_start_time = config.get('last_start_time')
        last_end_time = config.get('last_end_time')
        last_success = config.get('last_success')
        
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
        
        # Format status
        if last_success is True:
            status_str = "PASS"
        elif last_success is False:
            status_str = "FAIL"
        else:
            status_str = "UNKNOWN"
        
        print(f"{host:<{host_width}} {name:<{name_width}} {system_type:<{type_width}} {username:<{user_width}} {last_run_str:<{date_width}} {status_str:<{status_width}}")


def show_info(pattern: Optional[str] = None) -> None:
    configs: Deployments = get_all_configs(pattern)

    if not configs:
        if pattern:
            print(f"No configurations found matching '{pattern}'")
        else:
            print("No saved configurations found.")
        return

    for config in configs:
        host = config.get('host', 'Unknown')
        name = config.get('name')
        tags = config.get('tags', [])
        system_type = config.get('system_type', 'Unknown')
        args = config.get('args', {})
        username = args.get('username', 'Unknown')
        
        print("=" * 60)
        print(f"Host: {host}")
        if name:
            print(f"Name: {name}")
        if tags:
            print(f"Tags: {', '.join(tags)}")
        print(f"Type: {system_type}")
        print(f"User: {username}")
        print("-" * 60)
        
        deploy_specs: JSONList = cast(JSONList, args.get('deploy_specs', []))
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
        if args.get('enable_ssl'): features.append("SSL")
        if args.get('enable_cloudflare'): features.append("Cloudflare")
        if args.get('install_ruby'): features.append("Ruby")
        if args.get('install_node'): features.append("Node")
        if args.get('install_go'): features.append("Go")
        if args.get('install_python'): features.append("Python")
        if args.get('install_office'): features.append("Office")
        if args.get('use_flatpak'): features.append("Flatpak")
        if args.get('enable_samba'): features.append("Samba")
        
        if features:
            print(f"Features: {', '.join(features)}")
        
        samba_shares: JSONList = cast(JSONList, args.get('samba_shares', []))
        if samba_shares:
            print("Samba Shares:")
            for share in samba_shares:
                if isinstance(share, list):
                    try:
                        share_list: JSONList = cast(JSONList, share)
                        name_part = str(share_list[1])
                        host_part = str(share_list[0])
                        path_part = str(share_list[2])
                        print(f"  - {name_part}_{host_part}: {path_part}")
                    except Exception:
                        continue
        
        from datetime import datetime
        last_start_time = config.get('last_start_time')
        last_end_time = config.get('last_end_time')
        last_success = config.get('last_success')
        
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


def remove_configurations(args: StrList) -> int:
    force = False
    pattern: Optional[str] = None
    
    for arg in args:
        if arg == '-y':
            force = True
        elif not arg.startswith('-'):
            pattern = arg
            
    if not pattern:
        print("Error: Pattern required for remove command")
        return 1
        
    configs = get_all_configs(pattern)
    
    if not configs:
        print(f"No configurations found matching '{pattern}'")
        return 1
        
    print(f"Found {len(configs)} configuration(s) to remove:")
    for config in configs:
        print(f"  - {config.get('host')}")
        
    if not force:
        response = input("\nAre you sure you want to remove these configurations? [y/N] ")
        if response.lower() != 'y':
            print("Aborted.")
            return 0
            
    count = 0
    for config in configs:
        host = config.get('host')
        if not host:
            continue
            
        cache_path = get_cache_path_for_host(host)
        try:
            if os.path.exists(cache_path):
                os.remove(cache_path)
                print(f"Removed {host}")
                count += 1
        except Exception as e:
            print(f"Error removing {host}: {e}")
            
    print(f"\nRemoved {count} configuration(s).")
    return 0


def execute_patch(config: SetupConfig) -> int:
    """Execute patch operation with the given configuration."""
    if not validate_username(config.username):
        print(f"Error: Invalid username: {config.username}")
        return 1
    
    if not os.path.exists(REMOTE_SCRIPT_PATH):
        print(f"Error: Remote setup script not found: {REMOTE_SCRIPT_PATH}")
        return 1
    
    lib_dir = os.path.join(os.path.dirname(REMOTE_SCRIPT_PATH), "lib")
    if not os.path.exists(lib_dir):
        print(f"Error: Library directory not found: {lib_dir}")
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
    except ValueError as e:
        print(f"Error: {e}")
        return 1
    
    start_time = time.time()
    returncode = 1
    try:
        if not config.dry_run:
            store_cli_credentials(config)
        returncode = run_remote_setup(runtime_config)
    finally:
        end_time = time.time()
        success = (returncode == 0)
        if not config.dry_run:
            save_setup_command(config, start_time, end_time, success)
    
    if returncode != 0:
        print(f"\n✗ Patch failed (exit code: {returncode})")
        return 1
    
    print()
    print("=" * 60)
    print("Patch Complete!")
    print("=" * 60)
    print(f"Host: {config.host}")
    print(f"System has been updated with new configuration")
    
    if config.friendly_name or config.tags:
        print()
        print_name_and_tags(config)
    
    print("=" * 60)
    
    return 0


def deploy_configurations(args: StrList) -> int:
    force = False
    pattern: Optional[str] = None
    
    for arg in args:
        if arg == '-y':
            force = True
        elif not arg.startswith('-'):
            pattern = arg
            
    if not pattern:
        print("Error: Pattern required for deploy command")
        return 1
        
    configs: Deployments = get_all_configs(pattern)
    
    if not configs:
        print(f"No configurations found matching '{pattern}'")
        return 1
        
    print(f"Found {len(configs)} configuration(s) to deploy:")
    for config in configs:
        host = config.get('host')
        deploy_specs = config.get('args', {}).get('deploy_specs', [])
        print(f"  - {host} ({len(deploy_specs)} deployments)")
        
    if not force:
        response = input("\nAre you sure you want to deploy to these hosts? [y/N] ")
        if response.lower() != 'y':
            print("Aborted.")
            return 0
            
    failures = 0
    for config_data in configs:
        host = config_data.get('host')
        system_type = config_data.get('system_type')
        args_dict = config_data.get('args', {})
        
        print(f"\nDeploying to {host}...")
        try:
            if not isinstance(host, str) or not isinstance(system_type, str) or not isinstance(args_dict, dict):
                raise ValueError("Invalid cached configuration format")
            args_dict = cast(JSONDict, args_dict)
            config = SetupConfig.from_dict(host, system_type, args_dict)
            if execute_patch(config) != 0:
                failures += 1
        except Exception as e:
            print(f"Error creating config for {host}: {e}")
            failures += 1
    if failures > 0:
        print(f"\nCompleted with {failures} failure(s).")
        return 1
        
    print("\nAll deployments completed successfully.")
    return 0


def create_patch_argument_parser() -> argparse.ArgumentParser:
    parser = create_argument_parser(
        description="Patch a previously configured system with new or modified settings",
        allow_steps=True
    )
    parser.formatter_class = argparse.RawDescriptionHelpFormatter
    parser.epilog = PATCH_SPECIAL_COMMANDS_HELP
    return parser


def _process_workspace_args(argv: StrList) -> StrList:
    filtered_args: StrList = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--workspace":
            if index + 1 >= len(argv):
                raise ValueError("--workspace requires a path")
            set_workspace_dir(argv[index + 1])
            index += 2
            continue
        filtered_args.append(arg)
        index += 1
    return filtered_args


def main() -> int:
    try:
        argv = _process_workspace_args(sys.argv[1:])
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    if argv:
        cmd = argv[0]
        if cmd in ['list', 'ls']:
            pattern = argv[1] if len(argv) > 1 else None
            list_configurations(pattern)
            return 0
        elif cmd == 'info':
            pattern = argv[1] if len(argv) > 1 else None
            show_info(pattern)
            return 0
        elif cmd in ['cmd', 'command']:
            pattern = argv[1] if len(argv) > 1 else None
            show_command(pattern)
            return 0
        elif cmd in ['rm', 'remove']:
            return remove_configurations(argv[1:])
        elif cmd == 'deploy':
            return deploy_configurations(argv[1:])

    parser = create_patch_argument_parser()
    
    if argcomplete:
        argcomplete.autocomplete(parser)
    
    args = parser.parse_args(argv)
    if getattr(args, 'workspace', None):
        set_workspace_dir(args.workspace)
    
    if not validate_host(args.host):
        print(f"Error: Invalid IP address or hostname: {args.host}")
        return 1
    
    cached_config = load_setup_command(args.host)
    if not cached_config:
        print(f"Error: No cached setup found for {args.host}")
        print(f"Please run the initial setup using the appropriate setup_*.py script first.")
        return 1
    
    new_config = SetupConfig.from_args(args, cached_config.system_type)
    
    merged_config = merge_setup_configs(cached_config, new_config)
    
    return execute_patch(merged_config)


if __name__ == "__main__":
    sys.exit(main())
