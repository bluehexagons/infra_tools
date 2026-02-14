#!/usr/bin/env python3
"""Rsync wrapper with notification support for sync operations."""

from __future__ import annotations

import sys
import os
import subprocess
import fcntl
import hashlib
import signal
import time
import threading
from datetime import datetime

# Add lib directory to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../..'))

from lib.logging_utils import get_service_logger

# Conversion constants
BYTES_TO_MB = 1024 * 1024

# Lock directory
LOCK_DIR = "/var/lock/infra_tools"

# Progress notification intervals (in seconds) - exponential backoff
PROGRESS_INTERVALS = [
    3600,    # 1 hour
    7200,    # 2 hours (cumulative: 3h)
    14400,   # 4 hours (cumulative: 7h)
    28800,   # 8 hours (cumulative: 15h)
    28800,   # 8 hours (cumulative: 23h)
]

# Global for signal handling
_rsync_process = None
_logger = None
_shutting_down = False


def _signal_handler(signum: int, frame) -> None:
    """Handle termination signals gracefully."""
    global _shutting_down
    if _shutting_down:
        return  # Already handling shutdown
    
    _shutting_down = True
    
    if _logger:
        _logger.warning(f"Received signal {signum} ({'SIGTERM' if signum == signal.SIGTERM else 'SIGINT'}), initiating graceful shutdown...")
    
    # If rsync is running, terminate it gracefully
    if _rsync_process and _rsync_process.poll() is None:
        if _logger:
            _logger.info("Terminating rsync process...")
        try:
            _rsync_process.terminate()  # Send SIGTERM to rsync
            _rsync_process.wait(timeout=30)  # Wait up to 30 seconds
        except subprocess.TimeoutExpired:
            if _logger:
                _logger.warning("Rsync did not terminate gracefully, killing...")
            _rsync_process.kill()  # Force kill if needed
        except Exception as e:
            if _logger:
                _logger.error(f"Error terminating rsync: {e}")
    
    if _logger:
        _logger.info("Sync operation interrupted by signal, partial files preserved with --partial flag")
    
    sys.exit(143)  # Standard exit code for SIGTERM (128 + 15)


def _send_progress_notification(
    source: str,
    destination: str,
    start_time: datetime,
    elapsed_hours: float,
    notification_configs: list,
    tz,
    logger
) -> None:
    """Send a progress notification for a long-running sync."""
    try:
        from lib.notifications import send_notification
        
        current_time = datetime.now(tz)
        
        message = f"Sync still running after {elapsed_hours:.1f} hours"
        
        details = f"""Sync Progress Update:
Source: {source}
Destination: {destination}
Start time: {start_time.strftime('%Y-%m-%d %H:%M:%S %Z')}
Current time: {current_time.strftime('%Y-%m-%d %H:%M:%S %Z')}
Elapsed: {elapsed_hours:.1f} hours

The sync operation is still in progress. This is normal for large datasets.
You will receive another update if it continues running.
"""
        
        send_notification(
            notification_configs,
            subject=f"Info: Sync in progress ({elapsed_hours:.0f}h)",
            job="sync",
            status="info",
            message=message,
            details=details,
            logger=logger
        )
        logger.info(f"Sent progress notification after {elapsed_hours:.1f} hours")
    except Exception as e:
        logger.error(f"Failed to send progress notification: {e}")


def _schedule_progress_notifications(
    source: str,
    destination: str,
    start_time: datetime,
    notification_configs: list,
    tz,
    logger
) -> None:
    """Schedule progress notifications using exponential backoff."""
    if not notification_configs:
        return  # No notifications configured
    
    cumulative_seconds = 0
    
    for interval_seconds in PROGRESS_INTERVALS:
        cumulative_seconds += interval_seconds
        elapsed_hours = cumulative_seconds / 3600
        
        # Create a timer function with the captured elapsed time
        timer = threading.Timer(
            cumulative_seconds,
            _check_and_send_progress,
            args=(source, destination, start_time, elapsed_hours, notification_configs, tz, logger)
        )
        timer.daemon = True
        timer.start()


def _check_and_send_progress(
    source: str,
    destination: str,
    start_time: datetime,
    elapsed_hours: float,
    notification_configs: list,
    tz,
    logger
) -> None:
    """Check if rsync is still running and send progress notification if so."""
    if _shutting_down:
        return
    
    # Check if rsync is still running
    if _rsync_process and _rsync_process.poll() is None:
        _send_progress_notification(
            source, destination, start_time, elapsed_hours,
            notification_configs, tz, logger
        )


def run_rsync_with_notifications(source: str, destination: str) -> int:
    """Run rsync and send notifications on completion or failure.
    
    Args:
        source: Source directory
        destination: Destination directory
        
    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    logger = get_service_logger('sync', 'operations', use_syslog=False, console_output=True)
    
    # Create lock directory if it doesn't exist
    os.makedirs(LOCK_DIR, exist_ok=True)
    
    # Create a unique lock file based on source and destination
    lock_key = hashlib.md5(f"{source}:{destination}".encode()).hexdigest()
    lock_file_path = os.path.join(LOCK_DIR, f"sync-{lock_key}.lock")
    
    # Try to acquire exclusive lock
    lock_file = None
    try:
        lock_file = open(lock_file_path, 'w')
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        if lock_file:
            lock_file.close()
        logger.warning(f"Another sync operation is already running for {source} -> {destination}")
        logger.info("Skipping this run to avoid conflicts")
        return 0  # Exit gracefully, not an error
    
    try:
        return _run_rsync_locked(source, destination, logger)
    finally:
        # Release lock and clean up lock file
        if lock_file:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                lock_file.close()
                os.unlink(lock_file_path)
            except Exception:
                pass


def _run_rsync_locked(source: str, destination: str, logger) -> int:
    """Run rsync with lock already acquired.
    
    Args:
        source: Source directory
        destination: Destination directory
        logger: Logger instance
        
    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    global _logger, _rsync_process
    _logger = logger
    
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)
    
    # Load notification configs and timezone from machine state
    notification_configs = []
    timezone = 'UTC'
    friendly_name = None
    try:
        from lib.machine_state import load_setup_config
        from lib.notifications import parse_notification_args
        setup_config = load_setup_config()
        if setup_config:
            if 'notify_specs' in setup_config:
                notification_configs = parse_notification_args(setup_config['notify_specs'])
            if 'timezone' in setup_config:
                timezone = setup_config['timezone']
            if 'friendly_name' in setup_config:
                friendly_name = setup_config['friendly_name']
    except Exception as e:
        logger.warning(f"Failed to load notification configs: {e}")
    
    # Import timezone support
    try:
        import pytz
        tz = pytz.timezone(timezone)
    except Exception:
        # Fall back to UTC if timezone is invalid or pytz not available
        import pytz
        tz = pytz.UTC
    
    logger.info(f"Starting sync: {source} -> {destination}")
    start_time = datetime.now(tz)
    
    # Send start notification
    if notification_configs:
        try:
            from lib.notifications import send_notification
            import socket
            
            # Use friendly name if available, otherwise use hostname
            display_name = friendly_name if friendly_name else socket.gethostname()
            
            message = f"Starting sync from {source} to {destination}"
            
            details = f"""Sync Starting:
Source: {source}
Destination: {destination}
Host: {display_name}
Start time: {start_time.strftime('%Y-%m-%d %H:%M:%S %Z')}

The sync operation is beginning. You will be notified upon completion.
"""
            
            send_notification(
                notification_configs,
                subject=f"Info: Sync starting on {display_name}",
                job="sync",
                status="info",
                message=message,
                details=details,
                logger=logger
            )
            logger.info("Sent start notification")
        except Exception as e:
            logger.error(f"Failed to send start notification: {e}")
    
    # Schedule progress notifications with exponential backoff
    _schedule_progress_notifications(source, destination, start_time, notification_configs, tz, logger)
    
    try:
        # Run rsync - use Popen to track the process for signal handling
        global _rsync_process
        _rsync_process = subprocess.Popen(
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
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Wait for completion
        stdout, stderr = _rsync_process.communicate()
        returncode = _rsync_process.returncode
        
        # Check if interrupted by signal
        if _shutting_down:
            logger.info("Rsync was interrupted, partial files preserved")
            return 143
        
        if returncode != 0:
            raise subprocess.CalledProcessError(returncode, 'rsync', stdout, stderr)
        
        end_time = datetime.now(tz)
        duration_seconds = (end_time - start_time).total_seconds()
        
        # Format duration
        hours = int(duration_seconds // 3600)
        minutes = int((duration_seconds % 3600) // 60)
        seconds = int(duration_seconds % 60)
        if hours > 0:
            duration_str = f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            duration_str = f"{minutes}m {seconds}s"
        else:
            duration_str = f"{seconds}s"
        
        logger.info(f"✓ Sync completed in {duration_str}")
        
        # Log rsync output for observability
        if stdout:
            logger.info(f"Rsync output:\n{stdout}")
        
        # Parse rsync stats for notification
        stats_lines = stdout.split('\n')
        files_transferred = 0
        total_size = 0
        
        for line in stats_lines:
            if 'Number of files transferred:' in line:
                try:
                    files_transferred = int(line.split(':')[1].strip())
                except (IndexError, ValueError):
                    # Ignore malformed stats line
                    pass
            elif 'Total file size:' in line:
                try:
                    size_str = line.split(':')[1].strip().split()[0].replace(',', '')
                    total_size = int(size_str)
                except (IndexError, ValueError):
                    # Ignore malformed stats line
                    pass
        
        # Send success notification
        if notification_configs:
            try:
                from lib.notifications import send_notification
                message = f"Synced {files_transferred} files"
                if total_size > 0:
                    message += f" ({total_size // BYTES_TO_MB} MB)"
                message += f" in {duration_str}"
                
                details = f"""Sync Summary:
Source: {source}
Destination: {destination}
Start time: {start_time.strftime('%Y-%m-%d %H:%M:%S %Z')}
End time: {end_time.strftime('%Y-%m-%d %H:%M:%S %Z')}
Duration: {duration_str}
Files transferred: {files_transferred}

Output:
{stdout}
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
        end_time = datetime.now(tz)
        duration_seconds = (end_time - start_time).total_seconds()
        
        # Format duration
        hours = int(duration_seconds // 3600)
        minutes = int((duration_seconds % 3600) // 60)
        seconds = int(duration_seconds % 60)
        if hours > 0:
            duration_str = f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            duration_str = f"{minutes}m {seconds}s"
        else:
            duration_str = f"{seconds}s"
        
        logger.error(f"✗ Sync failed after {duration_str}")
        logger.error(f"Error: {e.stderr or e.stdout}")
        
        # Send error notification
        if notification_configs:
            try:
                from lib.notifications import send_notification
                error_msg = e.stderr or e.stdout or str(e)
                
                details = f"""Sync Error:
Source: {source}
Destination: {destination}
Start time: {start_time.strftime('%Y-%m-%d %H:%M:%S %Z')}
End time: {end_time.strftime('%Y-%m-%d %H:%M:%S %Z')}
Duration: {duration_str}

Error:
{error_msg}"""
                
                send_notification(
                    notification_configs,
                    subject="Error: Sync failed",
                    job="sync",
                    status="error",
                    message=f"Sync failed: {source} -> {destination}",
                    details=details,
                    logger=logger
                )
            except Exception as notify_error:
                logger.error(f"Failed to send error notification: {notify_error}")
        
        return e.returncode
    
    except Exception as e:
        end_time = datetime.now(tz)
        duration_seconds = (end_time - start_time).total_seconds()
        
        # Format duration
        hours = int(duration_seconds // 3600)
        minutes = int((duration_seconds % 3600) // 60)
        seconds = int(duration_seconds % 60)
        if hours > 0:
            duration_str = f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            duration_str = f"{minutes}m {seconds}s"
        else:
            duration_str = f"{seconds}s"
        
        logger.error(f"✗ Sync failed with unexpected error after {duration_str}: {e}")
        
        # Send error notification
        if notification_configs:
            try:
                from lib.notifications import send_notification
                
                details = f"""Sync Error:
Source: {source}
Destination: {destination}
Start time: {start_time.strftime('%Y-%m-%d %H:%M:%S %Z')}
End time: {end_time.strftime('%Y-%m-%d %H:%M:%S %Z')}
Duration: {duration_str}

Error:
{str(e)}"""
                
                send_notification(
                    notification_configs,
                    subject="Error: Sync failed",
                    job="sync",
                    status="error",
                    message=f"Sync failed with unexpected error: {source} -> {destination}",
                    details=details,
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
