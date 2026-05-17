"""Tests for lib/proxmox_shell.py: REPL command dispatch with mocked I/O."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from typing import Optional
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.proxmox_hosts import ProxmoxHost, add_proxmox_host, load_proxmox_hosts
from lib.proxmox_shell import ProxmoxShell


def _completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["ssh"], returncode=returncode, stdout=stdout, stderr=""
    )


class _ShellFixture(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = self._tmp.name
        self.outputs: list[str] = []
        self.shell = ProxmoxShell(
            workspace=self.workspace,
            input_func=lambda prompt: "",
            output_func=self.outputs.append,
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def assert_output_contains(self, needle: str) -> None:
        joined = "\n".join(self.outputs)
        self.assertIn(needle, joined, f"missing '{needle}' in: {joined}")


class TestShellHostManagement(_ShellFixture):
    def test_add_then_hosts_lists_it(self) -> None:
        self.shell.dispatch("add pve1 10.0.0.10 root")
        self.shell.dispatch("hosts")
        self.assert_output_contains("pve1")
        self.assert_output_contains("10.0.0.10")
        loaded = load_proxmox_hosts(self.workspace)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].name, "pve1")

    def test_use_selects_active_host(self) -> None:
        self.shell.dispatch("add pve1 10.0.0.10")
        self.shell.dispatch("use pve1")
        self.assertIsNotNone(self.shell.state.active_host)
        assert self.shell.state.active_host is not None
        self.assertEqual(self.shell.state.active_host.name, "pve1")

    def test_use_unknown_host_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.shell.dispatch("use missing")

    def test_remove_clears_active_host(self) -> None:
        self.shell.dispatch("add pve1 10.0.0.10")
        self.shell.dispatch("use pve1")
        self.shell.dispatch("remove pve1")
        self.assertIsNone(self.shell.state.active_host)
        self.assertEqual(load_proxmox_hosts(self.workspace), [])

    def test_remove_unknown_host_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.shell.dispatch("remove missing")


class TestShellRequiresActiveHost(_ShellFixture):
    def test_ls_without_host_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.shell.dispatch("ls")

    def test_status_without_host_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.shell.dispatch("status 100")


class TestShellContainerOps(_ShellFixture):
    def setUp(self) -> None:
        super().setUp()
        add_proxmox_host(
            ProxmoxHost(name="pve1", address="10.0.0.10"), self.workspace
        )
        self.shell.dispatch("use pve1")
        self.outputs.clear()

    @patch("lib.proxmox_manage._ssh_run")
    def test_ls_lists_containers(self, mock_run) -> None:
        mock_run.side_effect = [
            _completed("VMID Status Name\n100 running web\n101 stopped db\n"),
            _completed("VMID NAME STATUS MEM(MB) BOOTDISK(GB) PID\n"),
        ]
        self.shell.dispatch("ls")
        self.assert_output_contains("100")
        self.assert_output_contains("web")
        self.assert_output_contains("101")
        self.assert_output_contains("lxc")

    @patch("lib.proxmox_manage._ssh_run")
    def test_ls_when_empty_says_so(self, mock_run) -> None:
        mock_run.side_effect = [
            _completed("VMID Status Name\n"),
            _completed("VMID NAME STATUS MEM(MB) BOOTDISK(GB) PID\n"),
        ]
        self.shell.dispatch("ls")
        self.assert_output_contains("(no guests)")

    @patch("lib.proxmox_manage._ssh_run")
    def test_status_dispatch(self, mock_run) -> None:
        mock_run.return_value = _completed("status: running\n")
        self.shell.dispatch("status 100")
        self.assert_output_contains("VMID 100")
        self.assert_output_contains("running")

    @patch("lib.proxmox_manage._ssh_run")
    def test_start_dispatch(self, mock_run) -> None:
        mock_run.side_effect = [
            _completed("status: stopped\n"),
            _completed(""),
        ]
        self.shell.dispatch("start 100")
        self.assert_output_contains("Started guest 100")

    @patch("lib.proxmox_manage._ssh_run")
    def test_stop_default_uses_shutdown(self, mock_run) -> None:
        mock_run.side_effect = [
            _completed("status: running\n"),
            _completed(""),
        ]
        self.shell.dispatch("stop 100")
        executed = [c.args[3] for c in mock_run.call_args_list]
        self.assertIn("pct shutdown 100", executed)

    @patch("lib.proxmox_manage._ssh_run")
    def test_stop_force_uses_pct_stop(self, mock_run) -> None:
        mock_run.side_effect = [
            _completed("status: running\n"),
            _completed(""),
        ]
        self.shell.dispatch("stop 100 --force")
        executed = [c.args[3] for c in mock_run.call_args_list]
        self.assertIn("pct stop 100", executed)

    @patch("lib.proxmox_manage._ssh_run")
    def test_health_dispatch_reports_status(self, mock_run) -> None:
        mock_run.side_effect = [
            _completed("status: running\n"),
            _completed("net0: name=eth0,bridge=vmbr0,ip=10.0.0.50/24\n"),
            _completed("OK\n"),
            _completed("OK\n"),
        ]
        self.shell.dispatch("health 100")
        self.assert_output_contains("HEALTHY")
        self.assert_output_contains("10.0.0.50")


class TestShellDestroyConfirmation(_ShellFixture):
    def setUp(self) -> None:
        super().setUp()
        add_proxmox_host(
            ProxmoxHost(name="pve1", address="10.0.0.10"), self.workspace
        )
        self.confirm_calls: list[bool] = []
        self.shell = ProxmoxShell(
            workspace=self.workspace,
            input_func=lambda prompt: "",
            output_func=self.outputs.append,
            confirm_destroy=self._record_confirm,
        )
        self.shell.dispatch("use pve1")
        self.outputs.clear()

    def _record_confirm(self, info, host) -> bool:
        self.confirm_calls.append(True)
        return self._confirm_response

    @patch("lib.proxmox_manage._ssh_run")
    def test_destroy_calls_confirm_and_proceeds_on_yes(self, mock_run) -> None:
        self._confirm_response = True
        mock_run.side_effect = [
            _completed("VMID Status Name\n100 stopped web\n"),  # pct list
            _completed("VMID NAME STATUS MEM(MB) BOOTDISK(GB) PID\n"),  # qm list
            _completed("status: stopped\n"),                     # status pre-destroy
            _completed(""),                                       # destroy
        ]
        self.shell.dispatch("destroy 100")
        self.assertEqual(self.confirm_calls, [True])
        self.assert_output_contains("Destroyed guest 100")

    @patch("lib.proxmox_manage._ssh_run")
    def test_destroy_aborts_when_confirm_false(self, mock_run) -> None:
        self._confirm_response = False
        mock_run.side_effect = [
            _completed("VMID Status Name\n100 stopped web\n"),
            _completed("VMID NAME STATUS MEM(MB) BOOTDISK(GB) PID\n"),
        ]
        self.shell.dispatch("destroy 100")
        self.assert_output_contains("cancelled")
        # Only the list_containers call should have happened.
        self.assertEqual(mock_run.call_count, 2)

    @patch("lib.proxmox_manage._ssh_run")
    def test_destroy_unknown_vmid_raises(self, mock_run) -> None:
        mock_run.side_effect = [
            _completed("VMID Status Name\n"),
            _completed("VMID NAME STATUS MEM(MB) BOOTDISK(GB) PID\n"),
        ]
        with self.assertRaises(ValueError):
            self.shell.dispatch("destroy 999")


class TestShellMisc(_ShellFixture):
    def test_help_lists_commands(self) -> None:
        self.shell.dispatch("help")
        self.assert_output_contains("destroy")
        self.assert_output_contains("health")

    def test_unknown_command_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.shell.dispatch("nonsense")

    def test_run_quits_on_eof(self) -> None:
        def raising_input(prompt: str) -> str:
            raise EOFError
        shell = ProxmoxShell(
            workspace=self.workspace,
            input_func=raising_input,
            output_func=self.outputs.append,
        )
        self.assertEqual(shell.run(), 0)

    def test_run_executes_then_quits(self) -> None:
        scripted = iter(["help", "quit"])
        shell = ProxmoxShell(
            workspace=self.workspace,
            input_func=lambda prompt: next(scripted),
            output_func=self.outputs.append,
        )
        self.assertEqual(shell.run(), 0)
        self.assert_output_contains("destroy")

    def test_invalid_vmid_raises(self) -> None:
        add_proxmox_host(
            ProxmoxHost(name="pve1", address="10.0.0.10"), self.workspace
        )
        self.shell.dispatch("use pve1")
        with self.assertRaises(ValueError):
            self.shell.dispatch("status notanumber")
        with self.assertRaises(ValueError):
            self.shell.dispatch("status -1")


class TestShellLifecycleCommands(_ShellFixture):
    def setUp(self) -> None:
        super().setUp()
        add_proxmox_host(
            ProxmoxHost(name="pve1", address="10.0.0.10"), self.workspace
        )
        self.shell.dispatch("use pve1")

    @patch("lib.proxmox_manage._ssh_run")
    def test_config_dispatch(self, mock_run) -> None:
        mock_run.return_value = _completed("cores: 2\nmemory: 2048\n")
        self.shell.dispatch("config 100")
        self.assert_output_contains("cores")
        self.assert_output_contains("2048")

    @patch("lib.proxmox_manage._ssh_run")
    def test_config_pending_flag(self, mock_run) -> None:
        mock_run.return_value = _completed("cores: 4\n")
        self.shell.dispatch("config 100 --pending")
        self.assert_output_contains("Pending")
        self.assertIn("pct pending", mock_run.call_args.args[3])

    @patch("lib.proxmox_manage._ssh_run")
    def test_set_dispatch(self, mock_run) -> None:
        mock_run.return_value = _completed()
        self.shell.dispatch("set 100 hostname=newbox")
        self.assert_output_contains("Set 1 option")
        self.assertIn("--hostname", mock_run.call_args.args[3])

    def test_set_without_options_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.shell.dispatch("set 100")

    def test_set_bad_format_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.shell.dispatch("set 100 notakeyvalue")

    @patch("lib.proxmox_manage._ssh_run")
    def test_modify_cores(self, mock_run) -> None:
        mock_run.return_value = _completed()
        self.shell.dispatch("modify 100 --cores 4")
        self.assert_output_contains("cores=4")
        self.assertIn("--cores", mock_run.call_args.args[3])

    @patch("lib.proxmox_manage._ssh_run")
    def test_modify_memory_g_suffix(self, mock_run) -> None:
        mock_run.return_value = _completed()
        self.shell.dispatch("modify 100 --memory 2G")
        self.assert_output_contains("memory=2048M")
        self.assertIn("2048", mock_run.call_args.args[3])

    def test_modify_no_flags_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.shell.dispatch("modify 100")

    @patch("lib.proxmox_manage._ssh_run")
    def test_resize_dispatch(self, mock_run) -> None:
        mock_run.return_value = _completed()
        self.shell.dispatch("resize 100 rootfs 20G")
        self.assert_output_contains("Resized rootfs")
        cmd = mock_run.call_args.args[3]
        self.assertIn("pct resize", cmd)
        self.assertIn("rootfs", cmd)
        self.assertIn("20G", cmd)

    def test_resize_wrong_arg_count_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.shell.dispatch("resize 100 rootfs")


if __name__ == "__main__":
    unittest.main()
