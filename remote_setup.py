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


def extract_repo_name(git_url: str) -> str:
    """Extract repository name from git URL."""
    repo_name = git_url.rstrip('/').split('/')[-1]
    if repo_name.endswith('.git'):
        repo_name = repo_name[:-4]
    return repo_name


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
    parser.add_argument("--deploy", action="append", nargs=2, metavar=("DOMAIN_OR_PATH", "GIT_URL"),
                       help="Deploy a git repository (domain.com/path or /path) to auto-configure nginx. Can be comma-separated for multiple locations.")
    parser.add_argument("--lite-deploy", action="store_true",
                       help="Use pre-uploaded repository files instead of cloning (for remote execution)")
    parser.add_argument("--full-deploy", action="store_true",
                       help="Always rebuild deployments even if they haven't changed (default: skip unchanged deployments)")
    parser.add_argument("--ssl", action="store_true",
                       help="Enable Let's Encrypt SSL/TLS certificates for deployed domains")
    parser.add_argument("--ssl-email",
                       help="Email address for Let's Encrypt registration (optional)")
    parser.add_argument("--cloudflare", action="store_true",
                       help="Preconfigure server for Cloudflare tunnel (disables public HTTP/HTTPS ports)")
    parser.add_argument("--api-subdomain", action="store_true",
                       help="Deploy Rails API as a subdomain (api.domain.com) instead of a subdirectory (domain.com/api)")
    
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
        if args.ssl:
            print("SSL: Yes (Let's Encrypt)")
            if args.ssl_email:
                print(f"SSL Email: {args.ssl_email}")
    if args.cloudflare:
        print("Cloudflare: Yes (tunnel preconfiguration)")
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
    
    # Configure Cloudflare tunnel if requested
    if args.cloudflare and system_type == "server_web":
        from remote_modules.cloudflare_steps import (
            configure_cloudflare_firewall,
            create_cloudflared_config_directory,
            configure_nginx_for_cloudflare,
            install_cloudflared_service_helper
        )
        
        print("\n" + "=" * 60)
        print("Configuring Cloudflare tunnel support...")
        print("=" * 60)
        
        print("\n[1/4] Configuring firewall for Cloudflare tunnel")
        configure_cloudflare_firewall(os_type=os_type)
        
        print("\n[2/4] Creating cloudflared configuration directory")
        create_cloudflared_config_directory()
        
        print("\n[3/4] Configuring nginx for Cloudflare")
        configure_nginx_for_cloudflare()
        
        print("\n[4/4] Installing cloudflared setup helper")
        install_cloudflared_service_helper()
        
        print("\n✓ Cloudflare tunnel preconfiguration complete")
        print("  Run 'sudo setup-cloudflare-tunnel' to install cloudflared")
    
    # Handle deployments if specified
    if args.deploy:
        from remote_modules.deploy_steps import deploy_repository
        import shutil
        import tempfile
        import subprocess
        
        print("\n" + "=" * 60)
        print("Deploying repositories...")
        print("=" * 60)
        
        deployments = []
        
        if args.lite_deploy:
            # Use pre-uploaded files from /opt/infra_tools/deployments/
            for deploy_specs_str, git_url in args.deploy:
                repo_name = extract_repo_name(git_url)
                source_path = f'/opt/infra_tools/deployments/{repo_name}'
                
                if not os.path.exists(source_path):
                    print(f"\n⚠ Warning: {source_path} not found, skipping {git_url}")
                    continue
                
                # Read commit hash if available
                commit_hash = None
                commit_file = f'/opt/infra_tools/deployments/{repo_name}.commit'
                if os.path.exists(commit_file):
                    try:
                        with open(commit_file, 'r') as f:
                            commit_hash = f.read().strip()
                    except Exception:
                        pass
                
                for deploy_spec in deploy_specs_str.split(','):
                    deploy_spec = deploy_spec.strip()
                    if not deploy_spec: continue

                    print(f"\nDeploying pre-uploaded repository: {repo_name}")
                    info = deploy_repository(
                        source_path=source_path,
                        deploy_spec=deploy_spec,
                        git_url=git_url,
                        commit_hash=commit_hash,
                        full_deploy=args.full_deploy,
                        web_user="rails",
                        web_group="rails",
                        keep_source=True,
                        api_subdomain=args.api_subdomain
                    )
                    if info:
                        deployments.append(info)
        else:
            # Clone repositories directly (local execution)
            temp_dir = tempfile.mkdtemp(prefix="infra_deploy_")
            try:
                for deploy_specs_str, git_url in args.deploy:
                    repo_name = extract_repo_name(git_url)
                    clone_path = os.path.join(temp_dir, repo_name)
                    
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
                    
                    # Get commit hash
                    from shared.deploy_utils import get_git_commit_hash
                    commit_hash = get_git_commit_hash(clone_path)
                    
                    for deploy_spec in deploy_specs_str.split(','):
                        deploy_spec = deploy_spec.strip()
                        if not deploy_spec: continue

                        info = deploy_repository(
                            source_path=clone_path,
                            deploy_spec=deploy_spec,
                            git_url=git_url,
                            commit_hash=commit_hash,
                            full_deploy=args.full_deploy,
                            web_user="rails",
                            web_group="rails",
                            keep_source=True,
                            api_subdomain=args.api_subdomain
                        )
                        if info:
                            deployments.append(info)
            finally:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
        
        # Configure Nginx for all deployments
        if deployments:
            print("\n" + "=" * 60)
            print("Configuring Nginx...")
            print("=" * 60)
            
            from collections import defaultdict
            from shared.nginx_config import create_nginx_sites_for_groups
            from remote_modules.utils import run
            
            grouped_deployments = defaultdict(list)
            for dep in deployments:
                grouped_deployments[dep['domain']].append(dep)
            
            create_nginx_sites_for_groups(grouped_deployments, run)
            
            # Set up SSL if requested
            if args.ssl:
                from remote_modules.ssl_steps import install_certbot, setup_ssl_for_deployments
                
                print("\n" + "=" * 60)
                print("Installing certbot...")
                print("=" * 60)
                install_certbot(os_type=os_type)
                
                setup_ssl_for_deployments(deployments, args.ssl_email, run)
            
            # Update Cloudflare tunnel configuration if configured
            if args.cloudflare:
                from remote_modules.cloudflare_steps import run_cloudflare_tunnel_setup
                
                print("\n" + "=" * 60)
                print("Updating Cloudflare tunnel configuration...")
                print("=" * 60)
                run_cloudflare_tunnel_setup()
    
    print("\n" + "=" * 60)
    print("Setup completed successfully!")
    print("=" * 60)
    sys.stdout.flush()

    return 0


if __name__ == "__main__":
    sys.exit(main())
