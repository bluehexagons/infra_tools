#!/usr/bin/env python3

import argparse
import sys
import os

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
    REMOTE_SCRIPT_PATH,
    REMOTE_MODULES_DIR
)


def main() -> int:
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
    print(f"Patching System: {cached['script']}")
    print("=" * 60)
    print(f"Host: {args.host}")
    print(f"User: {username}")
    print(f"Timezone: {timezone}")
    print("=" * 60)
    print()
    
    # Run the setup with merged arguments
    returncode = run_remote_setup(
        host=args.host,
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
        dry_run=args.dry_run,
        install_ruby=merged_args.get('install_ruby', False),
        install_go=merged_args.get('install_go', False),
        install_node=merged_args.get('install_node', False),
        custom_steps=merged_args.get('custom_steps'),
        deploy_specs=merged_args.get('deploy_specs'),
        full_deploy=merged_args.get('full_deploy', False),
        enable_ssl=merged_args.get('enable_ssl', False),
        ssl_email=merged_args.get('ssl_email'),
        enable_cloudflare=merged_args.get('enable_cloudflare', False)
    )
    
    if returncode != 0:
        print(f"\n✗ Patch failed (exit code: {returncode})")
        return 1
    
    # Save updated setup command only after successful execution (unless dry-run)
    if not args.dry_run:
        save_setup_command(args.host, system_type, merged_args)
    
    print()
    print("=" * 60)
    print("Patch Complete!")
    print("=" * 60)
    print(f"Host: {args.host}")
    print(f"System has been updated with new configuration")
    print("=" * 60)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
