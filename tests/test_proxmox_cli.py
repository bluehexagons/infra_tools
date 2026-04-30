"""Tests for lib/proxmox_cli.py: argparse wiring and command dispatch."""

from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.proxmox_cli import add_proxmox_subparser, run_proxmox_command
from lib.proxmox_hosts import ProxmoxHost, add_proxmox_host


def _make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="command")
    add_proxmox_subparser(subs)
    return parser


def _completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["ssh"], returncode=returncode, stdout=stdout, stderr=""
    )


class _CliFixture(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = self._tmp.name
        self.parser = _make_parser()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, *argv: str) -> tuple[int, str]:
        args = self.parser.parse_args(["proxmox", "--workspace", self.workspace, *argv])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = run_proxmox_command(args)
        return rc, buf.getvalue()


class TestProxmoxCliHosts(_CliFixture):
    def test_add_then_list(self) -> None:
        rc, _ = self._run("add", "pve1", "10.0.0.10", "-u", "root", "--description", "primary")
        self.assertEqual(rc, 0)
        rc, out = self._run("hosts")
        self.assertEqual(rc, 0)
        self.assertIn("pve1", out)
        self.assertIn("10.0.0.10", out)
        self.assertIn("primary", out)

    def test_add_duplicate_without_replace_errors(self) -> None:
        self._run("add", "pve1", "10.0.0.10")
        rc, out = self._run("add", "pve1", "10.0.0.99")
        self.assertEqual(rc, 1)
        self.assertIn("already exists", out)

    def test_add_with_replace_overwrites(self) -> None:
        self._run("add", "pve1", "10.0.0.10")
        rc, _ = self._run("add", "pve1", "10.0.0.99", "--replace")
        self.assertEqual(rc, 0)
        rc, out = self._run("hosts")
        self.assertIn("10.0.0.99", out)
        self.assertNotIn("10.0.0.10", out)

    def test_remove_existing_host(self) -> None:
        self._run("add", "pve1", "10.0.0.10")
        rc, out = self._run("remove", "pve1")
        self.assertEqual(rc, 0)
        self.assertIn("Removed", out)

    def test_remove_missing_host_returns_failure(self) -> None:
        rc, out = self._run("remove", "missing")
        self.assertEqual(rc, 1)
        self.assertIn("No Proxmox host", out)


class TestProxmoxCliContainerOps(_CliFixture):
    def setUp(self) -> None:
        super().setUp()
        add_proxmox_host(
            ProxmoxHost(name="pve1", address="10.0.0.10"), self.workspace
        )

    @patch("lib.proxmox_manage._ssh_run")
    def test_ls_lists_containers(self, mock_run) -> None:
        mock_run.return_value = _completed(
            "VMID Status Name\n100 running web\n"
        )
        rc, out = self._run("ls", "pve1")
        self.assertEqual(rc, 0)
        self.assertIn("100", out)
        self.assertIn("web", out)

    @patch("lib.proxmox_manage._ssh_run")
    def test_status_prints_value(self, mock_run) -> None:
        mock_run.return_value = _completed("status: running\n")
        rc, out = self._run("status", "pve1", "100")
        self.assertEqual(rc, 0)
        self.assertIn("running", out)

    @patch("lib.proxmox_manage._ssh_run")
    def test_start_runs_pct_start(self, mock_run) -> None:
        mock_run.side_effect = [
            _completed("status: stopped\n"),
            _completed(""),
        ]
        rc, _ = self._run("start", "pve1", "100")
        self.assertEqual(rc, 0)
        self.assertIn("pct start 100", mock_run.call_args_list[1].args[3])

    @patch("lib.proxmox_manage._ssh_run")
    def test_stop_force(self, mock_run) -> None:
        mock_run.side_effect = [
            _completed("status: running\n"),
            _completed(""),
        ]
        rc, _ = self._run("stop", "pve1", "100", "--force")
        self.assertEqual(rc, 0)
        self.assertIn("pct stop 100", mock_run.call_args_list[-1].args[3])

    @patch("lib.proxmox_manage._ssh_run")
    def test_destroy_yes_skips_prompt(self, mock_run) -> None:
        mock_run.side_effect = [
            _completed("status: stopped\n"),
            _completed(""),
        ]
        rc, out = self._run("destroy", "pve1", "100", "-y")
        self.assertEqual(rc, 0)
        self.assertIn("Destroyed container 100", out)

    @patch("lib.proxmox_manage._ssh_run")
    @patch("builtins.input", return_value="no")
    def test_destroy_no_yes_prompts_and_aborts(self, mock_input, mock_run) -> None:
        rc, out = self._run("destroy", "pve1", "100")
        self.assertEqual(rc, 1)
        self.assertIn("Aborted", out)
        # Should not have run pct destroy.
        for call in mock_run.call_args_list:
            self.assertNotIn("destroy", call.args[3])

    @patch("lib.proxmox_manage._ssh_run")
    @patch("builtins.input", return_value="yes")
    def test_destroy_no_yes_prompts_and_proceeds(self, mock_input, mock_run) -> None:
        mock_run.side_effect = [
            _completed("status: stopped\n"),
            _completed(""),
        ]
        rc, _ = self._run("destroy", "pve1", "100")
        self.assertEqual(rc, 0)
        self.assertIn("pct destroy 100", mock_run.call_args_list[-1].args[3])

    @patch("lib.proxmox_manage._ssh_run")
    def test_health_returns_zero_when_healthy(self, mock_run) -> None:
        mock_run.side_effect = [
            _completed("status: running\n"),
            _completed("net0: name=eth0,bridge=vmbr0,ip=10.0.0.50/24\n"),
            _completed("OK\n"),
            _completed("OK\n"),
        ]
        rc, out = self._run("health", "pve1", "100")
        self.assertEqual(rc, 0)
        self.assertIn("HEALTHY", out)

    @patch("lib.proxmox_manage._ssh_run")
    def test_health_returns_one_when_unhealthy(self, mock_run) -> None:
        mock_run.return_value = _completed(returncode=2)
        rc, out = self._run("health", "pve1", "100")
        self.assertEqual(rc, 1)
        self.assertIn("UNHEALTHY", out)

    def test_unknown_host_returns_error(self) -> None:
        rc, out = self._run("status", "missing", "100")
        self.assertEqual(rc, 1)
        self.assertIn("No registered Proxmox host", out)


if __name__ == "__main__":
    unittest.main()
