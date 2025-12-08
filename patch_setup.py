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
    parser = argparse.ArgumentParser(
        description="Patch a previously configured system with new or modified settings"
    )
    parser.add_argument("host", help="IP address or hostname of the target system")
    parser.add_argument("--password", help="User password for sudo operations")
    parser.add_argument("--key", help="SSH key file path")
    parser.add_argument("--timezone", help="System timezone (e.g., America/New_York)")
    parser.add_argument("--skip-audio", action="store_true",
                       help="Skip audio configuration (workstation/desktop only)")
    parser.add_argument("--desktop", choices=["xfce", "i3", "cinnamon"],
                       help="Desktop environment (workstation/desktop only)")
    parser.add_argument("--browser", choices=["brave", "firefox", "chrome"],
                       help="Web browser to install (workstation/desktop only)")
    parser.add_argument("--flatpak", action="store_true",
                       help="Install Flatpak support (workstation/desktop only)")
    parser.add_argument("--office", action="store_true",
                       help="Install LibreOffice")
    parser.add_argument("--dry-run", action="store_true",
                       help="Show what would be done without executing commands")
    parser.add_argument("--ruby", action="store_true",
                       help="Install rbenv + latest Ruby version")
    parser.add_argument("--go", action="store_true",
                       help="Install latest Go version")
    parser.add_argument("--node", action="store_true",
                       help="Install nvm + latest Node.JS + PNPM + update NPM")
    parser.add_argument("--deploy", action="append", nargs=2, metavar=("DOMAIN_OR_PATH", "GIT_URL"),
                       help="Deploy a git repository (domain.com/path or /path) to auto-configure nginx (can be used multiple times)")
    parser.add_argument("--steps", help="Custom setup steps")
    
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
    
    # Build new args dict from command line
    new_args = {}
    if args.password:
        new_args['password'] = args.password
    if args.key:
        new_args['key'] = args.key
    if args.timezone:
        new_args['timezone'] = args.timezone
    if args.skip_audio:
        new_args['skip_audio'] = args.skip_audio
    if args.desktop:
        new_args['desktop'] = args.desktop
    if args.browser:
        new_args['browser'] = args.browser
    if args.flatpak:
        new_args['flatpak'] = args.flatpak
    if args.office:
        new_args['office'] = args.office
    if args.ruby:
        new_args['ruby'] = args.ruby
    if args.go:
        new_args['go'] = args.go
    if args.node:
        new_args['node'] = args.node
    if args.steps:
        new_args['steps'] = args.steps
    if args.deploy:
        new_args['deploy'] = args.deploy
    
    # Merge arguments (add/modify but don't remove)
    merged_args = merge_setup_args(cached_args, new_args)
    
    # Extract values
    username = merged_args.get('username') or get_current_username()
    password = merged_args.get('password')
    key = merged_args.get('key')
    timezone = merged_args.get('timezone') or get_local_timezone()
    skip_audio = merged_args.get('skip_audio', False)
    desktop = merged_args.get('desktop', 'xfce')
    browser = merged_args.get('browser', 'brave')
    use_flatpak = merged_args.get('flatpak', False)
    install_office = merged_args.get('office', False)
    if system_type == "pc_dev" and 'office' not in merged_args:
        install_office = True
    ruby = merged_args.get('ruby', False)
    go = merged_args.get('go', False)
    node = merged_args.get('node', False)
    custom_steps = merged_args.get('steps')
    deploy_specs = merged_args.get('deploy')
    dry_run = args.dry_run
    
    if not validate_username(username):
        print(f"Error: Invalid username: {username}")
        return 1
    
    if not os.path.exists(REMOTE_SCRIPT_PATH):
        print(f"Error: Remote setup script not found: {REMOTE_SCRIPT_PATH}")
        return 1
    
    if not os.path.exists(REMOTE_MODULES_DIR):
        print(f"Error: Remote modules not found: {REMOTE_MODULES_DIR}")
        return 1
    
    # Display what we're doing
    print("=" * 60)
    print(f"Patching System: {cached['script']}")
    print("=" * 60)
    print(f"Host: {args.host}")
    print(f"User: {username}")
    print(f"Timezone: {timezone}")
    if skip_audio and system_type in ["workstation_desktop", "pc_dev"]:
        print("Skip audio: Yes")
    if desktop != "xfce" and system_type in ["workstation_desktop", "pc_dev", "workstation_dev"]:
        print(f"Desktop: {desktop}")
    if browser != "brave" and system_type in ["workstation_desktop", "pc_dev", "workstation_dev"]:
        print(f"Browser: {browser}")
    if use_flatpak and system_type in ["workstation_desktop", "pc_dev", "workstation_dev"]:
        print("Flatpak: Yes")
    if install_office:
        print("Office: Yes")
    if ruby:
        print("Ruby: Yes")
    if go:
        print("Go: Yes")
    if node:
        print("Node.js: Yes")
    if dry_run:
        print("Dry-run: Yes")
    if custom_steps:
        print(f"Steps: {custom_steps}")
    if deploy_specs:
        print(f"Deployments: {len(deploy_specs)} repository(ies)")
        for location, git_url in deploy_specs:
            print(f"  - {git_url} -> {location}")
    print("=" * 60)
    print()
    
    # Save updated setup command (unless dry-run)
    if not dry_run:
        save_setup_command(args.host, system_type, merged_args)
    
    # Run the setup with merged arguments (uses current script version)
    returncode = run_remote_setup(
        args.host, username, system_type, password, key,
        timezone, skip_audio, desktop, browser, use_flatpak, install_office,
        dry_run, ruby, go, node, custom_steps, deploy_specs
    )
    
    if returncode != 0:
        print(f"\n✗ Patch failed (exit code: {returncode})")
        return 1
    
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
