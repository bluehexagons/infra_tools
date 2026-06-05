"""Tests for rolling cluster updates."""

from __future__ import annotations

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.cluster_update import run_cluster_update
from lib.config import SetupConfig


def _config(host: str) -> SetupConfig:
    return SetupConfig(
        host=host,
        username="admin",
        system_type="server_proxmox",
    )


class TestClusterUpdate(unittest.TestCase):
    @patch("lib.cluster_update.prepare_validated_runtime_config")
    @patch("lib.cluster_update.load_setup_command")
    def test_preflight_failure_aborts_without_changes(
        self,
        mock_load_setup,
        mock_prepare,
    ) -> None:
        configs = {
            "pve1": _config("10.0.0.10"),
            "pve2": _config("10.0.0.11"),
        }
        mock_load_setup.side_effect = lambda target: configs.get(target)
        mock_prepare.side_effect = [configs["pve1"], ValueError("Missing workspace credential 'fileshare'")]

        with patch("infra_tools._execute_patch_config") as mock_execute:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_cluster_update(["pve1", "pve2"], reboot_timeout=120)

        self.assertEqual(rc, 1)
        self.assertFalse(mock_execute.called)
        output = buf.getvalue()
        self.assertIn("Preflight failed; no systems were changed.", output)
        self.assertIn("Missing workspace credential 'fileshare'", output)

    @patch("lib.cluster_update._remote_reboot_required", side_effect=[True, False])
    @patch("lib.cluster_update._reboot_and_wait")
    @patch("lib.cluster_update.prepare_validated_runtime_config")
    @patch("lib.cluster_update.load_setup_command")
    def test_updates_targets_in_order_and_reboots_when_needed(
        self,
        mock_load_setup,
        mock_prepare,
        mock_reboot_and_wait,
        mock_reboot_required,
    ) -> None:
        configs = {
            "pve1": _config("10.0.0.10"),
            "pve2": _config("10.0.0.11"),
        }
        mock_load_setup.side_effect = lambda target: configs.get(target)
        mock_prepare.side_effect = [configs["pve1"], configs["pve2"]]

        with patch("infra_tools._execute_patch_config", side_effect=[0, 0]) as mock_execute:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_cluster_update(["pve1", "pve2"], reboot_timeout=180)

        self.assertEqual(rc, 0)
        self.assertEqual([call.args[0].host for call in mock_execute.call_args_list], ["10.0.0.10", "10.0.0.11"])
        mock_reboot_and_wait.assert_called_once_with(configs["pve1"], 180)
        output = buf.getvalue()
        self.assertIn("UPDATED   pve1 [10.0.0.10] (reboot-required, rebooted)", output)
        self.assertIn("UPDATED   pve2 [10.0.0.11] - No reboot required", output)

    @patch("lib.cluster_update._remote_reboot_required", return_value=False)
    @patch("lib.cluster_update.prepare_validated_runtime_config")
    @patch("lib.cluster_update.load_setup_command")
    def test_failure_skips_remaining_targets(
        self,
        mock_load_setup,
        mock_prepare,
        mock_reboot_required,
    ) -> None:
        configs = {
            "pve1": _config("10.0.0.10"),
            "pve2": _config("10.0.0.11"),
            "pve3": _config("10.0.0.12"),
        }
        mock_load_setup.side_effect = lambda target: configs.get(target)
        mock_prepare.side_effect = [configs["pve1"], configs["pve2"], configs["pve3"]]

        with patch("infra_tools._execute_patch_config", side_effect=[0, 1]) as mock_execute:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_cluster_update(["pve1", "pve2", "pve3"])

        self.assertEqual(rc, 1)
        self.assertEqual(mock_execute.call_count, 2)
        output = buf.getvalue()
        self.assertIn("FAILED    pve2 [10.0.0.11] - Patch run failed", output)
        self.assertIn("SKIPPED   pve3 [10.0.0.12] - Skipped after failure on pve2", output)
