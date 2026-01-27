"""Centralized notification system for infra_tools.

Supports webhook and email notifications for important events.
"""

from __future__ import annotations

import json
import subprocess
from typing import Optional, Literal
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
        
        return cls(type=notif_type, target=target)  # type: ignore


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
        """Send notification to all configured targets."""
        if not self.configs:
            return True
        
        success = False
        for config in self.configs:
            try:
                if config.type == "webhook":
                    self._send_webhook(config.target, notification)
                elif config.type == "mailbox":
                    self._send_mailbox(config.target, notification)
                success = True
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Failed to send {config.type} notification to {config.target}: {e}")
        
        return success
    
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
        
        configs.append(NotificationConfig(type=notif_type, target=target))  # type: ignore
    
    return configs
