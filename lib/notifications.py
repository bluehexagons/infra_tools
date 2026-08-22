"""Centralized notification system for infra_tools.

Supports webhook and email notifications for important events.
"""

from __future__ import annotations

import json
import re
import socket
import subprocess
from typing import Optional, Literal, cast
from dataclasses import dataclass, field
from logging import ERROR, INFO, Logger, WARNING
import urllib.request
import urllib.error
import urllib.parse

from lib.logging_utils import log_event
from lib.types import JSONDict

NotificationStatus = Literal["good", "info", "warning", "error"]
NotificationState = Literal["firing", "resolved", "success"]
NotificationDeliveryPolicy = Literal["always", "signal"]

NETWORK_TIMEOUT_SECONDS = 30
NOTIFICATION_SCHEMA_VERSION = 2
_MAILBOX_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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

        config = cls(type=cast(Literal["webhook", "mailbox"], notif_type), target=target)
        validate_notification_config(config)
        return config


@dataclass
class Notification:
    """A notification message."""
    
    subject: str
    job: str
    status: NotificationStatus
    message: str
    details: Optional[str] = None
    hostname: str = field(default_factory=lambda: socket.gethostname())
    data: Optional[JSONDict] = None
    event_type: Optional[str] = None
    state: Optional[NotificationState] = None
    dedup_key: Optional[str] = None
    actions: Optional[list[str]] = None
    delivery_policy: NotificationDeliveryPolicy = "always"

    def __post_init__(self) -> None:
        """Fill the common event fields used by every notification target."""
        if self.event_type is None:
            self.event_type = self.job
        if self.state is None:
            self.state = "success" if self.status in ("good", "info") else "firing"

    def to_dict(self) -> JSONDict:
        """Return a descriptive REST payload with separate event and operator data."""
        return {
            "schema_version": NOTIFICATION_SCHEMA_VERSION,
            "event": {
                "type": self.event_type,
                "state": self.state,
                "status": self.status,
                "deduplication_key": self.dedup_key,
            },
            "operator": {
                "subject": self.subject,
                "job": self.job,
                "system": self.hostname,
                "what_happened": self.message,
                "suggested_actions": list(self.actions or []),
                "details": self.details or "",
            },
            "data": self.data or {},
        }


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

        if not _should_deliver(notification):
            if self.logger:
                log_event(
                    self.logger,
                    "Notification suppressed by delivery policy",
                    level=INFO,
                    job=notification.job,
                    event_type=notification.event_type,
                    status=notification.status,
                )
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
                    log_event(
                        self.logger,
                        "Notification delivery failed",
                        level=ERROR,
                        job=notification.job,
                        notification_type=config.type,
                        target=_redact_notification_target(config),
                        error=str(e),
                    )
        
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
                    log_event(
                        self.logger,
                        "Webhook notification sent",
                        level=INFO,
                        job=notification.job,
                        status=notification.status,
                        target=_redact_notification_target(
                            NotificationConfig(type="webhook", target=url)
                        ),
                    )
        except urllib.error.URLError as e:
            raise Exception(f"Webhook request failed: {e}")
    
    def _send_mailbox(self, email: str, notification: Notification) -> None:
        """Send email notification."""
        body_parts = [
            f"[{notification.status.upper()}] {notification.subject}",
            f"Job: {notification.job}",
            f"Status: {notification.status.upper()}",
            f"System: {notification.hostname}",
            f"Event: {notification.event_type}",
            f"State: {notification.state}",
            "",
            "What happened:",
            notification.message,
        ]
        if notification.actions:
            body_parts.extend([
                "",
                "Suggested action:",
                *[f"- {action}" for action in notification.actions],
            ])
        if notification.details:
            body_parts.extend(["", "Details:", notification.details])
        if notification.dedup_key:
            body_parts.extend(["", f"Deduplication key: {notification.dedup_key}"])
        if notification.data:
            body_parts.extend([
                "",
                "Machine-readable event data (JSON):",
                json.dumps(notification.data, indent=2, sort_keys=True),
            ])
        body_parts.extend([
            "",
            "---",
            "This is an automated notification from infra_tools.",
            "Check system logs for detailed information.",
            "",
        ])
        body = "\n".join(body_parts)
        
        try:
            subprocess.run(
                ['mail', '-s', notification.subject, email],
                input=body.encode('utf-8'),
                check=True,
                capture_output=True,
                timeout=NETWORK_TIMEOUT_SECONDS
            )
            if self.logger:
                log_event(
                    self.logger,
                    "Mailbox notification sent",
                    level=INFO,
                    job=notification.job,
                    status=notification.status,
                    target=_redact_notification_target(
                        NotificationConfig(type="mailbox", target=email)
                    ),
                )
                    
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
            raise Exception(f"Failed to send email: {e}")


def send_notification(
    configs: list[NotificationConfig],
    subject: str,
    job: str,
    status: NotificationStatus,
    message: str,
    details: Optional[str] = None,
    logger: Optional[Logger] = None,
    data: Optional[JSONDict] = None,
    event_type: Optional[str] = None,
    state: Optional[NotificationState] = None,
    dedup_key: Optional[str] = None,
    actions: Optional[list[str]] = None,
    delivery_policy: NotificationDeliveryPolicy = "always",
) -> bool:
    """Send a notification to configured targets."""
    notification = Notification(
        subject=subject,
        job=job,
        status=status,
        message=message,
        details=details,
        data=data,
        event_type=event_type,
        state=state,
        dedup_key=dedup_key,
        actions=actions,
        delivery_policy=delivery_policy,
    )
    
    sender = NotificationSender(configs, logger=logger)
    return sender.send(notification)


def send_notification_safe(
    configs: list[NotificationConfig],
    subject: str,
    job: str,
    status: NotificationStatus,
    message: str,
    details: Optional[str] = None,
    logger: Optional[Logger] = None,
    data: Optional[JSONDict] = None,
    event_type: Optional[str] = None,
    state: Optional[NotificationState] = None,
    dedup_key: Optional[str] = None,
    actions: Optional[list[str]] = None,
    delivery_policy: NotificationDeliveryPolicy = "always",
) -> bool:
    """Send a notification and suppress delivery errors."""
    if not configs:
        return True
    try:
        notification_kwargs: dict[str, object] = {
            "subject": subject,
            "job": job,
            "status": status,
            "message": message,
            "details": details,
            "logger": logger,
            "event_type": event_type,
            "state": state,
            "dedup_key": dedup_key,
            "actions": actions,
            "delivery_policy": delivery_policy,
        }
        if data is not None:
            notification_kwargs["data"] = data
        delivered = send_notification(configs, **notification_kwargs)  # type: ignore[arg-type]
        if delivered is False and logger:
            log_event(
                logger,
                "Notification delivery incomplete",
                level=WARNING,
                job=job,
            )
        return delivered
    except Exception as e:
        if logger:
            log_event(
                logger,
                "Notification send suppressed after delivery failure",
                level=WARNING,
                job=job,
                error=str(e),
            )
        return False


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


def validate_notification_config(config: NotificationConfig) -> None:
    """Validate a parsed notification target."""

    target = config.target.strip()
    if not target:
        raise ValueError(f"Notification target for {config.type} must not be empty")

    if config.type == "webhook":
        parsed = urllib.parse.urlparse(target)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"Invalid webhook URL: {target}")
        return

    if config.type == "mailbox":
        if not _MAILBOX_PATTERN.match(target):
            raise ValueError(f"Invalid mailbox address: {target}")
        return

    raise ValueError(f"Invalid notification type: {config.type}")


def validate_notification_args(notify_args: Optional[list[list[str]]]) -> None:
    """Validate raw --notify argument pairs from CLI/config surfaces."""

    if not notify_args:
        return

    for notify_arg in notify_args:
        if len(notify_arg) != 2:
            raise ValueError(
                "--notify requires TYPE and TARGET"
            )
        notif_type, target = notify_arg
        if notif_type not in ["webhook", "mailbox"]:
            raise ValueError(f"Invalid notification type: {notif_type}")
        validate_notification_config(
            NotificationConfig(type=cast(Literal["webhook", "mailbox"], notif_type), target=target)
        )


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
            log_event(
                logger,
                "Failed to load notification configs from machine state",
                level=WARNING,
                error=str(e),
            )
    
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
        logger=logger,
        event_type="setup",
        state="success" if success else "firing",
        dedup_key=f"setup:{system_type}:{host}",
    )


def _should_deliver(notification: Notification) -> bool:
    """Return whether a signal-only notification has operator value."""
    if notification.delivery_policy == "always":
        return True
    return notification.status in ("warning", "error") or notification.state in (
        "firing",
        "resolved",
    )


def _redact_notification_target(config: NotificationConfig) -> str:
    """Return a log-safe summary of a notification target."""

    if config.type == "webhook":
        parsed = urllib.parse.urlparse(config.target)
        return parsed.hostname or "unknown-host"

    if config.type == "mailbox" and "@" in config.target:
        _local_part, domain = config.target.rsplit("@", 1)
        return f"*@{domain}"

    return config.type
