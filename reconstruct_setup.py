#!/usr/bin/env python3
"""Reconstruct setup configuration by analyzing the server state.

This script analyzes the current server to detect installed components
and generates a partial configuration that can be used to recall the
original setup command.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any


def check_command_exists(command: str) -> bool:
    """Check if a command exists in PATH."""
    try:
        subprocess.run(
            ["which", command],
            capture_output=True,
            check=True,
            timeout=5
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return False


def check_service_exists(service: str) -> bool:
    """Check if a systemd service exists."""
    try:
        result = subprocess.run(
            ["systemctl", "list-unit-files", f"{service}.service"],
            capture_output=True,
            text=True,
            timeout=5
        )
        return service in result.stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return False


def check_directory_exists(path: str) -> bool:
    """Check if a directory exists."""
    return os.path.isdir(path)


def check_file_exists(path: str) -> bool:
    """Check if a file exists."""
    return os.path.isfile(path)


def detect_ruby() -> bool:
    """Detect if Ruby is installed via rbenv."""
    home_dir = os.path.expanduser("~")
    rbenv_path = os.path.join(home_dir, ".rbenv")
    return check_directory_exists(rbenv_path) or check_command_exists("rbenv")


def detect_go() -> bool:
    """Detect if Go is installed."""
    return check_command_exists("go")


def detect_node() -> bool:
    """Detect if Node.js is installed via nvm."""
    home_dir = os.path.expanduser("~")
    nvm_path = os.path.join(home_dir, ".nvm")
    return check_directory_exists(nvm_path) or check_command_exists("nvm")


def detect_deployments() -> list[tuple[str, str]]:
    """Detect deployed applications."""
    deployments: list[tuple[str, str]] = []
    deploy_base = "/opt/deployments"
    
    if not check_directory_exists(deploy_base):
        return deployments
    
    try:
        for item in os.listdir(deploy_base):
            item_path = os.path.join(deploy_base, item)
            if os.path.isdir(item_path):
                # Try to detect the domain from nginx config or deployment metadata
                # For now, just note that a deployment exists
                deployments.append((item, "unknown"))
    except Exception:
        pass
    
    return deployments


def detect_samba() -> bool:
    """Detect if Samba is installed and configured."""
    return (check_service_exists("smbd") or 
            check_service_exists("nmbd") or
            check_file_exists("/etc/samba/smb.conf"))


def detect_samba_shares() -> list[str]:
    """Detect configured Samba shares."""
    shares: list[str] = []
    smb_conf = "/etc/samba/smb.conf"
    
    if not check_file_exists(smb_conf):
        return shares
    
    try:
        with open(smb_conf, 'r') as f:
            content = f.read()
            # Simple parsing - look for share sections
            import re
            share_pattern = re.compile(r'^\[([^\]]+)\]', re.MULTILINE)
            matches = share_pattern.findall(content)
            for match in matches:
                if match not in ['global', 'homes', 'printers']:
                    shares.append(match)
    except Exception:
        pass
    
    return shares


def detect_sync_operations() -> list[str]:
    """Detect rsync-based sync operations from systemd timers."""
    operations: list[str] = []
    
    try:
        result = subprocess.run(
            ["systemctl", "list-timers", "--all", "--no-pager"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        # Look for sync-related timers
        for line in result.stdout.split('\n'):
            if 'sync' in line.lower() and '.timer' in line:
                operations.append(line.strip())
    except Exception:
        pass
    
    return operations


def detect_scrub_operations() -> list[str]:
    """Detect par2-based scrub operations from systemd timers."""
    operations: list[str] = []
    
    try:
        result = subprocess.run(
            ["systemctl", "list-timers", "--all", "--no-pager"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        # Look for scrub-related timers
        for line in result.stdout.split('\n'):
            if 'scrub' in line.lower() and '.timer' in line:
                operations.append(line.strip())
    except Exception:
        pass
    
    return operations


def detect_smb_mounts() -> list[str]:
    """Detect SMB mounts from fstab and systemd mounts."""
    mounts: list[str] = []
    
    # Check /etc/fstab
    if check_file_exists("/etc/fstab"):
        try:
            with open("/etc/fstab", 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        if 'cifs' in line or 'smb' in line:
                            mounts.append(line.split()[1] if len(line.split()) > 1 else line)
        except Exception:
            pass
    
    # Check systemd mounts
    try:
        result = subprocess.run(
            ["systemctl", "list-units", "--type=mount", "--all", "--no-pager"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        for line in result.stdout.split('\n'):
            if 'mnt' in line and '.mount' in line:
                mounts.append(line.split()[0])
    except Exception:
        pass
    
    return mounts


def reconstruct_configuration() -> dict[str, Any]:
    """Reconstruct the setup configuration by analyzing the server."""
    config: dict[str, Any] = {}
    
    # Detect development tools
    if detect_ruby():
        config['ruby'] = True
    
    if detect_go():
        config['go'] = True
    
    if detect_node():
        config['node'] = True
    
    # Detect deployments
    deployments = detect_deployments()
    if deployments:
        config['deploy'] = deployments
    
    # Detect Samba
    if detect_samba():
        config['samba'] = True
        shares = detect_samba_shares()
        if shares:
            config['samba_shares'] = shares
    
    # Detect sync operations
    sync_ops = detect_sync_operations()
    if sync_ops:
        config['sync'] = sync_ops
    
    # Detect scrub operations
    scrub_ops = detect_scrub_operations()
    if scrub_ops:
        config['scrub'] = scrub_ops
    
    # Detect SMB mounts
    smb_mounts = detect_smb_mounts()
    if smb_mounts:
        config['mount_smb'] = smb_mounts
    
    return config


def main() -> int:
    """Main entry point."""
    try:
        config = reconstruct_configuration()
        print(json.dumps(config, indent=2))
        return 0
    except Exception as e:
        print(f"Error reconstructing configuration: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
