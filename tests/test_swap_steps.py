"""Tests for swap setup safety."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from common.swap_steps import configure_swap
from lib.config import SetupConfig


class TestConfigureSwap(unittest.TestCase):
    @patch("common.swap_steps.run")
    @patch("common.swap_steps.can_manage_swap")
    def test_dry_run_does_not_inspect_or_mutate_swap(self, mock_can_manage, mock_run):
        with patch("builtins.print") as mock_print:
            configure_swap(
                SetupConfig(
                    username="agent",
                    host="vm",
                    system_type="agent_code_vm",
                    dry_run=True,
                    swap_devices=[["fast", "UUID=abcd1234"]],
                )
            )

        mock_can_manage.assert_not_called()
        mock_run.assert_not_called()
        self.assertIn("declared areas=1", mock_print.call_args.args[0])

    @patch("common.swap_steps.run")
    @patch("common.swap_steps.can_manage_swap")
    def test_proxmox_does_not_create_a_generic_swap_file(self, mock_can_manage, mock_run):
        with patch("builtins.print") as mock_print:
            configure_swap(
                SetupConfig(username="root", host="pve1", system_type="server_proxmox")
            )

        mock_can_manage.assert_not_called()
        mock_run.assert_not_called()
        mock_print.assert_called_once_with(
            "  ✓ Preserving Proxmox host swap layout"
        )


if __name__ == "__main__":
    unittest.main()
