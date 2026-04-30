"""Tests for the top-level infra_tools interactive shell."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.interactive_shell import InteractiveShell, run_interactive_shell


def _make_shell(commands: list[str]) -> tuple[InteractiveShell, list[str]]:
    inputs = iter(commands)
    output: list[str] = []

    def _input(_prompt: str) -> str:
        try:
            return next(inputs)
        except StopIteration:
            raise EOFError()

    shell = InteractiveShell(input_func=_input, output_func=output.append)
    return shell, output


class TestInteractiveShellDispatch(unittest.TestCase):
    def test_help_prints_command_list(self):
        shell, output = _make_shell(["help", "exit"])
        self.assertEqual(shell.run(), 0)
        joined = "\n".join(output)
        self.assertIn("Available commands", joined)
        self.assertIn("proxmox", joined)
        self.assertIn("recall", joined)

    def test_unknown_command_reports_error(self):
        shell, output = _make_shell(["bogus", "exit"])
        self.assertEqual(shell.run(), 0)
        self.assertTrue(any("Unknown command 'bogus'" in line for line in output))

    def test_exit_returns_zero(self):
        shell, _ = _make_shell(["exit"])
        self.assertEqual(shell.run(), 0)

    def test_eof_returns_zero(self):
        shell, _ = _make_shell([])
        self.assertEqual(shell.run(), 0)

    def test_blank_lines_skip(self):
        shell, output = _make_shell(["", "   ", "help", "exit"])
        self.assertEqual(shell.run(), 0)
        self.assertTrue(any("Available commands" in line for line in output))

    @patch("infra_tools.list_configurations")
    def test_list_invokes_list_configurations(self, mock_list):
        shell, _ = _make_shell(["list prod", "exit"])
        shell.run()
        mock_list.assert_called_once_with("prod", json_output=False)

    @patch("infra_tools.list_configurations")
    def test_list_without_pattern_passes_none(self, mock_list):
        shell, _ = _make_shell(["ls", "exit"])
        shell.run()
        mock_list.assert_called_once_with(None, json_output=False)

    @patch("infra_tools.list_configurations")
    def test_list_json_flag_passes_true(self, mock_list):
        shell, _ = _make_shell(["list --json", "exit"])
        shell.run()
        mock_list.assert_called_once_with(None, json_output=True)

    @patch("infra_tools.show_info")
    def test_info_invokes_show_info(self, mock_show):
        shell, _ = _make_shell(["info web", "exit"])
        shell.run()
        mock_show.assert_called_once_with("web", compact=False)

    @patch("infra_tools.show_info")
    def test_info_compact_flag(self, mock_show):
        shell, _ = _make_shell(["info --compact", "exit"])
        shell.run()
        mock_show.assert_called_once_with(None, compact=True)

    @patch("infra_tools.show_command")
    def test_cmd_invokes_show_command(self, mock_show):
        shell, _ = _make_shell(["cmd web", "exit"])
        shell.run()
        mock_show.assert_called_once_with("web")

    @patch("infra_tools.deploy_configurations")
    def test_deploy_requires_pattern(self, mock_deploy):
        shell, output = _make_shell(["deploy", "exit"])
        shell.run()
        mock_deploy.assert_not_called()
        self.assertTrue(any("Usage: deploy" in line for line in output))

    @patch("infra_tools.deploy_configurations")
    def test_deploy_passes_yes_flag(self, mock_deploy):
        shell, _ = _make_shell(["deploy prod --yes", "exit"])
        shell.run()
        mock_deploy.assert_called_once_with("prod", True)

    @patch("infra_tools.remove_configurations")
    def test_remove_passes_short_yes_flag(self, mock_remove):
        shell, _ = _make_shell(["rm web -y", "exit"])
        shell.run()
        mock_remove.assert_called_once_with("web", True)

    @patch("lib.proxmox_shell.run_proxmox_shell")
    def test_proxmox_drops_into_proxmox_shell(self, mock_run_shell):
        mock_run_shell.return_value = 0
        shell, _ = _make_shell(["proxmox", "exit"])
        shell.run()
        mock_run_shell.assert_called_once_with(None)

    def test_recall_rejects_invalid_host(self):
        shell, output = _make_shell(["recall '%bad host'", "exit"])
        shell.run()
        self.assertTrue(any("Invalid IP address or hostname" in line for line in output))

    @patch("lib.reconstruct.run_reconstruct_command", return_value=0)
    def test_reconstruct_passes_compact_flag(self, mock_run):
        shell, _ = _make_shell(["reconstruct --compact", "exit"])
        shell.run()
        mock_run.assert_called_once_with(True)

    def test_workspace_without_arg_prints_default(self):
        shell, output = _make_shell(["workspace", "exit"])
        shell.run()
        self.assertTrue(any("Workspace:" in line for line in output))


class TestRunInteractiveShellEntry(unittest.TestCase):
    @patch("lib.interactive_shell.InteractiveShell.run", return_value=0)
    def test_run_interactive_shell_invokes_shell(self, mock_run):
        self.assertEqual(run_interactive_shell(workspace="/tmp/ws"), 0)
        mock_run.assert_called_once()


class TestInteractiveShellInitFile(unittest.TestCase):
    def test_init_file_commands_run_at_startup(self):
        import tempfile
        from pathlib import Path
        outputs: list[str] = []
        shell = InteractiveShell(
            input_func=lambda _p: (_ for _ in ()).throw(EOFError()),
            output_func=outputs.append,
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".rc", delete=False) as f:
            f.write("help\n")
            rc_path = Path(f.name)
        try:
            shell._run_init_file(rc_path)
        finally:
            rc_path.unlink(missing_ok=True)
        self.assertTrue(any("Available commands" in line for line in outputs))

    def test_init_file_skips_comments_and_blank_lines(self):
        import tempfile
        from pathlib import Path
        outputs: list[str] = []
        shell = InteractiveShell(
            input_func=lambda _p: (_ for _ in ()).throw(EOFError()),
            output_func=outputs.append,
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".rc", delete=False) as f:
            f.write("# this is a comment\n\n   \n")
            rc_path = Path(f.name)
        try:
            shell._run_init_file(rc_path)
        finally:
            rc_path.unlink(missing_ok=True)
        self.assertEqual(outputs, [])

    def test_init_file_missing_is_silent(self):
        from pathlib import Path
        outputs: list[str] = []
        shell = InteractiveShell(
            input_func=lambda _p: (_ for _ in ()).throw(EOFError()),
            output_func=outputs.append,
        )
        shell._run_init_file(Path("/nonexistent/no/such/file.rc"))
        self.assertEqual(outputs, [])

    def test_init_file_errors_reported_gracefully(self):
        import tempfile
        from pathlib import Path
        outputs: list[str] = []
        shell = InteractiveShell(
            input_func=lambda _p: (_ for _ in ()).throw(EOFError()),
            output_func=outputs.append,
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".rc", delete=False) as f:
            f.write("unknown_command_xyz\n")
            rc_path = Path(f.name)
        try:
            shell._run_init_file(rc_path)
        finally:
            rc_path.unlink(missing_ok=True)
        self.assertTrue(any("Init file error" in line for line in outputs))


if __name__ == "__main__":
    unittest.main()
