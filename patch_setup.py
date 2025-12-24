#!/usr/bin/env python3

import argparse
import sys
import os
import json

# Add parent directory to path to import lib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.setup_common import (
    load_setup_command,
    merge_setup_args,
    validate_host,
    create_argument_parser,
    run_remote_setup,
    save_setup_command,
    get_local_timezone,
    get_current_username,
    validate_username,
    print_name_and_tags,
    REMOTE_SCRIPT_PATH,
    REMOTE_MODULES_DIR,
    SETUP_CACHE_DIR,
    get_cache_path_for_host
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

    print(f"{'HOST':<30} {'NAME':<20} {'TYPE':<20} {'USER':<15}")
    print("-" * 85)
    
    for config in configs:
        host = config.get('host', 'Unknown')
        name = config.get('name', '')
        system_type = config.get('system_type', 'Unknown')
        args = config.get('args', {})
        username = args.get('username', 'Unknown')
        
        print(f"{host:<30} {name:<20} {system_type:<20} {username:<15}")


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


def execute_patch(host: str, system_type: str, merged_args: dict, dry_run: bool = False) -> int:
    # Extract values with defaults
    username = merged_args.get('username') or get_current_username()
    timezone = merged_args.get('timezone') or get_local_timezone()
    desktop = merged_args.get('desktop') or 'xfce'
    browser = merged_args.get('browser') or 'brave'
    
    # Handle office default for pc_dev
    install_office = merged_args.get('install_office', False)
    if system_type == "pc_dev" and 'install_office' not in merged_args:
        install_office = True
        merged_args['install_office'] = True

    if not validate_username(username):
        print(f"Error: Invalid username: {username}")
        return 1
    
    if not os.path.exists(REMOTE_SCRIPT_PATH):
        print(f"Error: Remote setup script not found: {REMOTE_SCRIPT_PATH}")
        return 1
    
    if not os.path.exists(REMOTE_MODULES_DIR):
        print(f"Error: Remote modules not found: {REMOTE_MODULES_DIR}")
        return 1
    
    print("=" * 60)
    print(f"Patching System: {system_type}")
    print("=" * 60)
    print(f"Host: {host}")
    print(f"User: {username}")
    print(f"Timezone: {timezone}")
    print("=" * 60)
    print()
    
    # Run the setup with merged arguments
    returncode = run_remote_setup(
        host=host,
        username=username,
        system_type=system_type,
        password=merged_args.get('password'),
        ssh_key=merged_args.get('ssh_key'),
        timezone=timezone,
        skip_audio=merged_args.get('skip_audio', False),
        desktop=desktop,
        browser=browser,
        use_flatpak=merged_args.get('use_flatpak', False),
        install_office=install_office,
        dry_run=dry_run,
        install_ruby=merged_args.get('install_ruby', False),
        install_go=merged_args.get('install_go', False),
        install_node=merged_args.get('install_node', False),
        custom_steps=merged_args.get('custom_steps'),
        deploy_specs=merged_args.get('deploy_specs'),
        full_deploy=merged_args.get('full_deploy', False),
        enable_ssl=merged_args.get('enable_ssl', False),
        ssl_email=merged_args.get('ssl_email'),
        enable_cloudflare=merged_args.get('enable_cloudflare', False),
        api_subdomain=merged_args.get('api_subdomain', False),
        enable_samba=merged_args.get('enable_samba', False),
        samba_shares=merged_args.get('samba_shares')
    )
    
    if returncode != 0:
        print(f"\n✗ Patch failed (exit code: {returncode})")
        return 1
    
    # Save updated setup command only after successful execution (unless dry-run)
    if not dry_run:
        save_setup_command(host, system_type, merged_args)
    
    print()
    print("=" * 60)
    print("Patch Complete!")
    print("=" * 60)
    print(f"Host: {host}")
    print(f"System has been updated with new configuration")
    
    # Print name and tags if present
    friendly_name = merged_args.get('friendly_name')
    tags_str = merged_args.get('tags')
    tags = []
    if tags_str:
        tags = [tag.strip() for tag in tags_str.split(',') if tag.strip()]
    if friendly_name or tags:
        print()
        print_name_and_tags(friendly_name, tags)
    
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
    for config in configs:
        host = config.get('host')
        system_type = config.get('system_type')
        args_dict = config.get('args', {})
        
        print(f"\nDeploying to {host}...")
        if execute_patch(host, system_type, args_dict) != 0:
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
    
    # Load cached setup command
    cached = load_setup_command(args.host)
    if not cached:
        print(f"Error: No cached setup found for {args.host}")
        print(f"Please run the initial setup using the appropriate setup_*.py script first.")
        return 1
    
    system_type = cached['system_type']
    cached_args = cached['args']
    
    # Build new args dict from command line, filtering out None values
    # Note: We allow False values now to support disabling features via --no-feature flags
    new_args = {k: v for k, v in vars(args).items() if v is not None}
    
    if 'host' in new_args:
        del new_args['host']
        
    # Merge arguments (add/modify but don't remove)
    merged_args = merge_setup_args(cached_args, new_args)
    
    return execute_patch(args.host, system_type, merged_args, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
