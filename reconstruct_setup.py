#!/usr/bin/env python3
"""Reconstruct setup configuration by analyzing the server state."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.config import SetupConfig


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
    return os.path.isdir(path)


def check_file_exists(path: str) -> bool:
    return os.path.isfile(path)


def detect_ruby() -> bool:
    home_dir = os.path.expanduser("~")
    rbenv_path = os.path.join(home_dir, ".rbenv")
    return check_directory_exists(rbenv_path) or check_command_exists("rbenv")


def detect_go() -> bool:
    return check_command_exists("go")


def detect_node() -> bool:
    home_dir = os.path.expanduser("~")
    nvm_path = os.path.join(home_dir, ".nvm")
    return (
        check_directory_exists(nvm_path)
        or check_command_exists("nvm")
        or check_directory_exists("/opt/nvm")
        or check_file_exists("/etc/profile.d/nvm.sh")
    )


def detect_deployments() -> list[tuple[str, str]]:
    deployments: list[tuple[str, str]] = []
    deploy_base = "/opt/deployments"
    
    if not check_directory_exists(deploy_base):
        return deployments
    
    try:
        for item in os.listdir(deploy_base):
            item_path = os.path.join(deploy_base, item)
            if os.path.isdir(item_path):
                deployments.append((item, "unknown"))
    except (OSError, PermissionError):
        # Failed to read deployments directory; return empty list
        pass
    
    return deployments


def detect_samba() -> bool:
    return (check_service_exists("smbd") or 
            check_service_exists("nmbd") or
            check_file_exists("/etc/samba/smb.conf"))


def detect_samba_shares() -> list[str]:
    shares: list[str] = []
    smb_conf = "/etc/samba/smb.conf"
    
    if not check_file_exists(smb_conf):
        return shares
    
    try:
        with open(smb_conf, 'r') as f:
            content = f.read()
            share_pattern = re.compile(r'^\[([^\]]+)\]', re.MULTILINE)
            matches = share_pattern.findall(content)
            for match in matches:
                if match not in ['global', 'homes', 'printers']:
                    shares.append(match)
    except (OSError, PermissionError):
        # Failed to read or parse smb.conf; return empty list
        pass
    
    return shares


def detect_sync_operations() -> list[str]:
    operations: list[str] = []
    
    try:
        result = subprocess.run(
            ["systemctl", "list-timers", "--all", "--no-pager"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        for line in result.stdout.split('\n'):
            if 'sync' in line.lower() and '.timer' in line:
                operations.append(line.strip())
    except (subprocess.SubprocessError, OSError):
        # Failed to query systemd timers; return empty list
        pass
    
    return operations


def detect_scrub_operations() -> list[str]:
    operations: list[str] = []
    
    try:
        result = subprocess.run(
            ["systemctl", "list-timers", "--all", "--no-pager"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        for line in result.stdout.split('\n'):
            if 'scrub' in line.lower() and '.timer' in line:
                operations.append(line.strip())
    except (subprocess.SubprocessError, OSError):
        # Failed to query systemd timers; return empty list
        pass
    
    return operations


def detect_smb_mounts() -> list[str]:
    mounts: list[str] = []
    
    if check_file_exists("/etc/fstab"):
        try:
            with open("/etc/fstab", 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        if 'cifs' in line or 'smb' in line:
                            mounts.append(line.split()[1] if len(line.split()) > 1 else line)
        except (OSError, PermissionError):
            # Failed to read /etc/fstab; SMB mounts can still be discovered via systemd
            pass
    
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
    except (subprocess.SubprocessError, OSError):
        # Failed to query systemd mounts; return what we found from fstab
        pass
    
    return mounts


def reconstruct_configuration(host: str = "localhost", username: str = "root") -> tuple[SetupConfig, dict[str, Any]]:
    """Reconstruct setup configuration by analyzing the server.
    
    Returns a tuple of (config, extras) where extras contains data
    that can't be fully reconstructed (shares, deployments, etc.).
    """
    config_dict: dict[str, Any] = {
        'username': username,
        'install_ruby': detect_ruby(),
        'install_go': detect_go(),
        'install_node': detect_node(),
        'enable_samba': detect_samba(),
    }
    
    deployments = detect_deployments()
    system_type = 'server_web' if deployments else 'server_dev'
    
    extras: dict[str, Any] = {}
    if detect_samba():
        shares = detect_samba_shares()
        if shares:
            extras['samba_shares'] = shares
    
    if deployments:
        extras['deploy'] = deployments
    
    sync_ops = detect_sync_operations()
    if sync_ops:
        extras['sync'] = sync_ops
    
    scrub_ops = detect_scrub_operations()
    if scrub_ops:
        extras['scrub'] = scrub_ops
    
    smb_mounts = detect_smb_mounts()
    if smb_mounts:
        extras['mount_smb'] = smb_mounts
    
    config = SetupConfig.from_dict(host, system_type, config_dict)
    
    return config, extras


def main() -> int:
    try:
        config, extras = reconstruct_configuration()
        
        output = {
            'install_ruby': config.install_ruby,
            'install_go': config.install_go,
            'install_node': config.install_node,
            'enable_samba': config.enable_samba,
        }
        
        output.update(extras)
        
        print(json.dumps(output, indent=2))
        return 0
    except Exception as e:
        print(f"Error reconstructing configuration: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
