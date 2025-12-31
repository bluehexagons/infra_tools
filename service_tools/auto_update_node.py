#!/usr/bin/env python3
"""
Auto-update Node.js

This script updates Node.js to the latest LTS version via nvm.
It also updates global npm and pnpm packages.
"""

import os
import sys
import subprocess
import syslog


NVM_DIR = "/opt/nvm"


def run_nvm_command(cmd: str) -> subprocess.CompletedProcess:
    """Run a command with nvm environment loaded."""
    full_cmd = f'export NVM_DIR="{NVM_DIR}" && [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" && {cmd}'
    
    result = subprocess.run(
        full_cmd,
        shell=True,
        executable="/bin/bash",
        capture_output=True,
        text=True
    )
    return result


def get_current_lts_version() -> str:
    """Get the latest LTS version available."""
    result = run_nvm_command("nvm version-remote --lts")
    if result.returncode == 0:
        return result.stdout.strip()
    return ""


def get_current_version() -> str:
    """Get the currently installed default version."""
    result = run_nvm_command("nvm version default")
    if result.returncode == 0:
        return result.stdout.strip()
    return ""


def install_lts_version():
    """Install the latest LTS version."""
    result = run_nvm_command("nvm install --lts")
    if result.returncode != 0:
        print(f"✗ Failed to install LTS version: {result.stderr}")
        syslog.syslog(syslog.LOG_ERR, f"auto-update-node: Failed to install LTS: {result.stderr}")
        return False
    return True


def update_global_packages():
    """Update global npm and pnpm packages."""
    result = run_nvm_command("npm install -g npm@latest")
    if result.returncode != 0:
        print(f"⚠ Warning: Failed to update npm: {result.stderr}")
    
    result = run_nvm_command("npm install -g pnpm")
    if result.returncode != 0:
        print(f"⚠ Warning: Failed to update pnpm: {result.stderr}")


def update_symlinks():
    """Update symlinks in /usr/local/bin."""
    result = run_nvm_command("which node")
    if result.returncode != 0:
        return
    
    node_path = result.stdout.strip()
    node_dir = os.path.dirname(node_path)
    
    for tool in ["node", "npm", "npx", "pnpm"]:
        tool_path = os.path.join(node_dir, tool)
        link_path = f"/usr/local/bin/{tool}"
        
        if os.path.exists(tool_path):
            try:
                if os.path.islink(link_path):
                    os.remove(link_path)
                os.symlink(tool_path, link_path)
            except Exception as e:
                print(f"⚠ Warning: Failed to create symlink for {tool}: {e}")


def fix_permissions():
    """Fix permissions on nvm directory."""
    try:
        subprocess.run(
            ["chmod", "-R", "a+rX", NVM_DIR],
            check=True,
            capture_output=True
        )
    except subprocess.CalledProcessError as e:
        print(f"⚠ Warning: Failed to fix permissions: {e}")


def main():
    """Main function to update Node.js."""
    if not os.path.exists(NVM_DIR):
        print(f"✗ nvm not found at {NVM_DIR}")
        return 1
    
    current_lts = get_current_lts_version()
    current_version = get_current_version()
    
    if not current_lts:
        print("✗ Failed to get latest LTS version")
        return 1
    
    if not current_version:
        print("✗ Failed to get current version")
        return 1
    
    if current_version == current_lts:
        print(f"Node.js already at latest LTS version: {current_lts}")
        return 0
    
    print(f"Updating Node.js from {current_version} to {current_lts}")
    syslog.syslog(syslog.LOG_INFO, f"auto-update-node: Updating Node.js from {current_version} to {current_lts}")
    
    if not install_lts_version():
        return 1
    
    update_global_packages()
    
    update_symlinks()
    
    fix_permissions()
    
    print(f"Node.js updated successfully to {current_lts}")
    syslog.syslog(syslog.LOG_INFO, f"auto-update-node: Successfully updated Node.js to {current_lts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
