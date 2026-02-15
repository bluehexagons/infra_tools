"""Centralized notification system for infra_tools.

Supports webhook and email notifications for important events.
"""

from __future__ import annotations

import json
import subprocess
from typing import Optional, Literal, cast
from dataclasses import dataclass, asdict
from logging import Logger
import urllib.request
import urllib.error

NotificationStatus = Literal["good", "info", "warning", "error"]

NETWORK_TIMEOUT_SECONDS = 30


@dataclass
class NotificationConfig:
    """Configuration for a notification target."""
    
    type: Literal["webhook", "mailbox"]
    target: str
    
    def __str__(self) -> str:
        return f"{self.type}:{self.target}"
    
    @classmethod
    def from_string(cls, config_str: str) -> NotificationConfig:
        """Parse notification config from string format."""
        parts = config_str.split(":", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid notification config format: {config_str}")
        
        notif_type, target = parts
        if notif_type not in ["webhook", "mailbox"]:
            raise ValueError(f"Invalid notification type: {notif_type}")
        
        return cls(type=cast(Literal["webhook", "mailbox"], notif_type), target=target)


@dataclass
class Notification:
    """A notification message."""
    
    subject: str
    job: str
    status: NotificationStatus
    message: str
    details: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {k: v for k, v in asdict(self).items() if v is not None}


class NotificationSender:
    """Handles sending notifications to configured targets."""
    
    def __init__(self, configs: list[NotificationConfig], logger: Optional[Logger] = None):
        """Initialize notification sender.
        
        Args:
            configs: List of notification configurations
            logger: Optional logger for debugging
        """
        self.configs = configs
        self.logger = logger
    
    def send(self, notification: Notification) -> bool:
        """Send notification to all configured targets.
        
        Returns:
            True only if ALL configured targets were sent successfully.
            Returns True if no targets are configured (nothing to fail).
        """
        if not self.configs:
            return True
        
        all_succeeded = True
        for config in self.configs:
            try:
                if config.type == "webhook":
                    self._send_webhook(config.target, notification)
                elif config.type == "mailbox":
                    self._send_mailbox(config.target, notification)
            except Exception as e:
                all_succeeded = False
                if self.logger:
                    self.logger.error(f"Failed to send {config.type} notification to {config.target}: {e}")
        
        return all_succeeded
    
    def _send_webhook(self, url: str, notification: Notification) -> None:
        """Send webhook notification via HTTP POST."""
        data = json.dumps(notification.to_dict()).encode('utf-8')
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'infra_tools-notification/1.0'
        }
        
        request = urllib.request.Request(url, data=data, headers=headers, method='POST')
        
        try:
            with urllib.request.urlopen(request, timeout=NETWORK_TIMEOUT_SECONDS) as response:
                if response.status not in (200, 201, 202, 204):
                    raise Exception(f"Webhook returned status {response.status}")
                
                if self.logger:
                    self.logger.info(f"✓ Webhook notification sent to {url}")
        except urllib.error.URLError as e:
            raise Exception(f"Webhook request failed: {e}")
    
    def _send_mailbox(self, email: str, notification: Notification) -> None:
        """Send email notification."""
        body = f"""Job: {notification.job}
Status: {notification.status.upper()}

{notification.message}

---
This is an automated notification from infra_tools.
Check system logs for detailed information.
"""
        
        try:
            subprocess.run(
                ['mail', '-s', notification.subject, email],
                input=body.encode('utf-8'),
                check=True,
                capture_output=True,
                timeout=NETWORK_TIMEOUT_SECONDS
            )
            if self.logger:
                self.logger.info(f"✓ Email notification sent to {email}")
                    
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
            raise Exception(f"Failed to send email: {e}")


def send_notification(
    configs: list[NotificationConfig],
    subject: str,
    job: str,
    status: NotificationStatus,
    message: str,
    details: Optional[str] = None,
    logger: Optional[Logger] = None
) -> bool:
    """Send a notification to configured targets."""
    notification = Notification(
        subject=subject,
        job=job,
        status=status,
        message=message,
        details=details
    )
    
    sender = NotificationSender(configs, logger=logger)
    return sender.send(notification)


def parse_notification_args(notify_args: Optional[list[list[str]]]) -> list[NotificationConfig]:
    """Parse notification arguments from command line."""
    if not notify_args:
        return []
    
    configs = []
    for notify_arg in notify_args:
        if len(notify_arg) != 2:
            continue
        
        notif_type, target = notify_arg
        if notif_type not in ["webhook", "mailbox"]:
            continue
        
        configs.append(NotificationConfig(type=cast(Literal["webhook", "mailbox"], notif_type), target=target))
    
    return configs


def load_notification_configs_from_state(logger: Optional[Logger] = None) -> list[NotificationConfig]:
    """Load notification configs from saved machine state.
    
    This helper loads notification configurations that were previously saved during
    setup, allowing service tools to use the same notification targets without
    re-parsing command-line arguments.
    
    Args:
        logger: Optional logger for debugging
    
    Returns:
        List of NotificationConfig objects, empty list if state not found or parsing fails
    
    Example:
        # In a service tool (e.g., auto_update_node.py)
        configs = load_notification_configs_from_state(logger)
        sender = NotificationSender(configs, logger=logger)
    """
    try:
        from lib.machine_state import load_setup_config
        setup_config = load_setup_config()
        if setup_config and 'notify_specs' in setup_config:
            return parse_notification_args(setup_config['notify_specs'])
    except (ImportError, OSError, ValueError, KeyError, TypeError) as e:
        if logger:
            logger.warning(f"Failed to load notification configs from machine state: {e}")
    
    return []


def send_setup_notification(
    notify_specs: Optional[list[list[str]]],
    system_type: str,
    host: str,
    success: bool,
    errors: Optional[list[str]] = None,
    friendly_name: Optional[str] = None,
    logger: Optional[Logger] = None
) -> bool:
    """Send a notification summarizing setup results.

    Args:
        notify_specs: Raw notify specs from SetupConfig (list of [type, target] pairs)
        system_type: The system type that was set up
        host: The host that was set up
        success: Whether setup completed successfully
        errors: Optional list of error messages encountered during setup
        friendly_name: Optional human-readable name for this system
        logger: Optional logger for debugging

    Returns:
        True if all notifications were sent successfully, False otherwise
    """
    configs = parse_notification_args(notify_specs)
    if not configs:
        return True

    # Build a descriptive identifier: prefer friendly_name, fall back to host
    identifier = f"{friendly_name} ({host})" if friendly_name else host

    if success:
        status: NotificationStatus = "good"
        subject = f"Setup complete: {system_type} on {identifier}"
        message = f"Setup of {system_type} on {identifier} completed successfully."
    else:
        status = "error"
        subject = f"Setup failed: {system_type} on {identifier}"
        message = f"Setup of {system_type} on {identifier} failed."

    details_parts = [f"System type: {system_type}", f"Host: {host}"]
    if friendly_name:
        details_parts.append(f"Name: {friendly_name}")
    if errors:
        details_parts.append(f"\nErrors ({len(errors)}):")
        for error in errors:
            details_parts.append(f"  - {error}")
    details = "\n".join(details_parts)

    return send_notification(
        configs,
        subject=subject,
        job="setup",
        status=status,
        message=message,
        details=details,
        logger=logger
    )
