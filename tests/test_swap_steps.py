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
    def test_proxmox_does_not_create_a_generic_swap_file(self, mock_can_manage, mock_run):
        with patch("builtins.print") as mock_print:
            configure_swap(
                SetupConfig(username="root", host="pve1", system_type="server_proxmox")
            )

        mock_can_manage.assert_not_called()
        mock_run.assert_not_called()
        mock_print.assert_called_once_with(
            "  ✓ Skipping swap-file setup (Proxmox storage manages swap)"
        )


if __name__ == "__main__":
    unittest.main()
