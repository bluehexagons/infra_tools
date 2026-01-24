#!/usr/bin/env python3
"""
Auto-update Node.js

This script updates Node.js to the latest LTS version via nvm.
It also updates global npm and pnpm packages.

Logs to: /var/log/infra_tools/web/auto_update_node.log
"""

from __future__ import annotations

import os
import sys
import subprocess

# Add lib directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../..'))

from lib.logging_utils import get_service_logger

NVM_DIR = "/opt/nvm"

# Initialize centralized logger
logger = get_service_logger('auto_update_node', 'web', use_syslog=True)


def run_nvm_command(cmd: str) -> subprocess.CompletedProcess[str]:
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
        error_msg = f"Failed to install LTS version: {result.stderr}"
        print(f"✗ {error_msg}")
        logger.error(error_msg)
        return False
    logger.info("Successfully installed LTS version")
    return True


def update_global_packages():
    """Update global npm and pnpm packages."""
    result = run_nvm_command("npm install -g npm@latest")
    if result.returncode != 0:
        warning_msg = f"Failed to update npm: {result.stderr}"
        print(f"⚠ Warning: {warning_msg}")
        logger.warning(warning_msg)
    else:
        logger.info("Successfully updated npm")
    
    result = run_nvm_command("npm install -g pnpm")
    if result.returncode != 0:
        warning_msg = f"Failed to update pnpm: {result.stderr}"
        print(f"⚠ Warning: {warning_msg}")
        logger.warning(warning_msg)
    else:
        logger.info("Successfully updated pnpm")


def update_symlinks():
    """Update symlinks in /usr/local/bin."""
    result = run_nvm_command("which node")
    if result.returncode != 0:
        logger.warning("Failed to locate node binary")
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
                logger.info(f"Updated symlink for {tool}")
            except Exception as e:
                warning_msg = f"Failed to create symlink for {tool}: {e}"
                print(f"⚠ Warning: {warning_msg}")
                logger.warning(warning_msg)


def fix_permissions():
    """Fix permissions on nvm directory."""
    try:
        subprocess.run(
            ["chmod", "-R", "a+rX", NVM_DIR],
            check=True,
            capture_output=True
        )
        logger.info("Successfully fixed permissions on nvm directory")
    except subprocess.CalledProcessError as e:
        warning_msg = f"Failed to fix permissions: {e}"
        print(f"⚠ Warning: {warning_msg}")
        logger.warning(warning_msg)


def main():
    """Main function to update Node.js."""
    logger.info("Starting Node.js update check")
    
    if not os.path.exists(NVM_DIR):
        error_msg = f"nvm not found at {NVM_DIR}"
        print(f"✗ {error_msg}")
        logger.error(error_msg)
        return 1
    
    current_lts = get_current_lts_version()
    current_version = get_current_version()
    
    if not current_lts:
        error_msg = "Failed to get latest LTS version"
        print(f"✗ {error_msg}")
        logger.error(error_msg)
        return 1
    
    if not current_version:
        error_msg = "Failed to get current version"
        print(f"✗ {error_msg}")
        logger.error(error_msg)
        return 1
    
    if current_version == current_lts:
        info_msg = f"Node.js already at latest LTS version: {current_lts}"
        print(info_msg)
        logger.info(info_msg)
        return 0
    
    update_msg = f"Updating Node.js from {current_version} to {current_lts}"
    print(update_msg)
    logger.info(update_msg)
    
    if not install_lts_version():
        logger.error("Node.js update failed")
        return 1
    
    update_global_packages()
    
    update_symlinks()
    
    fix_permissions()
    
    success_msg = f"Node.js updated successfully to {current_lts}"
    print(success_msg)
    logger.info(success_msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
