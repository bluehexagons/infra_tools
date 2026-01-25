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
import tempfile
from typing import Optional, Any, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def build_ssh_command(host: str, username: str, ssh_key: Optional[str] = None) -> List[str]:
    """Build an SSH command for connecting to a remote host."""
    ssh_opts = [
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=30",
        "-o", "ServerAliveInterval=30",
    ]
    if ssh_key:
        ssh_opts.extend(["-i", ssh_key])
    
    return ["ssh"] + ssh_opts + [f"{username}@{host}"]


def retrieve_stored_config(host: str, username: str, ssh_key: Optional[str] = None) -> Optional[dict[str, Any]]:
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
            return json.loads(result.stdout)
        
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


def generate_command_from_config(config: dict[str, Any], host: str, username: str, system_type: str = "server_dev") -> str:
    """Generate a setup command from the configuration."""
    cmd_parts = [f"python3 setup_{system_type}.py", host]
    
    if username != os.getenv("USER", ""):
        cmd_parts.append(username)
    
    # Add development tools
    if config.get("ruby"):
        cmd_parts.append("--ruby")
    
    if config.get("go"):
        cmd_parts.append("--go")
    
    if config.get("node"):
        cmd_parts.append("--node")
    
    # Add Samba
    if config.get("samba"):
        cmd_parts.append("--samba")
        
        # Note: Share details need manual reconstruction
        shares = config.get("samba_shares", [])
        if shares:
            cmd_parts.append(f"  # Detected {len(shares)} Samba share(s): {', '.join(shares)}")
            cmd_parts.append("  # Add --share flags manually")
    
    # Add deployments
    deployments = config.get("deploy", [])
    if deployments:
        cmd_parts.append(f"  # Detected {len(deployments)} deployment(s)")
        for name, domain in deployments:
            cmd_parts.append(f"  # --deploy <domain> <git_url>  # for: {name}")
    
    # Add sync operations
    sync_ops = config.get("sync", [])
    if sync_ops:
        cmd_parts.append(f"  # Detected {len(sync_ops)} sync operation(s)")
        cmd_parts.append("  # Add --sync flags manually")
    
    # Add scrub operations
    scrub_ops = config.get("scrub", [])
    if scrub_ops:
        cmd_parts.append(f"  # Detected {len(scrub_ops)} scrub operation(s)")
        cmd_parts.append("  # Add --scrub flags manually")
    
    # Add SMB mounts
    smb_mounts = config.get("mount_smb", [])
    if smb_mounts:
        cmd_parts.append(f"  # Detected {len(smb_mounts)} SMB mount(s): {', '.join(smb_mounts)}")
        cmd_parts.append("  # Add --mount-smb flags manually")
    
    return " \\\n  ".join(cmd_parts)


def print_config_info(config: dict[str, Any], source: str) -> None:
    """Print the configuration information."""
    print("=" * 60)
    print(f"Configuration source: {source}")
    print("=" * 60)
    print()
    print("Detected configuration:")
    print(json.dumps(config, indent=2))
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
    
    # First, try to retrieve stored configuration
    stored_config = retrieve_stored_config(args.host, username, args.ssh_key)
    
    if stored_config:
        print_config_info(stored_config, "Stored configuration file")
        
        # Extract system_type if available
        system_type = stored_config.get("system_type", "server_dev")
        
        # Generate command from stored config
        print("=" * 60)
        print("Suggested command:")
        print("=" * 60)
        print()
        print(generate_command_from_config(stored_config, args.host, username, system_type))
        print()
        
    else:
        # No stored config found, try to reconstruct
        print("⚠ Warning: No stored configuration found on remote host.")
        print("Attempting to reconstruct configuration by analyzing server state...")
        print()
        
        reconstructed_config = reconstruct_remote_config(args.host, username, args.ssh_key)
        
        if reconstructed_config:
            print_config_info(reconstructed_config, "Reconstructed from server analysis")
            
            print("=" * 60)
            print("Partial/guessed command (manual review required):")
            print("=" * 60)
            print()
            print(generate_command_from_config(reconstructed_config, args.host, username))
            print()
            print("⚠ Note: This is a partial reconstruction. Please review and complete manually.")
            print()
        else:
            print("Error: Failed to retrieve or reconstruct configuration.", file=sys.stderr)
            return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
