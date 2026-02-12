"""Tests for lib/notifications.py: config parsing, notification objects, sender logic."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.notifications import (
    NotificationConfig,
    Notification,
    NotificationSender,
    parse_notification_args,
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


if __name__ == '__main__':
    unittest.main()
