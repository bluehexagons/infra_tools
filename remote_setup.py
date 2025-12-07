#!/usr/bin/env python3

import argparse
import getpass
import os
import shlex
import sys
from typing import Optional

from remote_modules.utils import validate_username, detect_os, set_dry_run
from remote_modules.progress import progress_bar
from remote_modules.system_types import get_steps_for_system_type


VALID_SYSTEM_TYPES = ["workstation_desktop", "pc_dev", "workstation_dev", "server_dev", "server_web", "server_proxmox", "custom_steps"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Remote system setup")
    parser.add_argument("--system-type", required=False,
                       choices=VALID_SYSTEM_TYPES,
                       help="System type to setup")
    parser.add_argument("--steps", default=None,
                       help="Space-separated list of steps to run (e.g., 'install_ruby install_node')")
    parser.add_argument("--username", default=None,
                       help="Username (defaults to current user, not used for server_proxmox)")
    parser.add_argument("--password", default=None,
                       help="User password (not used for server_proxmox)")
    parser.add_argument("--timezone", default=None,
                       help="Timezone (defaults to UTC)")
    parser.add_argument("--skip-audio", action="store_true",
                       help="Skip audio setup")
    parser.add_argument("--desktop", choices=["xfce", "i3", "cinnamon"], default="xfce",
                       help="Desktop environment to install (default: xfce)")
    parser.add_argument("--browser", choices=["brave", "firefox", "browsh", "vivaldi", "lynx"], default="brave",
                       help="Web browser to install (default: brave)")
    parser.add_argument("--flatpak", action="store_true",
                       help="Install desktop apps via Flatpak when available (non-containerized environments)")
    parser.add_argument("--office", action="store_true",
                       help="Install LibreOffice (desktop only)")
    parser.add_argument("--dry-run", action="store_true",
                       help="Show what would be done without executing commands")
    parser.add_argument("--ruby", action="store_true",
                       help="Install rbenv + latest Ruby version")
    parser.add_argument("--go", action="store_true",
                       help="Install latest Go version")
    parser.add_argument("--node", action="store_true",
                       help="Install nvm + latest Node.JS + PNPM + update NPM")
    parser.add_argument("--deploy", action="append", nargs=2, metavar=("LOCATION", "GIT_URL"),
                       help="Deploy a git repository to the specified location (can be used multiple times)")
    
    args = parser.parse_args()
    
    if args.dry_run:
        set_dry_run(True)
        print("=" * 60)
        print("DRY-RUN MODE ENABLED")
        print("=" * 60)
    
    if args.steps:
        system_type = "custom_steps"
    elif args.system_type:
        system_type = args.system_type
    else:
        print("Error: Either --system-type or --steps must be specified")
        return 1
    
    if system_type == "server_proxmox":
        username = "root"
    else:
        username = args.username or getpass.getuser()
        if not validate_username(username):
            print(f"Error: Invalid username: {username}")
            return 1

    print("=" * 60)
    print(f"Remote Setup ({system_type})")
    print("=" * 60)
    if system_type != "server_proxmox":
        print(f"User: {username}")
    print(f"Timezone: {args.timezone or 'UTC'}")
    if args.skip_audio:
        print("Skip audio: Yes")
    if args.desktop != "xfce" and system_type in ["workstation_desktop", "pc_dev", "workstation_dev"]:
        print(f"Desktop: {args.desktop}")
    if args.browser != "brave" and system_type in ["workstation_desktop", "pc_dev", "workstation_dev"]:
        print(f"Browser: {args.browser}")
    if args.flatpak and system_type in ["workstation_desktop", "pc_dev", "workstation_dev"]:
        print("Flatpak: Yes")
    
    # Default to installing LibreOffice for pc_dev
    install_office_flag = args.office
    if system_type == "pc_dev" and not args.office:
        install_office_flag = True
    
    if install_office_flag and system_type in ["workstation_desktop", "pc_dev", "workstation_dev"]:
        print("Office: Yes")
    if args.dry_run:
        print("Dry-run: Yes")
    if args.steps:
        print(f"Steps: {args.steps}")
    if args.deploy:
        print(f"Deployments: {len(args.deploy)} repository(ies)")
        for location, git_url in args.deploy:
            print(f"  - {git_url} -> {location}")
    sys.stdout.flush()

    os_type = detect_os()
    print(f"OS: {os_type}")
    sys.stdout.flush()

    steps = get_steps_for_system_type(system_type, args.skip_audio, args.desktop, args.browser, args.flatpak, install_office_flag, args.ruby, args.go, args.node, args.steps)
    total_steps = len(steps)
    for i, (name, func) in enumerate(steps, 1):
        bar = progress_bar(i, total_steps)
        print(f"\n{bar} [{i}/{total_steps}] {name}")
        sys.stdout.flush()
        func(
            username=username,
            pw=args.password,
            os_type=os_type,
            timezone=args.timezone,
            desktop=args.desktop,
            browser=args.browser,
            use_flatpak=args.flatpak,
            install_office=install_office_flag
        )
    
    bar = progress_bar(total_steps, total_steps)
    print(f"\n{bar} Complete!")
    
    # Handle deployments if specified
    if args.deploy:
        from remote_modules.deploy_steps import detect_project_type, build_rails_project, build_node_project, build_static_project
        import shutil
        import tempfile
        import subprocess
        
        print("\n" + "=" * 60)
        print("Deploying repositories...")
        print("=" * 60)
        
        temp_dir = tempfile.mkdtemp(prefix="infra_deploy_")
        try:
            for location, git_url in args.deploy:
                repo_name = git_url.rstrip('/').split('/')[-1]
                if repo_name.endswith('.git'):
                    repo_name = repo_name[:-4]
                
                clone_path = os.path.join(temp_dir, repo_name)
                dest_path = os.path.join(location, repo_name) if location else repo_name
                
                print(f"\nCloning {git_url}...")
                result = subprocess.run(
                    ["git", "clone", git_url, clone_path],
                    capture_output=True,
                    text=True,
                    timeout=300
                )
                
                if result.returncode != 0:
                    print(f"  Error cloning repository: {result.stderr}")
                    continue
                
                print(f"  ✓ Cloned to {clone_path}")
                
                # Create destination directory
                os.makedirs(os.path.dirname(dest_path) if os.path.dirname(dest_path) else '.', exist_ok=True)
                
                # Move from temp to destination
                if os.path.exists(dest_path):
                    print(f"  Destination {dest_path} already exists, removing...")
                    shutil.rmtree(dest_path)
                
                shutil.move(clone_path, dest_path)
                print(f"  ✓ Moved to {dest_path}")
                
                # Detect project type and build
                project_type = detect_project_type(dest_path)
                print(f"  Detected project type: {project_type}")
                
                if project_type == 'rails':
                    build_rails_project(dest_path)
                elif project_type == 'node':
                    build_node_project(dest_path)
                elif project_type == 'static':
                    build_static_project(dest_path)
                else:
                    print(f"  ⚠ Unknown project type, no build performed")
                
                # Set proper permissions
                subprocess.run(f"chown -R www-data:www-data {shlex.quote(dest_path)}", shell=True, check=False)
                subprocess.run(f"chmod -R 755 {shlex.quote(dest_path)}", shell=True, check=False)
                
                print(f"  ✓ Repository deployed to {dest_path}")
        finally:
            # Clean up temp directory
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
    
    print("\n" + "=" * 60)
    print("Setup completed successfully!")
    print("=" * 60)
    sys.stdout.flush()

    return 0


if __name__ == "__main__":
    sys.exit(main())
