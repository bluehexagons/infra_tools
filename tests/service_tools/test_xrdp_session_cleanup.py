"""Tests for desktop.service_tools.xrdp_session_cleanup."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from desktop.service_tools import xrdp_session_cleanup


class TestXrdpSessionCleanup(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    @patch.object(sys, "argv", ["xrdp_session_cleanup.py"])
    def test_main_returns_error_when_no_user_is_available(self):
        with self.assertLogs(xrdp_session_cleanup.logger, level="ERROR") as logs:
            result = xrdp_session_cleanup.main()

        self.assertEqual(result, 1)
        self.assertIn("No user specified for cleanup", "\n".join(logs.output))

    @patch("desktop.service_tools.xrdp_session_cleanup.kill_processes")
    @patch.dict(os.environ, {"PAM_USER": "alice"}, clear=True)
    def test_main_logs_structured_start_and_completion(self, mock_kill_processes):
        with self.assertLogs(xrdp_session_cleanup.logger, level="INFO") as logs:
            result = xrdp_session_cleanup.main()

        self.assertEqual(result, 0)
        self.assertEqual(mock_kill_processes.call_count, 6)
        output = "\n".join(logs.output)
        self.assertIn("Starting session cleanup | username='alice'", output)
        self.assertIn("Session cleanup completed | username='alice'", output)


if __name__ == "__main__":
    unittest.main()
