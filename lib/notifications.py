"""Centralized notification system for infra_tools.

This module provides a unified notification infrastructure for sending alerts
about important events (errors, warnings, successes) to administrators.

Supported notification types:
- Webhook: POST JSON to a URL with event details
- Mailbox: Send email notifications (subject, job, status, message only)

Notifications include:
- subject: Brief description (e.g., "Error: Scrub failed")
- job: Job identifier (e.g., "scrub", "sync", "deploy")
- status: Severity level (good, info, warning, error)
- message: Summary information
- details: Additional logs/data (webhook only)
"""

from __future__ import annotations

import json
import smtplib
import subprocess
from email.message import EmailMessage
from typing import Optional, Literal
from dataclasses import dataclass, asdict
from logging import Logger
import urllib.request
import urllib.error

# Notification status levels
NotificationStatus = Literal["good", "info", "warning", "error"]

# Common subprocess timeout for network operations
NETWORK_TIMEOUT_SECONDS = 30

# Conversion constants
BYTES_TO_MB = 1024 * 1024


@dataclass
class NotificationConfig:
    """Configuration for a notification target."""
    
    type: Literal["webhook", "mailbox"]
    target: str  # URL for webhook, email address for mailbox
    
    def __str__(self) -> str:
        return f"{self.type}:{self.target}"
    
    @classmethod
    def from_string(cls, config_str: str) -> NotificationConfig:
        """Parse notification config from string format.
        
        Args:
            config_str: Format "type:target" (e.g., "webhook:https://...", "mailbox:user@host")
            
        Returns:
            NotificationConfig instance
            
        Raises:
            ValueError: If config string is invalid
        """
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
        """Send notification to all configured targets.
        
        Args:
            notification: Notification to send
            
        Returns:
            True if at least one notification succeeded, False otherwise
        """
        if not self.configs:
            return True  # No notifications configured, nothing to do
        
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
        """Send webhook notification via HTTP POST.
        
        Args:
            url: Webhook URL
            notification: Notification to send
            
        Raises:
            Exception: If webhook request fails
        """
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
        """Send email notification (subject, job, status, message only).
        
        Args:
            email: Email address to send to
            notification: Notification to send
            
        Raises:
            Exception: If email sending fails
        """
        # Format email body with key information (no details for mailbox)
        body = f"""Job: {notification.job}
Status: {notification.status.upper()}

{notification.message}

---
This is an automated notification from infra_tools.
Check system logs for detailed information.
"""
        
        # Use mail command for simplicity (assumes mail/mailutils is installed)
        try:
            # Create email message
            msg = EmailMessage()
            msg.set_content(body)
            msg['Subject'] = notification.subject
            msg['To'] = email
            msg['From'] = f"infra_tools@{self._get_hostname()}"
            
            # Try to send via sendmail (common on Unix systems)
            try:
                # Use sendmail if available
                proc = subprocess.run(
                    ['/usr/sbin/sendmail', '-t', '-oi'],
                    input=msg.as_bytes(),
                    check=True,
                    capture_output=True,
                    timeout=NETWORK_TIMEOUT_SECONDS
                )
                if self.logger:
                    self.logger.info(f"✓ Email notification sent to {email}")
            except (FileNotFoundError, subprocess.CalledProcessError):
                # Fallback to mail command
                proc = subprocess.run(
                    ['mail', '-s', notification.subject, email],
                    input=body.encode('utf-8'),
                    check=True,
                    capture_output=True,
                    timeout=NETWORK_TIMEOUT_SECONDS
                )
                if self.logger:
                    self.logger.info(f"✓ Email notification sent to {email} (via mail)")
                    
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
            raise Exception(f"Failed to send email (mail/sendmail not available or failed): {e}")
    
    def _get_hostname(self) -> str:
        """Get system hostname for email from address."""
        try:
            result = subprocess.run(
                ['hostname', '-f'],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.stdout.strip() or 'localhost'
        except Exception:
            return 'localhost'


def send_notification(
    configs: list[NotificationConfig],
    subject: str,
    job: str,
    status: NotificationStatus,
    message: str,
    details: Optional[str] = None,
    logger: Optional[Logger] = None
) -> bool:
    """Send a notification to configured targets.
    
    This is a convenience function for sending notifications without creating
    a NotificationSender instance.
    
    Args:
        configs: List of notification configurations
        subject: Brief subject line (e.g., "Error: Scrub failed")
        job: Job identifier (e.g., "scrub", "sync")
        status: Notification status level
        message: Detailed message
        details: Additional details (webhook only)
        logger: Optional logger for debugging
        
    Returns:
        True if notification was sent successfully, False otherwise
        
    Example:
        configs = [NotificationConfig("webhook", "https://hooks.slack.com/...")]
        send_notification(
            configs,
            subject="Scrub completed successfully",
            job="scrub",
            status="good",
            message="Processed 1000 files, 0 errors"
        )
    """
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
    """Parse notification arguments from command line.
    
    Args:
        notify_args: List of [type, target] pairs from --notify arguments
        
    Returns:
        List of NotificationConfig instances
        
    Example:
        args = [["webhook", "https://..."], ["mailbox", "admin@example.com"]]
        configs = parse_notification_args(args)
    """
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
