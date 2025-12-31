#!/usr/bin/env python3

import argparse
import sys
import os
import json

# Add parent directory to path to import lib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.config import SetupConfig
from lib.validators import validate_host, validate_username
from lib.display import print_name_and_tags
from lib.cache import (
    load_setup_command,
    merge_setup_configs,
    save_setup_command,
    get_cache_path_for_host,
    SETUP_CACHE_DIR
)
from lib.setup_common import (
    create_argument_parser,
    run_remote_setup,
    REMOTE_SCRIPT_PATH
)


def get_all_configs(pattern: str = None) -> list:
    if not os.path.exists(SETUP_CACHE_DIR):
        return []

    configs = []
    try:
        for filename in os.listdir(SETUP_CACHE_DIR):
            if not filename.endswith('.json'):
                continue
                
            filepath = os.path.join(SETUP_CACHE_DIR, filename)
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)
                    configs.append(data)
            except Exception:
                continue
    except Exception as e:
        print(f"Error reading configurations: {e}")
        return []

    # Filter by pattern if provided
    if pattern:
        pattern = pattern.lower()
        filtered = []
        for c in configs:
            # Check host
            if pattern in c.get('host', '').lower():
                filtered.append(c)
                continue
            # Check name
            if pattern in c.get('name', '').lower():
                filtered.append(c)
                continue
            # Check tags
            tags = c.get('tags', [])
            if any(pattern in tag.lower() for tag in tags):
                filtered.append(c)
                continue
        configs = filtered
    
    # Sort by host
    configs.sort(key=lambda x: x.get('host', ''))
    
    return configs


def list_configurations(pattern: str = None) -> None:
    configs = get_all_configs(pattern)

    if not configs:
        if pattern:
            print(f"No configurations found matching '{pattern}'")
        else:
            print("No saved configurations found.")
        return

    # Column widths
    host_width = 30
    name_width = 20
    type_width = 20
    user_width = 15
    total_width = host_width + name_width + type_width + user_width
    
    print(f"{'HOST':<{host_width}} {'NAME':<{name_width}} {'TYPE':<{type_width}} {'USER':<{user_width}}")
    print("-" * total_width)
    
    for config in configs:
        host = config.get('host', 'Unknown')
        name = config.get('name', '')
        system_type = config.get('system_type', 'Unknown')
        args = config.get('args', {})
        username = args.get('username', 'Unknown')
        
        print(f"{host:<{host_width}} {name:<{name_width}} {system_type:<{type_width}} {username:<{user_width}}")


def show_info(pattern: str = None) -> None:
    configs = get_all_configs(pattern)

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
        
        # Show deployments
        deploy_specs = args.get('deploy_specs', [])
        if deploy_specs:
            print("Deployments:")
            for spec in deploy_specs:
                if isinstance(spec, list) and len(spec) >= 2:
                    print(f"  - {spec[1]} -> {spec[0]}")
                else:
                    print(f"  - {spec}")
        else:
            print("Deployments: None")
            
        # Show key features
        features = []
        if args.get('enable_ssl'): features.append("SSL")
        if args.get('enable_cloudflare'): features.append("Cloudflare")
        if args.get('install_ruby'): features.append("Ruby")
        if args.get('install_node'): features.append("Node")
        if args.get('install_go'): features.append("Go")
        if args.get('install_office'): features.append("Office")
        if args.get('use_flatpak'): features.append("Flatpak")
        if args.get('enable_samba'): features.append("Samba")
        
        if features:
            print(f"Features: {', '.join(features)}")
        
        # Show Samba shares
        samba_shares = args.get('samba_shares', [])
        if samba_shares:
            print("Samba Shares:")
            for share in samba_shares:
                if isinstance(share, list) and len(share) >= 4:
                    print(f"  - {share[1]}_{share[0]}: {share[2]}")
        
        print()


def remove_configurations(args: list) -> int:
    force = False
    pattern = None
    
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
    
    # Run the setup with configuration
    returncode = run_remote_setup(config)
    
    if returncode != 0:
        print(f"\n✗ Patch failed (exit code: {returncode})")
        return 1
    
    # Save updated setup command only after successful execution (unless dry-run)
    if not config.dry_run:
        save_setup_command(config)
    
    print()
    print("=" * 60)
    print("Patch Complete!")
    print("=" * 60)
    print(f"Host: {config.host}")
    print(f"System has been updated with new configuration")
    
    # Print name and tags if present
    if config.friendly_name or config.tags:
        print()
        print_name_and_tags(config)
    
    print("=" * 60)
    
    return 0


def deploy_configurations(args: list) -> int:
    force = False
    pattern = None
    
    for arg in args:
        if arg == '-y':
            force = True
        elif not arg.startswith('-'):
            pattern = arg
            
    if not pattern:
        print("Error: Pattern required for deploy command")
        return 1
        
    configs = get_all_configs(pattern)
    
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


def main() -> int:
    # Check for subcommands
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd in ['list', 'ls']:
            pattern = sys.argv[2] if len(sys.argv) > 2 else None
            list_configurations(pattern)
            return 0
        elif cmd == 'info':
            pattern = sys.argv[2] if len(sys.argv) > 2 else None
            show_info(pattern)
            return 0
        elif cmd in ['rm', 'remove']:
            return remove_configurations(sys.argv[2:])
        elif cmd == 'deploy':
            return deploy_configurations(sys.argv[2:])

    parser = create_argument_parser(
        description="Patch a previously configured system with new or modified settings",
        allow_steps=True
    )
    
    args = parser.parse_args()
    
    if not validate_host(args.host):
        print(f"Error: Invalid IP address or hostname: {args.host}")
        return 1
    
    # Load cached setup configuration
    cached_config = load_setup_command(args.host)
    if not cached_config:
        print(f"Error: No cached setup found for {args.host}")
        print(f"Please run the initial setup using the appropriate setup_*.py script first.")
        return 1
    
    # Create new config from command line args
    new_config = SetupConfig.from_args(args, cached_config.system_type)
    
    # Merge configurations (new values override cached values)
    merged_config = merge_setup_configs(cached_config, new_config)
    
    return execute_patch(merged_config)


if __name__ == "__main__":
    sys.exit(main())
