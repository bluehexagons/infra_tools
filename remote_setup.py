#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.arg_parser import create_setup_argument_parser
from lib.config import SetupConfig
from lib.display import print_setup_summary
from lib.machine_state import save_machine_state, save_setup_config
from lib.notifications import send_setup_notification
from lib.remote_utils import validate_username, detect_os, set_dry_run
from lib.progress import progress_bar
from lib.system_types import get_steps_for_system_type
from lib.systemd_service import cleanup_all_infra_services
from typing import Optional
from lib.types import Deployments 


def extract_repo_name(git_url: str) -> str:
    repo_name = git_url.rstrip('/').split('/')[-1]
    if repo_name.endswith('.git'):
        repo_name = repo_name[:-4]
    return repo_name


def config_from_remote_args(args: argparse.Namespace) -> SetupConfig:
    if args.custom_steps:
        system_type = "custom_steps"
    elif args.system_type:
        system_type = args.system_type
    else:
        raise ValueError("Either --system-type or --steps must be specified")
    
    args.host = "localhost"
    
    config = SetupConfig.from_args(args, system_type)
    
    if system_type == "server_proxmox":
        config.username = "root"
    
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
    
    try:
        config = config_from_remote_args(args)
    except ValueError as e:
        print(f"Error: {e}")
        return 1
    
    if not validate_username(config.username):
        print(f"Error: Invalid username: {config.username}")
        return 1
    
    print_setup_summary(config, f"Remote Setup ({config.system_type})")
    sys.stdout.flush()

    detect_os()
    print("OS: Debian")
    sys.stdout.flush()
    
    # Save machine state for services to reference
    save_machine_state(
        machine_type=config.machine_type,
        system_type=config.system_type,
        username=config.username
    )
    print(f"Machine type: {config.machine_type}")
    sys.stdout.flush()
    
    # Save setup configuration for later recall
    try:
        config_dict = config.to_dict()
        config_dict['system_type'] = config.system_type
        save_setup_config(config_dict)
    except OSError as e:
        print(f"Warning: Failed to save setup configuration: {e}", file=sys.stderr)
    
    # Clean up all previously deployed services to ensure clean state
    # This treats the current deployment command as the desired baseline
    print("\nCleaning up existing infra_tools services...")
    sys.stdout.flush()
    # Use longer timeout for cleanup - scrub operations can take days
    cleanup_all_infra_services(dry_run=args.dry_run, wait_for_completion=True, timeout_seconds=600)
    sys.stdout.flush()

    steps = get_steps_for_system_type(config)
    
    # Send start notification
    if config.notify_specs:
        send_setup_notification(
            notify_specs=config.notify_specs,
            system_type=config.system_type,
            host=config.host,
            success=True,  # Not used for start notifications
            friendly_name=config.friendly_name,
            started=True,
        )
    
    setup_errors: list[str] = []
    
    total_steps = len(steps)
    for i, (name, func) in enumerate(steps, 1):
        bar = progress_bar(i, total_steps)
        print(f"\n{bar} [{i}/{total_steps}] {name}")
        sys.stdout.flush()
        try:
            func(config)
        except Exception as e:
            error_msg = f"Step '{name}' failed: {e}"
            print(f"  ✗ {error_msg}")
            setup_errors.append(error_msg)
            if config.notify_specs:
                send_setup_notification(
                    notify_specs=config.notify_specs,
                    system_type=config.system_type,
                    host=config.host,
                    success=False,
                    errors=setup_errors,
                    friendly_name=config.friendly_name,
                )
            raise
    
    bar = progress_bar(total_steps, total_steps)
    print(f"\n{bar} Complete!")
    
    if config.enable_cloudflare:
        from web.cloudflare_steps import (
            configure_cloudflare_firewall,
            create_cloudflared_config_directory,
            configure_nginx_for_cloudflare,
            install_cloudflared_service_helper
        )
        
        print("\n" + "=" * 60)
        print("Configuring Cloudflare tunnel support...")
        print("=" * 60)
        
        print("\n[1/4] Configuring firewall for Cloudflare tunnel")
        configure_cloudflare_firewall(config)
        
        print("\n[2/4] Creating cloudflared configuration directory")
        create_cloudflared_config_directory(config)
        
        print("\n[3/4] Configuring nginx for Cloudflare")
        configure_nginx_for_cloudflare(config)
        
        print("\n[4/4] Installing cloudflared setup helper")
        install_cloudflared_service_helper(config)
        
        print("\n✓ Cloudflare tunnel preconfiguration complete")
        print("  Run 'sudo setup-cloudflare-tunnel' to install cloudflared")
    
    if config.deploy_specs:
        from deploy.deploy_steps import deploy_repository
        import shutil
        import tempfile
        import subprocess
        
        print("\n" + "=" * 60)
        print("Deploying repositories...")
        print("=" * 60)
        
        deployments: Deployments = []
        
        if args.lite_deploy:
            for deploy_specs_str, git_url in config.deploy_specs:
                repo_name = extract_repo_name(git_url)
                source_path = f'/opt/infra_tools/deployments/{repo_name}'
                
                if not os.path.exists(source_path):
                    print(f"\n⚠ Warning: {source_path} not found, skipping {git_url}")
                    continue
                
                commit_hash: str = ""
                commit_file = f'/opt/infra_tools/deployments/{repo_name}.commit'
                if os.path.exists(commit_file):
                    try:
                        with open(commit_file, 'r') as f:
                            content = f.read().strip()
                            if content:
                                commit_hash = content
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
                    
                    from lib.deploy_utils import get_git_commit_hash
                    commit_hash_result = get_git_commit_hash(clone_path)
                    commit_hash: str = commit_hash_result if commit_hash_result else ""
                    
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
        
        if deployments:
            print("\n" + "=" * 60)
            print("Configuring Nginx...")
            print("=" * 60)
            
            from lib.nginx_config import create_nginx_sites_for_groups
            
            grouped_deployments: dict[Optional[str], Deployments] = {}
            for dep in deployments:
                key = dep.get('domain')
                grouped_deployments.setdefault(key, []).append(dep)
            
            create_nginx_sites_for_groups(grouped_deployments)
            
            if config.enable_ssl:
                from web.ssl_steps import install_certbot, setup_ssl_for_deployments
                
                print("\n" + "=" * 60)
                print("Installing certbot...")
                print("=" * 60)
                install_certbot(config)
                
                setup_ssl_for_deployments(deployments, config.ssl_email)
            
            if config.enable_cloudflare:
                from web.cloudflare_steps import run_cloudflare_tunnel_setup
                
                print("\n" + "=" * 60)
                print("Updating cloudflared config for deployments...")
                print("=" * 60)
                run_cloudflare_tunnel_setup(config)
    
    if config.enable_samba:
        from smb.samba_steps import (
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
        install_samba(config)
        
        print("\n[2/4] Configuring global Samba settings with security hardening")
        configure_samba_global_settings(config)
        
        print("\n[3/4] Configuring firewall for Samba")
        configure_samba_firewall(config)
        
        print("\n[4/4] Configuring fail2ban for Samba brute-force protection")
        configure_samba_fail2ban(config)
        
        if config.samba_shares:
            print("\n" + "=" * 60)
            print(f"Configuring {len(config.samba_shares)} Samba share(s)...")
            print("=" * 60)
            
            for i, share_spec in enumerate(config.samba_shares, 1):
                print(f"\n[{i}/{len(config.samba_shares)}] Setting up share: {share_spec[1]}_{share_spec[0]}")
                setup_samba_share(config, share_spec=share_spec)
        
        print("\n✓ Samba configuration complete")
    
    if config.smb_mounts:
        from smb.smb_mount_steps import configure_smb_mount
        
        print("\n" + "=" * 60)
        print("Configuring SMB mounts...")
        print("=" * 60)
        
        for i, mount_spec in enumerate(config.smb_mounts, 1):
            print(f"\n[{i}/{len(config.smb_mounts)}] Mounting {mount_spec[0]}")
            configure_smb_mount(config, mount_spec=mount_spec)
        
        print("\n✓ SMB mount configuration complete")
    
    if config.sync_specs or config.scrub_specs:
        from sync.sync_steps import install_rsync, create_sync_service
        from sync.scrub_steps import install_par2, create_scrub_service

        print("\n" + "=" * 60)
        print("Configuring sync and scrub services...")
        print("=" * 60)

        # Only run initial sync/scrub if flags are set
        run_initial = config.run_initial_sync or config.run_initial_scrub
        
        if run_initial:
            from lib.concurrent_sync_scrub import create_concurrent_coordinator
            from lib.concurrent_operations import OperationPriority
            
            print("Initializing concurrent operations...")
            coordinator = create_concurrent_coordinator(config)

            if config.sync_specs:
                install_rsync(config)
                if config.run_initial_sync:
                    print(f"\nSubmitting {len(config.sync_specs)} sync job(s) for background execution...")
                    for spec in config.sync_specs:
                        coordinator.submit_sync_operation(spec, priority=OperationPriority.NORMAL)
                else:
                    print(f"\nConfiguring {len(config.sync_specs)} sync service(s) (initial sync will run on first timer trigger)...")
                    for spec in config.sync_specs:
                        create_sync_service(config, spec, skip_initial_sync=True)

            if config.scrub_specs:
                install_par2(config)
                if config.run_initial_scrub:
                    print(f"\nSubmitting {len(config.scrub_specs)} scrub job(s) for background execution...")
                    for spec in config.scrub_specs:
                        coordinator.submit_scrub_operation(spec, priority=OperationPriority.NORMAL)
                else:
                    print(f"\nConfiguring {len(config.scrub_specs)} scrub service(s) (initial scrub will run on first timer trigger)...")
                    for spec in config.scrub_specs:
                        create_scrub_service(config, spec, skip_initial_scrub=True)

            print("\nWaiting for background operations to complete...")
            coordinator.wait_until_idle()
            print("\n✓ Concurrent operations complete")
        else:
            # Skip initial operations - just configure services
            if config.sync_specs:
                install_rsync(config)
                print(f"\nConfiguring {len(config.sync_specs)} sync service(s) (initial sync will run on first timer trigger)...")
                for spec in config.sync_specs:
                    create_sync_service(config, spec, skip_initial_sync=True)

            if config.scrub_specs:
                install_par2(config)
                print(f"\nConfiguring {len(config.scrub_specs)} scrub service(s) (initial scrub will run on first timer trigger)...")
                for spec in config.scrub_specs:
                    create_scrub_service(config, spec, skip_initial_scrub=True)
            
            print("\n✓ Sync and scrub services configured")
            print("Note: Initial sync/scrub operations will run when the timers trigger.")
            print("You can manually trigger them by starting the systemd services.")
    
    
    print("\n" + "=" * 60)
    print("✓ Remote setup complete!")
    print("=" * 60)
    
    if config.notify_specs:
        send_setup_notification(
            notify_specs=config.notify_specs,
            system_type=config.system_type,
            host=config.host,
            success=True,
            friendly_name=config.friendly_name,
        )
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
