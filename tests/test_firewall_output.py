"""Tests for concise UFW command reporting."""

from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from security.security_steps import _run_ufw, _ufw_failure


class TestFirewallOutput(unittest.TestCase):
    @patch("security.security_steps.run")
    def test_successful_ufw_output_is_captured(self, mock_run) -> None:
        mock_run.return_value = SimpleNamespace(returncode=0, stdout="Rule added\n", stderr="")

        _run_ufw("ufw allow ssh")

        mock_run.assert_called_once_with(
            "ufw allow ssh",
            check=False,
            capture_output=True,
        )

    def test_failed_ufw_output_remains_actionable(self) -> None:
        error = _ufw_failure(
            "Failed to install rule",
            SimpleNamespace(stdout="", stderr="permission denied\n"),
        )

        self.assertEqual(str(error), "Failed to install rule: permission denied")


if __name__ == "__main__":
    unittest.main()
