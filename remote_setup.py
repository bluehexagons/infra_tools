#!/usr/bin/env python3

import argparse
import getpass
import os
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.arg_parser import create_setup_argument_parser
from lib.config import SetupConfig
from remote_modules.utils import validate_username, detect_os, set_dry_run
from remote_modules.progress import progress_bar
from remote_modules.system_types import get_steps_for_system_type


VALID_SYSTEM_TYPES = ["workstation_desktop", "pc_dev", "workstation_dev", "server_dev", "server_web", "server_proxmox", "custom_steps"]


def extract_repo_name(git_url: str) -> str:
    repo_name = git_url.rstrip('/').split('/')[-1]
    if repo_name.endswith('.git'):
        repo_name = repo_name[:-4]
    return repo_name


def config_from_remote_args(args: argparse.Namespace) -> SetupConfig:
    if args.steps:
        system_type = "custom_steps"
    elif args.system_type:
        system_type = args.system_type
    else:
        raise ValueError("Either --system-type or --steps must be specified")
    
    if system_type == "server_proxmox":
        username = "root"
    else:
        username = args.username or getpass.getuser()
    
    install_office = args.office
    if system_type == "pc_dev" and not args.office:
        install_office = True
    
    config = SetupConfig(
        host="localhost",
        username=username,
        system_type=system_type,
        password=args.password,
        ssh_key=None,
        timezone=args.timezone or "UTC",
        friendly_name=None,
        tags=None,
        enable_rdp=args.rdp,
        enable_x2go=args.x2go,
        enable_audio=args.audio,
        desktop=args.desktop,
        browser=args.browser,
        use_flatpak=args.flatpak,
        install_office=install_office,
        dry_run=args.dry_run,
        install_ruby=args.ruby,
        install_go=args.go,
        install_node=args.node,
        custom_steps=args.steps,
        deploy_specs=args.deploy,
        full_deploy=args.full_deploy,
        enable_ssl=args.ssl,
        ssl_email=args.ssl_email,
        enable_cloudflare=args.cloudflare,
        api_subdomain=args.api_subdomain,
        enable_samba=args.samba,
        samba_shares=args.share
    )
    
    return config


def main() -> int:
    parser = create_setup_argument_parser(
        description="Remote system setup",
        for_remote=True,
        allow_steps=True
    )
    
    args = parser.parse_args()
    
    if args.dry_run:
        set_dry_run(True)
        print("=" * 60)
        print("DRY-RUN MODE ENABLED")
        print("=" * 60)
    
    # Create config from arguments
    try:
        config = config_from_remote_args(args)
    except ValueError as e:
        print(f"Error: {e}")
        return 1
    
    # Validate username
    if not validate_username(config.username):
        print(f"Error: Invalid username: {config.username}")
        return 1
    
    # Print configuration
    print("=" * 60)
    print(f"Remote Setup ({config.system_type})")
    print("=" * 60)
    if config.system_type != "server_proxmox":
        print(f"User: {config.username}")
    print(f"Timezone: {config.timezone}")
    if config.system_type in ["workstation_desktop", "pc_dev", "workstation_dev"]:
        print(f"RDP: {'Yes' if config.enable_rdp else 'No'}")
        print(f"X2Go: {'Yes' if config.enable_x2go else 'No'}")
    elif config.enable_rdp and config.system_type == "server_dev":
        print("RDP: Yes")
    if config.enable_x2go and config.system_type == "server_dev":
        print("X2Go: Yes")
    if config.enable_audio:
        print("Audio: Yes")
    if config.desktop != "xfce" and config.system_type in ["workstation_desktop", "pc_dev", "workstation_dev"]:
        print(f"Desktop: {config.desktop}")
    if config.browser != "brave" and config.system_type in ["workstation_desktop", "pc_dev", "workstation_dev"]:
        print(f"Browser: {config.browser}")
    if config.use_flatpak and config.system_type in ["workstation_desktop", "pc_dev", "workstation_dev"]:
        print("Flatpak: Yes")
    if config.install_office and config.system_type in ["workstation_desktop", "pc_dev", "workstation_dev"]:
        print("Office: Yes")
    if config.dry_run:
        print("Dry-run: Yes")
    if config.custom_steps:
        print(f"Steps: {config.custom_steps}")
    if config.deploy_specs:
        print(f"Deployments: {len(config.deploy_specs)} repository(ies)")
        for location, git_url in config.deploy_specs:
            print(f"  - {git_url} -> {location}")
        if config.enable_ssl:
            print("SSL: Yes (Let's Encrypt)")
            if config.ssl_email:
                print(f"SSL Email: {config.ssl_email}")
    if config.enable_cloudflare:
        print("Cloudflare: Yes (tunnel preconfiguration)")
    sys.stdout.flush()

    detect_os()
    print("OS: Debian")
    sys.stdout.flush()

    steps = get_steps_for_system_type(config)
    
    total_steps = len(steps)
    for i, (name, func) in enumerate(steps, 1):
        bar = progress_bar(i, total_steps)
        print(f"\n{bar} [{i}/{total_steps}] {name}")
        sys.stdout.flush()
        func(config)
    
    bar = progress_bar(total_steps, total_steps)
    print(f"\n{bar} Complete!")
    
    # Configure Cloudflare tunnel if requested
    if config.enable_cloudflare and config.system_type == "server_web":
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
        configure_cloudflare_firewall()
        
        print("\n[2/4] Creating cloudflared configuration directory")
        create_cloudflared_config_directory()
        
        print("\n[3/4] Configuring nginx for Cloudflare")
        configure_nginx_for_cloudflare()
        
        print("\n[4/4] Installing cloudflared setup helper")
        install_cloudflared_service_helper()
        
        print("\n✓ Cloudflare tunnel preconfiguration complete")
        print("  Run 'sudo setup-cloudflare-tunnel' to install cloudflared")
    
    # Handle deployments if specified
    if config.deploy_specs:
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
            for deploy_specs_str, git_url in config.deploy_specs:
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
                        full_deploy=config.full_deploy,
                        web_user="rails",
                        web_group="rails",
                        keep_source=True,
                        api_subdomain=config.api_subdomain
                    )
                    if info:
                        deployments.append(info)
        else:
            # Clone repositories directly (local execution)
            temp_dir = tempfile.mkdtemp(prefix="infra_deploy_")
            try:
                for deploy_specs_str, git_url in config.deploy_specs:
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
                            full_deploy=config.full_deploy,
                            web_user="rails",
                            web_group="rails",
                            keep_source=True,
                            api_subdomain=config.api_subdomain
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
            
            create_nginx_sites_for_groups(grouped_deployments)
            
            # Set up SSL if requested
            if config.enable_ssl:
                from remote_modules.ssl_steps import install_certbot, setup_ssl_for_deployments
                
                print("\n" + "=" * 60)
                print("Installing certbot...")
                print("=" * 60)
                install_certbot(config)
                
                setup_ssl_for_deployments(deployments, config.ssl_email)
            
            # Update Cloudflare tunnel configuration if configured
            if config.enable_cloudflare:
                from remote_modules.cloudflare_steps import run_cloudflare_tunnel_setup
                
                print("\n" + "=" * 60)
                print("Updating cloudflared config for deployments...")
                print("=" * 60)
                run_cloudflare_tunnel_setup(config)
    
    # Configure Samba if requested
    if config.enable_samba:
        from remote_modules.samba_steps import (
            install_samba,
            configure_samba_firewall,
            configure_samba_global_settings,
            configure_samba_fail2ban,
            setup_samba_share
        )
        
        print("\n" + "=" * 60)
        print("Configuring Samba...")
        print("=" * 60)
        
        print("\n[1/4] Installing Samba")
        install_samba()
        
        print("\n[2/4] Configuring global Samba settings with security hardening")
        configure_samba_global_settings()
        
        print("\n[3/4] Configuring firewall for Samba")
        configure_samba_firewall()
        
        print("\n[4/4] Configuring fail2ban for Samba brute-force protection")
        configure_samba_fail2ban()
        
        if config.samba_shares:
            print("\n" + "=" * 60)
            print(f"Configuring {len(config.samba_shares)} Samba share(s)...")
            print("=" * 60)
            
            for i, share_spec in enumerate(config.samba_shares, 1):
                print(f"\n[{i}/{len(config.samba_shares)}] Setting up share: {share_spec[1]}_{share_spec[0]}")
                setup_samba_share(config, share_spec=share_spec)
        
        print("\n✓ Samba configuration complete")
    
    print("\n" + "=" * 60)
    print("✓ Remote setup complete!")
    print("=" * 60)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
