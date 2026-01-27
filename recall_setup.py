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
        # Try to read the stored configuration
        result = subprocess.run(
            ssh_cmd + ["cat", remote_config_path],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0 and result.stdout.strip():
            config_dict = json.loads(result.stdout)
            system_type = config_dict.get("system_type", "server_dev")
            # Update host to the current host (in case it changed)
            return SetupConfig.from_dict(host, system_type, config_dict)
        
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        pass
    
    return None


def reconstruct_remote_config(host: str, username: str, ssh_key: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Run reconstruct_setup.py on the remote host to analyze configuration."""
    ssh_cmd = build_ssh_command(host, username, ssh_key)
    
    # First, upload the reconstruct_setup.py script
    local_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reconstruct_setup.py")
    remote_script = "/tmp/reconstruct_setup.py"
    
    try:
        # Upload the script
        scp_cmd = ["scp"]
        if ssh_key:
            scp_cmd.extend(["-i", ssh_key])
        scp_cmd.extend([
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ConnectTimeout=30",
        ])
        scp_cmd.extend([local_script, f"{username}@{host}:{remote_script}"])
        
        subprocess.run(scp_cmd, capture_output=True, check=True, timeout=30)
        
        # Run the script on the remote host
        result = subprocess.run(
            ssh_cmd + ["python3", remote_script],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        # Clean up the remote script
        subprocess.run(
            ssh_cmd + ["rm", "-f", remote_script],
            capture_output=True,
            timeout=10
        )
        
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
        else:
            print(f"Error running reconstruct script: {result.stderr}", file=sys.stderr)
            
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, json.JSONDecodeError) as e:
        print(f"Error reconstructing configuration: {e}", file=sys.stderr)
    
    return None


def create_partial_config_from_reconstruction(
    reconstructed: dict[str, Any],
    host: str,
    username: str
) -> SetupConfig:
    """Create a partial SetupConfig from reconstructed data.
    
    Converts the simple dict from reconstruction into a SetupConfig object
    so we can use the standard to_setup_command() method.
    """
    # Map reconstructed flags to config fields
    config_dict: dict[str, Any] = {
        'username': username,
        'install_ruby': reconstructed.get('ruby', False),
        'install_go': reconstructed.get('go', False),
        'install_node': reconstructed.get('node', False),
        'enable_samba': reconstructed.get('samba', False),
    }
    
    # Try to infer system_type from detected features
    # Default to server_dev, but use server_web if deployments are detected
    system_type = 'server_dev'
    if reconstructed.get('deploy'):
        system_type = 'server_web'
    
    return SetupConfig.from_dict(host, system_type, config_dict)


def print_config_info(config: SetupConfig, source: str) -> None:
    """Print stored configuration information."""
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


def print_reconstructed_info(config_dict: dict[str, Any], source: str) -> None:
    """Print reconstructed configuration information."""
    print("=" * 60)
    print(f"Configuration source: {source}")
    print("=" * 60)
    print()
    print("Detected configuration:")
    print(json.dumps(config_dict, indent=2))
    print()


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Recall setup configuration from a remote host")
    parser.add_argument("host", help="IP address or hostname of the remote host")
    parser.add_argument("username", nargs="?", default=None, 
                       help="Username (defaults to current user)")
    parser.add_argument("-k", "--key", dest="ssh_key", help="SSH private key path")
    
    args = parser.parse_args()
    
    # Get username
    username = args.username if args.username else os.getenv("USER", "root")
    
    print(f"Attempting to recall setup configuration for {username}@{args.host}...")
    print()
    
    # First, try to retrieve stored configuration from remote host
    stored_config = retrieve_stored_config(args.host, username, args.ssh_key)
    
    if stored_config:
        print_config_info(stored_config, "Stored configuration file")
        
        # Generate command from stored config using SetupConfig's method
        print("=" * 60)
        print("Suggested command:")
        print("=" * 60)
        print()
        cmd_parts = stored_config.to_setup_command(include_username=True)
        print(" \\\n  ".join(cmd_parts))
        print()
        
    else:
        # No stored config found, try to reconstruct
        print("⚠ Warning: No stored configuration found on remote host.")
        print("Attempting to reconstruct configuration by analyzing server state...")
        print()
        
        reconstructed_data = reconstruct_remote_config(args.host, username, args.ssh_key)
        
        if reconstructed_data:
            print_reconstructed_info(reconstructed_data, "Reconstructed from server analysis")
            
            # Create a partial SetupConfig from reconstructed data
            partial_config = create_partial_config_from_reconstruction(
                reconstructed_data, args.host, username
            )
            
            print("=" * 60)
            print("Partial/guessed command (manual review required):")
            print("=" * 60)
            print()
            
            # Use the standard to_setup_command() method
            # Only include username if it differs from current user
            current_user = os.getenv("USER", "")
            include_username = (username != current_user)
            cmd_parts = partial_config.to_setup_command(include_username=include_username)
            print(" \\\n  ".join(cmd_parts))
            
            # Add notes about complex features that need manual configuration
            notes = []
            if reconstructed_data.get('samba_shares'):
                shares = reconstructed_data['samba_shares']
                notes.append(f"  # Detected {len(shares)} Samba share(s): {', '.join(shares)}")
                notes.append("  # Add --share flags manually with access type, paths, and credentials")
            
            if reconstructed_data.get('deploy'):
                deployments = reconstructed_data['deploy']
                notes.append(f"  # Detected {len(deployments)} deployment(s)")
                for name, _ in deployments:
                    notes.append(f"  # Add --deploy <domain> <git_url>  # for: {name}")
            
            if reconstructed_data.get('sync'):
                sync_ops = reconstructed_data['sync']
                notes.append(f"  # Detected {len(sync_ops)} sync operation(s)")
                notes.append("  # Add --sync <source> <dest> <interval> flags manually")
            
            if reconstructed_data.get('scrub'):
                scrub_ops = reconstructed_data['scrub']
                notes.append(f"  # Detected {len(scrub_ops)} scrub operation(s)")
                notes.append("  # Add --scrub <dir> <db_path> <redundancy> <freq> flags manually")
            
            if reconstructed_data.get('mount_smb'):
                mounts = reconstructed_data['mount_smb']
                mount_strs = [str(m) for m in mounts]
                notes.append(f"  # Detected {len(mounts)} SMB mount(s): {', '.join(mount_strs)}")
                notes.append("  # Add --mount-smb flags manually with credentials")
            
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
