"""Tests for controller-verified live network handoffs."""

from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from lib.config import SetupConfig
from lib.network_transition import finish_network_transition, network_transition_targets


def _config(**overrides: object) -> SetupConfig:
    values: dict[str, object] = {
        "host": "192.168.10.20",
        "username": "admin",
        "system_type": "server_lite",
        "static_ipv4": "192.168.10.21/24",
        "activate_network": True,
    }
    values.update(overrides)
    return SetupConfig(**values)  # type: ignore[arg-type]


def _result(returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["ssh"], returncode, "", stderr)


class TestNetworkTransitionTargets(unittest.TestCase):
    def test_prefers_ipv4_and_normalizes_dual_stack_targets(self) -> None:
        config = _config(static_ipv6="2001:db8:10::21/64")

        self.assertEqual(
            network_transition_targets(config),
            ["192.168.10.21", "2001:db8:10::21"],
        )


class TestFinishNetworkTransition(unittest.TestCase):
    @patch("lib.network_transition._run_transition_ssh", return_value=_result())
    @patch("lib.network_transition._wait_for_transition_ssh", return_value=_result())
    def test_verifies_before_and_after_commit_then_adopts_new_host(
        self,
        mock_wait,
        mock_run,
    ) -> None:
        config = _config()

        result = finish_network_transition(config, 0)

        self.assertEqual(result, 0)
        self.assertEqual(config.host, "192.168.10.21")
        self.assertEqual(mock_wait.call_count, 2)
        self.assertIn("--commit-transition", mock_run.call_args.args[2])

    @patch("lib.network_transition.apply_proxmox_network_plan")
    @patch("lib.network_transition.prepare_proxmox_network_plan")
    @patch("lib.network_transition._run_transition_ssh", return_value=_result())
    @patch("lib.network_transition._wait_for_transition_ssh", return_value=_result())
    def test_updates_proxmox_metadata_between_guest_verification_checks(
        self,
        mock_wait,
        _mock_run,
        mock_prepare,
        mock_apply,
    ) -> None:
        from lib.proxmox_network_transition import ProxmoxNetworkPlan

        config = _config(hosted_node="10.0.0.10", machine_type="unprivileged")
        plan = ProxmoxNetworkPlan(
            node="10.0.0.10",
            user="root",
            ssh_opts=[],
            guest_kind="LXC",
            vmid=101,
            option="net0",
            previous_value="name=eth0,ip=192.168.10.20/24,type=veth",
            requested_value="name=eth0,ip=192.168.10.21/24,type=veth",
        )
        mock_prepare.return_value = plan

        result = finish_network_transition(config, 0)

        self.assertEqual(result, 0)
        mock_prepare.assert_called_once_with(config, "192.168.10.20")
        mock_apply.assert_called_once_with(plan)
        self.assertEqual(mock_wait.call_count, 3)

    @patch("lib.network_transition._abort_transition")
    @patch(
        "lib.network_transition._wait_for_transition_ssh",
        return_value=_result(255, "connection refused"),
    )
    def test_failed_new_address_verification_aborts_without_changing_host(
        self,
        _mock_wait,
        mock_abort,
    ) -> None:
        config = _config()

        result = finish_network_transition(config, 0)

        self.assertEqual(result, 1)
        self.assertEqual(config.host, "192.168.10.20")
        mock_abort.assert_called_once_with(config)

    @patch("lib.network_transition._abort_transition")
    def test_failed_setup_cleans_up_temporary_addresses(self, mock_abort) -> None:
        config = _config()

        self.assertEqual(finish_network_transition(config, 3), 3)
        mock_abort.assert_called_once_with(config)


class TestSavedHostMigration(unittest.TestCase):
    @patch("infra_tools.remove_replaced_setup_cache")
    @patch("infra_tools.save_setup_command")
    @patch("infra_tools.store_cli_credentials")
    def test_successful_patch_saves_only_the_verified_new_host(
        self,
        _mock_credentials,
        mock_save,
        mock_remove,
    ) -> None:
        from infra_tools import _execute_patch_config

        config = _config()
        runtime_config = _config()

        def finish_runtime(runtime: SetupConfig) -> int:
            runtime.host = "192.168.10.21"
            return 0

        with patch(
            "infra_tools._prepare_runtime_config_for_cli",
            return_value=runtime_config,
        ), patch("infra_tools.run_remote_setup", side_effect=finish_runtime):
            result = _execute_patch_config(config)

        self.assertEqual(result, 0)
        self.assertEqual(config.host, "192.168.10.21")
        self.assertFalse(config.activate_network)
        self.assertEqual(mock_save.call_args.args[0].host, "192.168.10.21")
        mock_remove.assert_called_once_with("192.168.10.20", "192.168.10.21")


if __name__ == "__main__":
    unittest.main()
