#!/usr/bin/env python3
"""
Auto-update Ruby

This script updates Ruby to the latest stable version via rbenv.
It also updates the bundler gem.

Logs to: /var/log/infra_tools/web/auto_update_ruby.log
"""

from __future__ import annotations

import os
import sys
import subprocess
import re

# Add lib directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../..'))

from lib.logging_utils import get_service_logger

# Initialize centralized logger
logger = get_service_logger('auto_update_ruby', 'web', use_syslog=True)


def run_rbenv_command(cmd: str) -> subprocess.CompletedProcess[str]:
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
        subprocess.run(
            ["git", "-C", os.path.expanduser("~/.rbenv/plugins/ruby-build"), "pull"],
            capture_output=True,
            text=True,
            check=True
        )
        logger.info("✓ Successfully updated ruby-build")
        return True
    except subprocess.CalledProcessError as e:
        logger.warning(f"⚠ Failed to update ruby-build: {e}")
        return False


def get_latest_stable_ruby() -> str:
    """Get the latest stable Ruby version (excluding preview/rc/dev)."""
    result = run_rbenv_command("rbenv install -l")
    if result.returncode != 0:
        return ""
    
    versions: list[str] = []
    for line in result.stdout.split('\n'):
        line = line.strip()
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
        logger.error(f"✗ Failed to install Ruby {version}: {result.stderr}")
        return False
    logger.info(f"✓ Successfully installed Ruby {version}")
    return True


def set_global_ruby(version: str) -> bool:
    """Set the global Ruby version."""
    result = run_rbenv_command(f"rbenv global {version}")
    if result.returncode != 0:
        logger.error(f"✗ Failed to set global Ruby to {version}: {result.stderr}")
        return False
    logger.info(f"✓ Successfully set global Ruby to {version}")
    return True


def update_bundler():
    """Update the bundler gem."""
    result = run_rbenv_command("gem install bundler")
    if result.returncode != 0:
        logger.warning(f"⚠ Failed to update bundler: {result.stderr}")
    else:
        logger.info("✓ Successfully updated bundler")


def main():
    """Main function to update Ruby."""
    logger.info("Starting Ruby update check")
    
    # Load notification configs
    notification_configs = []
    try:
        from lib.machine_state import load_setup_config
        from lib.notifications import parse_notification_args
        setup_config = load_setup_config()
        if setup_config and 'notify_specs' in setup_config:
            notification_configs = parse_notification_args(setup_config['notify_specs'])
    except Exception as e:
        logger.warning(f"Failed to load notification configs: {e}")
    
    rbenv_dir = os.path.expanduser("~/.rbenv")
    if not os.path.exists(rbenv_dir):
        logger.error(f"✗ rbenv not found at {rbenv_dir}")
        if notification_configs:
            try:
                from lib.notifications import send_notification
                send_notification(
                    notification_configs,
                    subject="Error: Ruby update failed",
                    job="auto_update_ruby",
                    status="error",
                    message=f"rbenv not found at {rbenv_dir}",
                    logger=logger
                )
            except Exception:
                pass
        return 1
    
    update_ruby_build()
    
    latest_ruby = get_latest_stable_ruby()
    if not latest_ruby:
        logger.error("✗ Failed to get latest stable Ruby version")
        if notification_configs:
            try:
                from lib.notifications import send_notification
                send_notification(
                    notification_configs,
                    subject="Error: Ruby update failed",
                    job="auto_update_ruby",
                    status="error",
                    message="Failed to get latest stable Ruby version",
                    logger=logger
                )
            except Exception:
                pass
        return 1
    
    current_version = get_current_ruby_version()
    if not current_version:
        logger.error("✗ Failed to get current Ruby version")
        return 1
    
    if current_version == latest_ruby:
        logger.info(f"Ruby already at latest stable version: {latest_ruby}")
        return 0
    
    logger.info(f"Updating Ruby from {current_version} to {latest_ruby}")
    
    if not install_ruby_version(latest_ruby):
        logger.error("✗ Ruby installation failed")
        if notification_configs:
            try:
                from lib.notifications import send_notification
                send_notification(
                    notification_configs,
                    subject="Error: Ruby update failed",
                    job="auto_update_ruby",
                    status="error",
                    message=f"Failed to install Ruby {latest_ruby}",
                    logger=logger
                )
            except Exception:
                pass
        return 1
    
    if not set_global_ruby(latest_ruby):
        logger.error("✗ Failed to set global Ruby version")
        return 1
    
    update_bundler()
    
    logger.info(f"✓ Ruby updated successfully to {latest_ruby}")
    
    if notification_configs:
        try:
            from lib.notifications import send_notification
            send_notification(
                notification_configs,
                subject="Success: Ruby updated",
                job="auto_update_ruby",
                status="good",
                message=f"Updated from {current_version} to {latest_ruby}",
                logger=logger
            )
        except Exception:
            pass
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
