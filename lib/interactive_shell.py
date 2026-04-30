#!/usr/bin/env python3
"""Top-level interactive REPL for infra_tools.

Provides a small command loop that wraps the saved-configuration helpers
(``list``/``info``/``cmd``/``deploy``/``rm``), the recall/reconstruct
flows, and a handoff into the existing :class:`lib.proxmox_shell.ProxmoxShell`.

The shell is intentionally driver-agnostic: tests construct a shell with
custom ``input_func``/``output_func`` callables to drive sequences
without a TTY.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

try:
    import readline as _readline
    _READLINE_AVAILABLE = True
except ImportError:
    _readline = None  # type: ignore[assignment]
    _READLINE_AVAILABLE = False

_HISTORY_FILE = Path.home() / ".local" / "share" / "infra_tools" / "shell_history"
_HISTORY_MAX_LINES = 1000
_INIT_FILE = Path.home() / ".infra_toolsrc"

InputFn = Callable[[str], str]
OutputFn = Callable[[str], None]


HELP_TEXT = """\
Available commands:
  list/ls [pattern] [--json]  List saved configurations (--json for scripting)
  info [pattern] [--compact]  Show saved configuration details (--compact: one line each)
  cmd [pattern]               Show reconstructed setup commands
  deploy <pattern> [--yes]    Redeploy saved configurations
  rm/remove <pattern> [--yes] Remove saved configurations
  recall <host> [user]        Fetch/reconstruct a remote setup command
  reconstruct [--compact]     Reconstruct local host configuration
  proxmox                     Drop into the proxmox shell
  workspace [path]            Show or change the active workspace
  help                        Show this help text
  quit/exit                   Leave the shell
"""


@dataclass
class ShellState:
    workspace: Optional[str] = None
    history: list[str] = field(default_factory=list)


class InteractiveShell:
    """Small REPL wrapping the main infra_tools management surface."""

    def __init__(
        self,
        *,
        workspace: Optional[str] = None,
        input_func: InputFn = input,
        output_func: OutputFn = print,
    ) -> None:
        self.state = ShellState(workspace=workspace)
        self._input = input_func
        self._output = output_func

    # ------------------------------------------------------------------
    # Public entry points

    def run(self) -> int:
        """Drive the REPL until the user quits or input ends."""
        self._load_readline_history()
        self._run_init_file()
        self._output("infra_tools shell — type 'help' for commands.")
        try:
            return self._run_loop()
        finally:
            self._save_readline_history()

    def _run_loop(self) -> int:
        while True:
            try:
                raw = self._input(self._make_prompt())
            except (EOFError, KeyboardInterrupt):
                self._output("")
                return 0
            line = raw.strip()
            if not line:
                continue
            self.state.history.append(line)
            if line in {"quit", "exit"}:
                return 0
            try:
                self.dispatch(line)
            except ValueError as exc:
                self._output(f"Error: {exc}")

    def dispatch(self, line: str) -> None:
        """Parse and execute a single shell command line."""
        try:
            tokens = shlex.split(line)
        except ValueError as exc:
            raise ValueError(f"Could not parse command: {exc}")
        if not tokens:
            return
        cmd, *args = tokens
        handler = self._handlers().get(cmd)
        if handler is None:
            raise ValueError(
                f"Unknown command '{cmd}'. Type 'help' for the command list."
            )
        handler(args)

    # ------------------------------------------------------------------
    # Internal helpers

    def _make_prompt(self) -> str:
        return "infra_tools> "

    def _run_init_file(self, init_file: Optional[Path] = None) -> None:
        path = init_file if init_file is not None else _INIT_FILE
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except OSError as exc:
            self._output(f"Warning: could not read {path}: {exc}")
            return
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                self.dispatch(stripped)
            except ValueError as exc:
                self._output(f"Init file error ({stripped!r}): {exc}")

    def _load_readline_history(self) -> None:
        if not _READLINE_AVAILABLE or self._input is not input:
            return
        try:
            _readline.read_history_file(_HISTORY_FILE)
        except (FileNotFoundError, OSError):
            pass
        _readline.set_history_length(_HISTORY_MAX_LINES)

    def _save_readline_history(self) -> None:
        if not _READLINE_AVAILABLE or self._input is not input:
            return
        try:
            _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            _readline.write_history_file(_HISTORY_FILE)
        except OSError:
            pass

    def _handlers(self) -> dict[str, Callable[[list[str]], None]]:
        return {
            "help": self._cmd_help,
            "list": self._cmd_list,
            "ls": self._cmd_list,
            "info": self._cmd_info,
            "cmd": self._cmd_command,
            "command": self._cmd_command,
            "deploy": self._cmd_deploy,
            "rm": self._cmd_remove,
            "remove": self._cmd_remove,
            "recall": self._cmd_recall,
            "reconstruct": self._cmd_reconstruct,
            "proxmox": self._cmd_proxmox,
            "workspace": self._cmd_workspace,
        }

    @staticmethod
    def _split_yes_flag(args: list[str]) -> tuple[list[str], bool]:
        yes = any(a in {"-y", "--yes"} for a in args)
        rest = [a for a in args if a not in {"-y", "--yes"}]
        return rest, yes

    def _confirm(self, prompt: str) -> bool:
        try:
            response = self._input(prompt)
        except (EOFError, KeyboardInterrupt):
            self._output("")
            return False
        return response.strip().lower() in {"y", "yes"}

    # ------------------------------------------------------------------
    # Commands

    def _cmd_help(self, args: list[str]) -> None:
        self._output(HELP_TEXT)

    def _cmd_workspace(self, args: list[str]) -> None:
        if not args:
            self._output(
                f"Workspace: {self.state.workspace or '(default)'}"
            )
            return
        if len(args) != 1:
            raise ValueError("Usage: workspace [path]")
        from lib.workspace import set_workspace_dir
        from lib.validation import validate_workspace_dir
        try:
            validate_workspace_dir(args[0])
        except ValueError as exc:
            raise ValueError(str(exc))
        set_workspace_dir(args[0])
        self.state.workspace = args[0]
        self._output(f"Workspace set to {args[0]}")

    def _cmd_list(self, args: list[str]) -> None:
        from infra_tools import list_configurations
        json_output = "--json" in args
        rest = [a for a in args if a != "--json"]
        pattern = rest[0] if rest else None
        list_configurations(pattern, json_output=json_output)

    def _cmd_info(self, args: list[str]) -> None:
        from infra_tools import show_info
        compact = "--compact" in args
        rest = [a for a in args if a != "--compact"]
        pattern = rest[0] if rest else None
        show_info(pattern, compact=compact)

    def _cmd_command(self, args: list[str]) -> None:
        from infra_tools import show_command
        pattern = args[0] if args else None
        show_command(pattern)

    def _cmd_deploy(self, args: list[str]) -> None:
        rest, yes = self._split_yes_flag(args)
        if len(rest) != 1:
            raise ValueError("Usage: deploy <pattern> [--yes]")
        from infra_tools import deploy_configurations
        deploy_configurations(rest[0], yes)

    def _cmd_remove(self, args: list[str]) -> None:
        rest, yes = self._split_yes_flag(args)
        if len(rest) != 1:
            raise ValueError("Usage: rm <pattern> [--yes]")
        from infra_tools import remove_configurations
        remove_configurations(rest[0], yes)

    def _cmd_recall(self, args: list[str]) -> None:
        if len(args) < 1 or len(args) > 2:
            raise ValueError("Usage: recall <host> [username]")
        from lib.recall import run_recall_command
        from lib.system_utils import get_current_username
        from lib.validators import validate_host, validate_username
        host = args[0]
        username = args[1] if len(args) == 2 else get_current_username()
        if not validate_host(host):
            raise ValueError(f"Invalid IP address or hostname: {host}")
        if not validate_username(username):
            raise ValueError(f"Invalid username: {username}")
        run_recall_command(host, username, None)

    def _cmd_reconstruct(self, args: list[str]) -> None:
        compact = "--compact" in args or "-c" in args
        from lib.reconstruct import run_reconstruct_command
        run_reconstruct_command(compact)

    def _cmd_proxmox(self, args: list[str]) -> None:
        if args:
            raise ValueError("Usage: proxmox (drops into the proxmox shell)")
        from lib.proxmox_shell import run_proxmox_shell
        run_proxmox_shell(self.state.workspace)


def run_interactive_shell(workspace: Optional[str] = None) -> int:
    """Entry point used by the CLI ``shell`` subcommand."""
    shell = InteractiveShell(workspace=workspace)
    return shell.run()


__all__ = ["InteractiveShell", "ShellState", "run_interactive_shell"]
