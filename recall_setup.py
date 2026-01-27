#!/usr/bin/env python3
"""Recall setup configuration from a remote host.

This script attempts to retrieve the stored configuration from a remote host,
or if not found, reconstructs it by analyzing the server state.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Optional, Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.config import SetupConfig


def build_ssh_command(host: str, username: str, ssh_key: Optional[str] = None) -> list[str]:
    """Build an SSH command for connecting to a remote host.
    
    Uses same options as setup_common.py for consistency.
    """
    ssh_opts = [
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=30",
        "-o", "ServerAliveInterval=30",
    ]
    if ssh_key:
        ssh_opts.extend(["-i", ssh_key])
    
    return ["ssh"] + ssh_opts + [f"{username}@{host}"]


def retrieve_stored_config(host: str, username: str, ssh_key: Optional[str] = None) -> Optional[SetupConfig]:
    """Retrieve the stored configuration from the remote host."""
    ssh_cmd = build_ssh_command(host, username, ssh_key)
    remote_config_path = "/opt/infra_tools/state/setup.json"
    
    try:
        result = subprocess.run(
            ssh_cmd + ["cat", remote_config_path],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0 and result.stdout.strip():
            config_dict = json.loads(result.stdout)
            system_type = config_dict.get("system_type", "server_dev")
            return SetupConfig.from_dict(host, system_type, config_dict)
        
    except subprocess.TimeoutExpired:
        print(f"Timeout retrieving stored config from {host}", file=sys.stderr)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON in stored config: {e}", file=sys.stderr)
    except FileNotFoundError:
        # SSH command not found; this is a critical error
        print("SSH command not available", file=sys.stderr)
    
    return None


def reconstruct_remote_config(host: str, username: str, ssh_key: Optional[str] = None) -> Optional[tuple[SetupConfig, dict[str, Any]]]:
    """Run reconstruct_setup.py on the remote host to analyze configuration.
    
    Returns a tuple of (config, extras) or None on failure.
    """
    ssh_cmd = build_ssh_command(host, username, ssh_key)
    remote_script = "/opt/infra_tools/reconstruct_setup.py"
    
    try:
        # Check if infra_tools is installed on remote
        check_result = subprocess.run(
            ssh_cmd + ["test", "-f", remote_script],
            capture_output=True,
            timeout=10
        )
        
        if check_result.returncode != 0:
            print("Note: infra_tools not found on remote host. Installing...", file=sys.stderr)
            # Install infra_tools by running a minimal setup
            # This will install the tools to /opt/infra_tools
            from lib.setup_common import copy_project_files, create_tar_from_dir, REMOTE_INSTALL_DIR
            import tempfile
            
            build_dir = tempfile.mkdtemp(prefix="infra_recall_")
            try:
                copy_project_files(build_dir)
                tar_data = create_tar_from_dir(build_dir)
                
                install_cmd = f"mkdir -p {REMOTE_INSTALL_DIR} && cd {REMOTE_INSTALL_DIR} && tar xzf -"
                install_process = subprocess.Popen(
                    ssh_cmd + [install_cmd],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                install_process.communicate(input=tar_data, timeout=60)
                
                if install_process.returncode != 0:
                    print(f"Failed to install infra_tools on remote host", file=sys.stderr)
                    return None
            finally:
                import shutil
                if os.path.exists(build_dir):
                    shutil.rmtree(build_dir)
        
        # Run the reconstruct script from the installed location
        result = subprocess.run(
            ssh_cmd + ["python3", remote_script],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0 and result.stdout.strip():
            reconstructed = json.loads(result.stdout)
            
            config_dict: dict[str, Any] = {
                'username': username,
                'install_ruby': reconstructed.get('install_ruby', False),
                'install_go': reconstructed.get('install_go', False),
                'install_node': reconstructed.get('install_node', False),
                'enable_samba': reconstructed.get('enable_samba', False),
            }
            
            system_type = 'server_web' if reconstructed.get('deploy') else 'server_dev'
            config = SetupConfig.from_dict(host, system_type, config_dict)
            
            extras = {}
            for key in ['samba_shares', 'deploy', 'sync', 'scrub', 'mount_smb']:
                if key in reconstructed:
                    extras[key] = reconstructed[key]
            
            return config, extras
        else:
            print(f"Error running reconstruct script: {result.stderr}", file=sys.stderr)
            
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, json.JSONDecodeError) as e:
        print(f"Error reconstructing configuration: {e}", file=sys.stderr)
    
    return None


def print_config_info(config: SetupConfig, source: str) -> None:
    print("=" * 60)
    print(f"Configuration source: {source}")
    print("=" * 60)
    print()
    print(f"System type: {config.system_type}")
    print(f"Machine type: {config.machine_type}")
    print(f"Username: {config.username}")
    if config.friendly_name:
        print(f"Name: {config.friendly_name}")
    if config.tags and len(config.tags) > 0:
        print(f"Tags: {', '.join(config.tags)}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Recall setup configuration from a remote host")
    parser.add_argument("host", help="IP address or hostname of the remote host")
    parser.add_argument("username", nargs="?", default=None, 
                       help="Username (defaults to current user)")
    parser.add_argument("-k", "--key", dest="ssh_key", help="SSH private key path")
    
    args = parser.parse_args()
    
    username = args.username if args.username else os.getenv("USER", "root")
    
    print(f"Attempting to recall setup configuration for {username}@{args.host}...")
    print()
    
    stored_config = retrieve_stored_config(args.host, username, args.ssh_key)
    
    if stored_config:
        print_config_info(stored_config, "Stored configuration file")
        
        print("=" * 60)
        print("Suggested command:")
        print("=" * 60)
        print()
        cmd_parts = stored_config.to_setup_command(include_username=True)
        print(" \\\n  ".join(cmd_parts))
        print()
        
    else:
        print("⚠ Warning: No stored configuration found on remote host.")
        print("Attempting to reconstruct configuration by analyzing server state...")
        print()
        
        result = reconstruct_remote_config(args.host, username, args.ssh_key)
        
        if result:
            config, extras = result
            print_config_info(config, "Reconstructed from server analysis")
            
            print("=" * 60)
            print("Partial/guessed command (manual review required):")
            print("=" * 60)
            print()
            
            current_user = os.getenv("USER", "")
            include_username = (username != current_user)
            cmd_parts = config.to_setup_command(include_username=include_username)
            print(" \\\n  ".join(cmd_parts))
            
            if extras:
                notes = []
                
                if 'samba_shares' in extras:
                    shares = extras['samba_shares']
                    notes.append(f"  # Detected {len(shares)} Samba share(s): {', '.join(shares)}")
                    notes.append("  # Add --share flags manually")
                
                if 'deploy' in extras:
                    deployments = extras['deploy']
                    notes.append(f"  # Detected {len(deployments)} deployment(s)")
                    for name, _ in deployments:
                        notes.append(f"  # Add --deploy <domain> <git_url>  # for: {name}")
                
                if 'sync' in extras:
                    notes.append(f"  # Detected {len(extras['sync'])} sync operation(s)")
                    notes.append("  # Add --sync <source> <dest> <interval> flags")
                
                if 'scrub' in extras:
                    notes.append(f"  # Detected {len(extras['scrub'])} scrub operation(s)")
                    notes.append("  # Add --scrub <dir> <db_path> <redundancy> <freq> flags")
                
                if 'mount_smb' in extras:
                    mounts = extras['mount_smb']
                    mount_strs = [str(m) for m in mounts]
                    notes.append(f"  # Detected {len(mounts)} SMB mount(s): {', '.join(mount_strs)}")
                    notes.append("  # Add --mount-smb flags manually")
                
                if notes:
                    print()
                    print("# Additional features requiring manual configuration:")
                    for note in notes:
                        print(note)
            
            print()
            print("⚠ Note: This is a partial reconstruction. Please review and complete manually.")
            print()
        else:
            print("Error: Failed to retrieve or reconstruct configuration.", file=sys.stderr)
            return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
