#!/usr/bin/env python3
"""
Auto-update Ruby

This script updates Ruby to the latest stable version via rbenv.
It also updates the bundler gem.
"""

import os
import sys
import subprocess
import syslog
import re


def run_rbenv_command(cmd: str) -> subprocess.CompletedProcess:
    """Run a command with rbenv environment loaded."""
    full_cmd = f'export PATH="$HOME/.rbenv/bin:$PATH" && eval "$(rbenv init -)" && {cmd}'
    
    result = subprocess.run(
        full_cmd,
        shell=True,
        executable="/bin/bash",
        capture_output=True,
        text=True
    )
    return result


def update_ruby_build():
    """Update ruby-build to get latest Ruby definitions."""
    try:
        result = subprocess.run(
            ["git", "-C", os.path.expanduser("~/.rbenv/plugins/ruby-build"), "pull"],
            capture_output=True,
            text=True,
            check=True
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"⚠ Warning: Failed to update ruby-build: {e}")
        return False


def get_latest_stable_ruby() -> str:
    """Get the latest stable Ruby version (excluding preview/rc/dev)."""
    result = run_rbenv_command("rbenv install -l")
    if result.returncode != 0:
        return ""
    
    # Filter for stable versions (X.Y.Z format only, no suffixes)
    versions = []
    for line in result.stdout.split('\n'):
        line = line.strip()
        # Match versions like "3.3.0" but not "3.3.0-preview1"
        if re.match(r'^\d+\.\d+\.\d+$', line):
            versions.append(line)
    
    if versions:
        return versions[-1]  # Return the last (latest) version
    return ""


def get_current_ruby_version() -> str:
    """Get the currently installed global Ruby version."""
    result = run_rbenv_command("rbenv global")
    if result.returncode == 0:
        return result.stdout.strip()
    return ""


def install_ruby_version(version: str) -> bool:
    """Install a specific Ruby version."""
    result = run_rbenv_command(f"rbenv install -s {version}")
    if result.returncode != 0:
        print(f"✗ Failed to install Ruby {version}: {result.stderr}")
        syslog.syslog(syslog.LOG_ERR, f"auto-update-ruby: Failed to install Ruby {version}: {result.stderr}")
        return False
    return True


def set_global_ruby(version: str) -> bool:
    """Set the global Ruby version."""
    result = run_rbenv_command(f"rbenv global {version}")
    if result.returncode != 0:
        print(f"✗ Failed to set global Ruby to {version}: {result.stderr}")
        return False
    return True


def update_bundler():
    """Update the bundler gem."""
    result = run_rbenv_command("gem install bundler")
    if result.returncode != 0:
        print(f"⚠ Warning: Failed to update bundler: {result.stderr}")


def main():
    """Main function to update Ruby."""
    # Check if rbenv is installed
    rbenv_dir = os.path.expanduser("~/.rbenv")
    if not os.path.exists(rbenv_dir):
        print(f"✗ rbenv not found at {rbenv_dir}")
        return 1
    
    # Update ruby-build
    update_ruby_build()
    
    # Get latest stable version
    latest_ruby = get_latest_stable_ruby()
    if not latest_ruby:
        print("✗ Failed to get latest stable Ruby version")
        return 1
    
    # Get current version
    current_version = get_current_ruby_version()
    if not current_version:
        print("✗ Failed to get current Ruby version")
        return 1
    
    # Check if update is needed
    if current_version == latest_ruby:
        print(f"Ruby already at latest stable version: {latest_ruby}")
        return 0
    
    # Perform update
    print(f"Updating Ruby from {current_version} to {latest_ruby}")
    syslog.syslog(syslog.LOG_INFO, f"auto-update-ruby: Updating Ruby from {current_version} to {latest_ruby}")
    
    # Install new version
    if not install_ruby_version(latest_ruby):
        return 1
    
    # Set as global version
    if not set_global_ruby(latest_ruby):
        return 1
    
    # Update bundler
    update_bundler()
    
    print(f"Ruby updated successfully to {latest_ruby}")
    syslog.syslog(syslog.LOG_INFO, f"auto-update-ruby: Successfully updated Ruby to {latest_ruby}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
