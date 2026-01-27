#!/usr/bin/env python3
"""Rsync wrapper with notification support for sync operations."""

from __future__ import annotations

import sys
import os
import subprocess
from datetime import datetime

# Add lib directory to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../..'))

from lib.logging_utils import get_service_logger

# Conversion constants
BYTES_TO_MB = 1024 * 1024


def run_rsync_with_notifications(source: str, destination: str) -> int:
    """Run rsync and send notifications on completion or failure.
    
    Args:
        source: Source directory
        destination: Destination directory
        
    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    logger = get_service_logger('sync', 'operations', use_syslog=False, console_output=True)
    
    # Load notification configs from machine state
    notification_configs = []
    try:
        from lib.machine_state import load_setup_config
        from lib.notifications import parse_notification_args
        setup_config = load_setup_config()
        if setup_config and 'notify_specs' in setup_config:
            notification_configs = parse_notification_args(setup_config['notify_specs'])
    except Exception as e:
        logger.warning(f"Failed to load notification configs: {e}")
    
    logger.info(f"Starting sync: {source} -> {destination}")
    start_time = datetime.now()
    
    try:
        # Run rsync
        result = subprocess.run(
            [
                '/usr/bin/rsync',
                '-av',
                '--delete',
                '--delete-delay',
                '--partial',
                '--exclude=.git',
                '--stats',
                f'{source}/',
                f'{destination}/'
            ],
            capture_output=True,
            text=True,
            check=True
        )
        
        duration = (datetime.now() - start_time).total_seconds()
        logger.info(f"✓ Sync completed in {duration:.1f}s")
        
        # Parse rsync stats for notification
        stats_lines = result.stdout.split('\n')
        files_transferred = 0
        total_size = 0
        
        for line in stats_lines:
            if 'Number of files transferred:' in line:
                try:
                    files_transferred = int(line.split(':')[1].strip())
                except (IndexError, ValueError):
                    pass
            elif 'Total file size:' in line:
                try:
                    size_str = line.split(':')[1].strip().split()[0].replace(',', '')
                    total_size = int(size_str)
                except (IndexError, ValueError):
                    pass
        
        # Send success notification
        if notification_configs:
            try:
                from lib.notifications import send_notification
                message = f"Synced {files_transferred} files"
                if total_size > 0:
                    message += f" ({total_size // BYTES_TO_MB} MB)"
                message += f" in {duration:.1f}s"
                
                details = f"""Sync Summary:
Source: {source}
Destination: {destination}
Files transferred: {files_transferred}
Duration: {duration:.1f}s

Output:
{result.stdout}
"""
                
                send_notification(
                    notification_configs,
                    subject="Success: Sync completed",
                    job="sync",
                    status="good",
                    message=message,
                    details=details,
                    logger=logger
                )
            except Exception as e:
                logger.error(f"Failed to send notification: {e}")
        
        return 0
        
    except subprocess.CalledProcessError as e:
        duration = (datetime.now() - start_time).total_seconds()
        logger.error(f"✗ Sync failed after {duration:.1f}s")
        logger.error(f"Error: {e.stderr or e.stdout}")
        
        # Send error notification
        if notification_configs:
            try:
                from lib.notifications import send_notification
                error_msg = e.stderr or e.stdout or str(e)
                send_notification(
                    notification_configs,
                    subject="Error: Sync failed",
                    job="sync",
                    status="error",
                    message=f"Sync failed: {source} -> {destination}",
                    details=f"Error:\n{error_msg}",
                    logger=logger
                )
            except Exception as notify_error:
                logger.error(f"Failed to send error notification: {notify_error}")
        
        return e.returncode
    
    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds()
        logger.error(f"✗ Sync failed with unexpected error after {duration:.1f}s: {e}")
        
        # Send error notification
        if notification_configs:
            try:
                from lib.notifications import send_notification
                send_notification(
                    notification_configs,
                    subject="Error: Sync failed",
                    job="sync",
                    status="error",
                    message=f"Sync failed with unexpected error: {source} -> {destination}",
                    details=str(e),
                    logger=logger
                )
            except Exception as notify_error:
                logger.error(f"Failed to send error notification: {notify_error}")
        
        return 1


def main():
    """Main entry point."""
    if len(sys.argv) != 3:
        print("Usage: sync_rsync.py <source> <destination>")
        return 1
    
    source = sys.argv[1]
    destination = sys.argv[2]
    
    return run_rsync_with_notifications(source, destination)


if __name__ == '__main__':
    sys.exit(main())
