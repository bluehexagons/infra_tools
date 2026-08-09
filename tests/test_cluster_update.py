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
from lib.proxmox_maintenance import ProxmoxMaintenanceReport
from lib.proxmox_manage import ContainerInfo


def _config(host: str) -> SetupConfig:
    return SetupConfig(
        host=host,
        username="admin",
        system_type="server_proxmox",
    )


def _maintenance_report(
    *,
    reboot_required: bool = False,
    running_guests: list[ContainerInfo] | None = None,
    errors: list[str] | None = None,
) -> ProxmoxMaintenanceReport:
    return ProxmoxMaintenanceReport(
        host_name="pve",
        address="10.0.0.10",
        node_name="pve",
        clustered=False,
        reboot_required=reboot_required,
        running_guests=list(running_guests or []),
        errors=list(errors or []),
    )


class TestClusterUpdate(unittest.TestCase):
    @patch("lib.cluster_update._maintenance_report", return_value=_maintenance_report())
    @patch("lib.cluster_update.prepare_validated_runtime_config")
    @patch("lib.cluster_update.load_setup_command")
    def test_preflight_failure_aborts_without_changes(
        self,
        mock_load_setup,
        mock_prepare,
        mock_maintenance,
    ) -> None:
        configs = {
            "pve1": _config("10.0.0.10"),
            "pve2": _config("10.0.0.11"),
        }
        mock_load_setup.side_effect = lambda target: configs.get(target)
        mock_prepare.side_effect = [
            configs["pve1"],
            ValueError("Missing workspace credential 'fileshare'"),
        ]

        with patch("infra_tools._execute_patch_config") as mock_execute:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_cluster_update(["pve1", "pve2"], reboot_timeout=120)

        self.assertEqual(rc, 1)
        self.assertFalse(mock_execute.called)
        output = buf.getvalue()
        self.assertIn("Preflight failed; no systems were changed.", output)
        self.assertIn("Missing workspace credential 'fileshare'", output)

    @patch("lib.cluster_update._reboot_and_wait")
    @patch("lib.cluster_update._maintenance_report")
    @patch("lib.cluster_update.prepare_validated_runtime_config")
    @patch("lib.cluster_update.load_setup_command")
    def test_updates_targets_in_order_and_reboots_when_needed(
        self,
        mock_load_setup,
        mock_prepare,
        mock_maintenance,
        mock_reboot_and_wait,
    ) -> None:
        configs = {
            "pve1": _config("10.0.0.10"),
            "pve2": _config("10.0.0.11"),
        }
        mock_load_setup.side_effect = lambda target: configs.get(target)
        mock_prepare.side_effect = [configs["pve1"], configs["pve2"]]
        mock_maintenance.side_effect = [
            _maintenance_report(),
            _maintenance_report(),
            _maintenance_report(reboot_required=True),
            _maintenance_report(),
            _maintenance_report(),
        ]

        with patch("infra_tools._execute_patch_config", side_effect=[0, 0]) as mock_execute:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_cluster_update(["pve1", "pve2"], reboot_timeout=180)

        self.assertEqual(rc, 0)
        self.assertEqual(
            [call.args[0].host for call in mock_execute.call_args_list],
            ["10.0.0.10", "10.0.0.11"],
        )
        mock_reboot_and_wait.assert_called_once_with(configs["pve1"], 180)
        output = buf.getvalue()
        self.assertIn("UPDATED   pve1 [10.0.0.10] (reboot-required, rebooted)", output)
        self.assertIn("verified", output)
        self.assertIn("UPDATED   pve2 [10.0.0.11] - No reboot required", output)

    @patch("lib.cluster_update._maintenance_report", return_value=_maintenance_report())
    @patch("lib.cluster_update.prepare_validated_runtime_config")
    @patch("lib.cluster_update.load_setup_command")
    def test_failure_skips_remaining_targets(
        self,
        mock_load_setup,
        mock_prepare,
        _mock_maintenance,
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

    @patch("lib.cluster_update._maintenance_report")
    @patch("lib.cluster_update.prepare_validated_runtime_config")
    @patch("lib.cluster_update.load_setup_command")
    def test_unhealthy_node_aborts_before_any_changes(
        self, mock_load_setup, mock_prepare, mock_maintenance
    ) -> None:
        config = _config("10.0.0.10")
        mock_load_setup.return_value = config
        mock_prepare.return_value = config
        mock_maintenance.return_value = _maintenance_report(errors=["Cluster is not quorate"])

        with patch("infra_tools._execute_patch_config") as mock_execute:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_cluster_update(["pve1"])

        self.assertEqual(rc, 1)
        mock_execute.assert_not_called()
        self.assertIn("Cluster is not quorate", buf.getvalue())

    @patch("lib.cluster_update._reboot_and_wait")
    @patch("lib.cluster_update._maintenance_report")
    @patch("lib.cluster_update.prepare_validated_runtime_config")
    @patch("lib.cluster_update.load_setup_command")
    def test_running_guest_blocks_reboot_and_later_nodes(
        self,
        mock_load_setup,
        mock_prepare,
        mock_maintenance,
        mock_reboot_and_wait,
    ) -> None:
        configs = {
            "pve1": _config("10.0.0.10"),
            "pve2": _config("10.0.0.11"),
        }
        mock_load_setup.side_effect = lambda target: configs[target]
        mock_prepare.side_effect = [configs["pve1"], configs["pve2"]]
        running = _maintenance_report(
            running_guests=[
                ContainerInfo(vmid=100, status="running", name="web", guest_type="vm")
            ]
        )
        reboot_blocked = _maintenance_report(
            reboot_required=True,
            running_guests=running.running_guests,
        )
        mock_maintenance.side_effect = [running, _maintenance_report(), reboot_blocked]

        with patch("infra_tools._execute_patch_config", return_value=0) as mock_execute:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_cluster_update(["pve1", "pve2"])

        self.assertEqual(rc, 1)
        self.assertEqual(mock_execute.call_count, 1)
        mock_reboot_and_wait.assert_not_called()
        self.assertIn("Reboot blocked: running guests: 100", buf.getvalue())
        self.assertIn("Skipped after blocked reboot on pve1", buf.getvalue())
