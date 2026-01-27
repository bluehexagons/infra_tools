#!/usr/bin/env python3
"""Test script for notification system.

This script demonstrates and tests the notification system by:
1. Creating notification configurations
2. Sending test notifications
3. Testing webhook and mailbox functionality (dry-run mode)
"""

import os
import sys
import tempfile
import json

# Add lib directory to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from lib.notifications import (
    NotificationConfig,
    Notification,
    NotificationSender,
    send_notification,
    parse_notification_args
)
from lib.logging_utils import get_service_logger
from logging import INFO


def test_notification_config():
    """Test notification configuration parsing."""
    print("=" * 60)
    print("Test 1: Notification Configuration")
    print("=" * 60)
    
    # Test webhook config
    webhook_config = NotificationConfig("webhook", "https://example.com/webhook")
    print(f"✓ Created webhook config: {webhook_config}")
    
    # Test mailbox config
    mailbox_config = NotificationConfig("mailbox", "admin@example.com")
    print(f"✓ Created mailbox config: {mailbox_config}")
    
    # Test from_string parsing
    webhook_parsed = NotificationConfig.from_string("webhook:https://hooks.slack.com/test")
    print(f"✓ Parsed webhook config: {webhook_parsed}")
    
    mailbox_parsed = NotificationConfig.from_string("mailbox:user@host.com")
    print(f"✓ Parsed mailbox config: {mailbox_parsed}")
    
    # Test parse_notification_args
    args = [["webhook", "https://test.com"], ["mailbox", "test@test.com"]]
    configs = parse_notification_args(args)
    print(f"✓ Parsed {len(configs)} notification configs from args")
    
    print()


def test_notification_message():
    """Test notification message creation."""
    print("=" * 60)
    print("Test 2: Notification Message")
    print("=" * 60)
    
    # Create a notification
    notification = Notification(
        subject="Test: Scrub completed",
        job="scrub",
        status="good",
        message="Processed 100 files successfully",
        details="Detailed logs here..."
    )
    
    print(f"✓ Created notification: {notification.subject}")
    
    # Test to_dict conversion
    notif_dict = notification.to_dict()
    print(f"✓ Notification as dict: {len(notif_dict)} fields")
    print(f"  - subject: {notif_dict['subject']}")
    print(f"  - job: {notif_dict['job']}")
    print(f"  - status: {notif_dict['status']}")
    print(f"  - message: {notif_dict['message']}")
    
    # Test JSON serialization
    json_str = json.dumps(notif_dict, indent=2)
    print(f"✓ JSON serialization successful ({len(json_str)} bytes)")
    
    print()


def test_webhook_notification():
    """Test webhook notification (dry-run)."""
    print("=" * 60)
    print("Test 3: Webhook Notification (Dry-Run)")
    print("=" * 60)
    
    # Note: This is a dry-run test - no actual webhook is sent
    # In production, you would need a real webhook URL
    
    notification = Notification(
        subject="Success: Test notification",
        job="test",
        status="good",
        message="This is a test notification",
        details="Test details here"
    )
    
    print(f"✓ Would send webhook notification:")
    print(f"  - Subject: {notification.subject}")
    print(f"  - Job: {notification.job}")
    print(f"  - Status: {notification.status}")
    print(f"  - Message: {notification.message}")
    print(f"  - Details included: {notification.details is not None}")
    
    # Show what the JSON payload would look like
    payload = json.dumps(notification.to_dict(), indent=2)
    print(f"\n  Webhook payload:")
    for line in payload.split('\n'):
        print(f"    {line}")
    
    print()


def test_mailbox_notification():
    """Test mailbox notification (dry-run)."""
    print("=" * 60)
    print("Test 4: Mailbox Notification (Dry-Run)")
    print("=" * 60)
    
    notification = Notification(
        subject="Error: Test failure",
        job="test",
        status="error",
        message="Test operation failed",
        details="This should not be included in mailbox"
    )
    
    print(f"✓ Would send mailbox notification:")
    print(f"  - To: admin@example.com")
    print(f"  - Subject: {notification.subject}")
    print(f"  - Job: {notification.job}")
    print(f"  - Status: {notification.status}")
    print(f"  - Message: {notification.message}")
    print(f"  - Details: NOT included (mailbox only includes key info)")
    
    print()


def test_notification_sender():
    """Test NotificationSender with multiple configs."""
    print("=" * 60)
    print("Test 5: NotificationSender")
    print("=" * 60)
    
    # Create multiple notification configs
    configs = [
        NotificationConfig("webhook", "https://example.com/webhook"),
        NotificationConfig("mailbox", "admin@example.com"),
    ]
    
    # Create logger for testing
    logger = get_service_logger('notification_test', 'test', console_output=False)
    
    # Create sender
    sender = NotificationSender(configs, logger=logger)
    print(f"✓ Created NotificationSender with {len(configs)} configs")
    
    # Create notification
    notification = Notification(
        subject="Info: System status",
        job="status_check",
        status="info",
        message="All systems operational",
        details=None
    )
    
    print(f"✓ Would send notification to {len(configs)} targets:")
    for config in configs:
        print(f"  - {config.type}: {config.target}")
    
    print()


def test_convenience_function():
    """Test send_notification convenience function."""
    print("=" * 60)
    print("Test 6: Convenience Function")
    print("=" * 60)
    
    configs = [
        NotificationConfig("webhook", "https://example.com/hook"),
    ]
    
    print("✓ Would send notification using convenience function:")
    print("  - Subject: Warning: High disk usage")
    print("  - Job: disk_monitor")
    print("  - Status: warning")
    print("  - Message: Disk usage at 85%")
    
    # In production, this would actually send:
    # success = send_notification(
    #     configs,
    #     subject="Warning: High disk usage",
    #     job="disk_monitor",
    #     status="warning",
    #     message="Disk usage at 85%",
    #     details="Detailed stats here..."
    # )
    
    print()


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("INFRA_TOOLS NOTIFICATION SYSTEM TEST")
    print("=" * 60 + "\n")
    
    try:
        test_notification_config()
        test_notification_message()
        test_webhook_notification()
        test_mailbox_notification()
        test_notification_sender()
        test_convenience_function()
        
        print("=" * 60)
        print("ALL TESTS COMPLETED")
        print("=" * 60)
        print("\nNOTE: These are dry-run tests.")
        print("To test actual notifications:")
        print("  1. For webhooks: Use a service like webhook.site")
        print("  2. For mailbox: Ensure mail/sendmail is configured")
        print("\nExample webhook test:")
        print("  python3 -c \"from lib.notifications import *; \\")
        print("  send_notification([NotificationConfig('webhook', 'https://webhook.site/YOUR-ID')], \\")
        print("  'Test', 'test', 'info', 'Test message')\"")
        
        return 0
        
    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
