"""Tests for lib/notifications.py: config parsing, notification objects, sender logic."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.notifications import (
    NotificationConfig,
    Notification,
    NotificationSender,
    parse_notification_args,
    send_setup_notification,
)


class TestNotificationConfig(unittest.TestCase):
    def test_from_string_webhook(self):
        config = NotificationConfig.from_string('webhook:https://example.com/hook')
        self.assertEqual(config.type, 'webhook')
        self.assertEqual(config.target, 'https://example.com/hook')

    def test_from_string_mailbox(self):
        config = NotificationConfig.from_string('mailbox:admin@example.com')
        self.assertEqual(config.type, 'mailbox')
        self.assertEqual(config.target, 'admin@example.com')

    def test_from_string_invalid_type(self):
        with self.assertRaises(ValueError):
            NotificationConfig.from_string('sms:+1234567890')

    def test_from_string_no_colon(self):
        with self.assertRaises(ValueError):
            NotificationConfig.from_string('invalid')

    def test_str(self):
        config = NotificationConfig(type='webhook', target='https://url')
        self.assertEqual(str(config), 'webhook:https://url')


class TestNotification(unittest.TestCase):
    def test_to_dict(self):
        n = Notification(subject='Test', job='sync', status='good', message='All ok')
        d = n.to_dict()
        self.assertEqual(d['subject'], 'Test')
        self.assertEqual(d['job'], 'sync')
        self.assertEqual(d['status'], 'good')
        self.assertEqual(d['message'], 'All ok')

    def test_to_dict_excludes_none_details(self):
        n = Notification(subject='Test', job='sync', status='good', message='ok', details=None)
        d = n.to_dict()
        self.assertNotIn('details', d)

    def test_to_dict_includes_details(self):
        n = Notification(subject='Test', job='sync', status='error', message='fail', details='traceback')
        d = n.to_dict()
        self.assertEqual(d['details'], 'traceback')


class TestNotificationSender(unittest.TestCase):
    def test_empty_configs_returns_true(self):
        sender = NotificationSender([])
        notification = Notification(subject='Test', job='sync', status='good', message='ok')
        self.assertTrue(sender.send(notification))


class TestParseNotificationArgs(unittest.TestCase):
    def test_none_args(self):
        self.assertEqual(parse_notification_args(None), [])

    def test_empty_list(self):
        self.assertEqual(parse_notification_args([]), [])

    def test_valid_webhook(self):
        configs = parse_notification_args([['webhook', 'https://example.com/hook']])
        self.assertEqual(len(configs), 1)
        self.assertEqual(configs[0].type, 'webhook')

    def test_valid_mailbox(self):
        configs = parse_notification_args([['mailbox', 'admin@example.com']])
        self.assertEqual(len(configs), 1)
        self.assertEqual(configs[0].type, 'mailbox')

    def test_multiple(self):
        configs = parse_notification_args([
            ['webhook', 'https://hook1.com'],
            ['mailbox', 'user@example.com'],
        ])
        self.assertEqual(len(configs), 2)

    def test_invalid_type_skipped(self):
        configs = parse_notification_args([['sms', '+1234']])
        self.assertEqual(len(configs), 0)

    def test_wrong_arg_count_skipped(self):
        configs = parse_notification_args([['webhook']])
        self.assertEqual(len(configs), 0)


class TestSendSetupNotification(unittest.TestCase):
    @patch('lib.notifications.NotificationSender.send')
    def test_success_notification(self, mock_send):
        mock_send.return_value = True
        result = send_setup_notification(
            notify_specs=[['webhook', 'https://example.com/hook']],
            system_type='server_web',
            host='10.0.0.1',
            success=True,
        )
        self.assertTrue(result)
        mock_send.assert_called_once()
        notification = mock_send.call_args[0][0]
        self.assertEqual(notification.job, 'setup')
        self.assertEqual(notification.status, 'good')
        self.assertIn('server_web', notification.subject)
        self.assertIn('10.0.0.1', notification.subject)
        self.assertIn('successfully', notification.message)

    @patch('lib.notifications.NotificationSender.send')
    def test_failure_notification(self, mock_send):
        mock_send.return_value = True
        result = send_setup_notification(
            notify_specs=[['webhook', 'https://example.com/hook']],
            system_type='server_web',
            host='10.0.0.1',
            success=False,
            errors=["Step 'install_nginx' failed: command error"],
        )
        self.assertTrue(result)
        notification = mock_send.call_args[0][0]
        self.assertEqual(notification.status, 'error')
        self.assertIn('failed', notification.subject)
        self.assertIn('install_nginx', notification.details)

    @patch('lib.notifications.NotificationSender.send')
    def test_failure_with_multiple_errors(self, mock_send):
        mock_send.return_value = True
        errors = ["Error 1", "Error 2"]
        send_setup_notification(
            notify_specs=[['webhook', 'https://example.com/hook']],
            system_type='server_web',
            host='10.0.0.1',
            success=False,
            errors=errors,
        )
        notification = mock_send.call_args[0][0]
        self.assertIn('Errors (2)', notification.details)
        self.assertIn('Error 1', notification.details)
        self.assertIn('Error 2', notification.details)

    def test_no_notify_specs_returns_true(self):
        result = send_setup_notification(
            notify_specs=None,
            system_type='server_web',
            host='10.0.0.1',
            success=True,
        )
        self.assertTrue(result)

    def test_empty_notify_specs_returns_true(self):
        result = send_setup_notification(
            notify_specs=[],
            system_type='server_web',
            host='10.0.0.1',
            success=True,
        )
        self.assertTrue(result)

    @patch('lib.notifications.NotificationSender.send')
    def test_success_no_errors_in_details(self, mock_send):
        mock_send.return_value = True
        send_setup_notification(
            notify_specs=[['webhook', 'https://example.com/hook']],
            system_type='server_lite',
            host='localhost',
            success=True,
        )
        notification = mock_send.call_args[0][0]
        self.assertNotIn('Errors', notification.details)
        self.assertIn('server_lite', notification.details)
        self.assertIn('localhost', notification.details)


if __name__ == '__main__':
    unittest.main()
