#!/usr/bin/env python3
"""Interactive command-line shell for managing Proxmox-hosted containers.

Designed to feel like a small REPL on top of :mod:`lib.proxmox_manage` and
:mod:`lib.proxmox_hosts`. The shell starts with no host selected; ``use``
chooses one from the workspace registry, then commands like ``ls``, ``status``,
``start``, ``stop``, ``destroy``, and ``health`` operate on it.

The shell is fully driver-agnostic: tests construct one with a custom
``input_func``/``output_func`` to drive command sequences without a TTY.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from typing import Callable, Optional

from lib.proxmox_hosts import (
    ProxmoxHost,
    add_proxmox_host,
    find_proxmox_host,
    load_proxmox_hosts,
    remove_proxmox_host,
)
from lib.proxmox_manage import (
    ContainerInfo,
    HealthReport,
    ProxmoxManageError,
    destroy_container,
    health_check,
    list_containers,
    start_container,
    stop_container,
)


InputFn = Callable[[str], str]
OutputFn = Callable[[str], None]


HELP_TEXT = """\
Available commands:
  hosts                       List registered Proxmox hosts
  use <name|address>          Select a host for subsequent commands
  add <name> <addr> [user] [key]
                              Register a new Proxmox host
  remove <name|address>       Remove a host from the registry
  ls                          List containers on the active host
  status <vmid>               Show container status
  start <vmid>                Start a container
  stop <vmid> [--force]       Shutdown (or force-stop) a container
  destroy <vmid> [--force]    Destroy a container (asks for confirmation)
  health <vmid>               Run a health check
  help                        Show this help text
  quit / exit                 Leave the shell
"""


def _format_host_row(host: ProxmoxHost) -> str:
    bits = [host.name, host.address, host.user]
    if host.description:
        bits.append(f"({host.description})")
    return "  " + " | ".join(bits)


def _format_container_row(info: ContainerInfo) -> str:
    parts = [
        f"{info.vmid:>6}",
        f"{info.status:<10}",
        f"{(info.lock or '-'):<10}",
        info.name or "-",
    ]
    return "  " + " ".join(parts)


def _format_health(report: HealthReport) -> str:
    state = "HEALTHY" if report.healthy else "UNHEALTHY"
    lines = [
        f"  VMID:    {report.vmid}",
        f"  Status:  {report.status}",
        f"  IP:      {report.ip or 'n/a'}",
        f"  Ping:    {_tristate(report.pingable)}",
        f"  SSH:22:  {_tristate(report.ssh_open)}",
        f"  Result:  {state}",
    ]
    for note in report.notes:
        lines.append(f"  Note:    {note}")
    return "\n".join(lines)


def _tristate(value: Optional[bool]) -> str:
    if value is None:
        return "skipped"
    return "ok" if value else "fail"


@dataclass
class ShellState:
    workspace: Optional[str] = None
    active_host: Optional[ProxmoxHost] = None
    history: list[str] = field(default_factory=list)


class ProxmoxShell:
    """Small REPL wrapper around the Proxmox management helpers."""

    def __init__(
        self,
        *,
        workspace: Optional[str] = None,
        input_func: InputFn = input,
        output_func: OutputFn = print,
        confirm_destroy: Optional[Callable[[ContainerInfo, ProxmoxHost], bool]] = None,
    ) -> None:
        self.state = ShellState(workspace=workspace)
        self._input = input_func
        self._output = output_func
        self._confirm_destroy = confirm_destroy or self._default_confirm_destroy

    # ------------------------------------------------------------------
    # Public entry points

    def run(self) -> int:
        """Drive the REPL until the user quits or input ends."""
        self._output("infra_tools proxmox shell — type 'help' for commands.")
        while True:
            prompt = self._make_prompt()
            try:
                raw = self._input(prompt)
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
            except ProxmoxManageError as exc:
                self._output(f"Error: {exc}")
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

    def _handlers(self) -> dict[str, Callable[[list[str]], None]]:
        return {
            "help": self._cmd_help,
            "hosts": self._cmd_hosts,
            "use": self._cmd_use,
            "add": self._cmd_add,
            "remove": self._cmd_remove,
            "rm": self._cmd_remove,
            "ls": self._cmd_ls,
            "list": self._cmd_ls,
            "status": self._cmd_status,
            "start": self._cmd_start,
            "stop": self._cmd_stop,
            "destroy": self._cmd_destroy,
            "rmct": self._cmd_destroy,
            "health": self._cmd_health,
            "check": self._cmd_health,
        }

    def _make_prompt(self) -> str:
        if self.state.active_host:
            return f"proxmox[{self.state.active_host.name}]> "
        return "proxmox> "

    def _require_host(self) -> ProxmoxHost:
        if not self.state.active_host:
            raise ValueError(
                "No active host. Use 'hosts' to list and 'use <name>' to select one."
            )
        return self.state.active_host

    @staticmethod
    def _default_confirm_destroy(
        info: ContainerInfo, host: ProxmoxHost
    ) -> bool:
        prompt = (
            f"Destroy container {info.vmid} '{info.name}' on {host.name} "
            f"({host.address})? Type 'yes' to confirm: "
        )
        try:
            response = input(prompt)
        except (EOFError, KeyboardInterrupt):
            return False
        return response.strip().lower() == "yes"

    # ------------------------------------------------------------------
    # Commands

    def _cmd_help(self, args: list[str]) -> None:
        self._output(HELP_TEXT)

    def _cmd_hosts(self, args: list[str]) -> None:
        hosts = load_proxmox_hosts(self.state.workspace)
        if not hosts:
            self._output("No Proxmox hosts registered. Use 'add <name> <addr>'.")
            return
        self._output("Registered Proxmox hosts:")
        for host in hosts:
            marker = "*" if (
                self.state.active_host
                and self.state.active_host.name == host.name
            ) else " "
            self._output(marker + _format_host_row(host))

    def _cmd_use(self, args: list[str]) -> None:
        if len(args) != 1:
            raise ValueError("Usage: use <name|address>")
        host = find_proxmox_host(args[0], self.state.workspace)
        if not host:
            raise ValueError(f"No registered host matching '{args[0]}'")
        self.state.active_host = host
        self._output(f"Using {host.name} ({host.address})")

    def _cmd_add(self, args: list[str]) -> None:
        if len(args) < 2 or len(args) > 4:
            raise ValueError(
                "Usage: add <name> <address> [user] [ssh_key_path]"
            )
        name, address = args[0], args[1]
        user = args[2] if len(args) >= 3 else "root"
        ssh_key = args[3] if len(args) == 4 else None
        host = ProxmoxHost(
            name=name, address=address, user=user, ssh_key=ssh_key
        )
        add_proxmox_host(host, self.state.workspace, replace=True)
        self._output(f"Saved host {name} ({address}) as user {user}.")

    def _cmd_remove(self, args: list[str]) -> None:
        if len(args) != 1:
            raise ValueError("Usage: remove <name|address>")
        target = args[0]
        removed = remove_proxmox_host(target, self.state.workspace)
        if not removed:
            raise ValueError(f"No registered host matching '{target}'")
        if (
            self.state.active_host
            and (
                self.state.active_host.name.lower() == target.lower()
                or self.state.active_host.address == target
            )
        ):
            self.state.active_host = None
        self._output(f"Removed host '{target}'.")

    def _cmd_ls(self, args: list[str]) -> None:
        host = self._require_host()
        rows = list_containers(host)
        if not rows:
            self._output("(no containers)")
            return
        self._output(
            f"  {'VMID':>6} {'Status':<10} {'Lock':<10} Name"
        )
        for row in rows:
            self._output(_format_container_row(row))

    def _cmd_status(self, args: list[str]) -> None:
        host = self._require_host()
        vmid = self._parse_vmid(args, "status")
        from lib.proxmox_manage import get_container_status
        status = get_container_status(host, vmid)
        self._output(f"  VMID {vmid}: {status}")

    def _cmd_start(self, args: list[str]) -> None:
        host = self._require_host()
        vmid = self._parse_vmid(args, "start")
        start_container(host, vmid)
        self._output(f"  Started container {vmid} on {host.name}.")

    def _cmd_stop(self, args: list[str]) -> None:
        host = self._require_host()
        force = "--force" in args
        rest = [a for a in args if a != "--force"]
        vmid = self._parse_vmid(rest, "stop")
        stop_container(host, vmid, force=force)
        self._output(
            f"  {'Stopped' if force else 'Shut down'} container {vmid} on {host.name}."
        )

    def _cmd_destroy(self, args: list[str]) -> None:
        host = self._require_host()
        force = "--force" in args
        rest = [a for a in args if a != "--force"]
        vmid = self._parse_vmid(rest, "destroy")
        # Look up the container so the confirmation prompt has its name.
        info: Optional[ContainerInfo] = None
        for row in list_containers(host):
            if row.vmid == vmid:
                info = row
                break
        if info is None:
            raise ValueError(
                f"No container with VMID {vmid} on {host.name}"
            )
        if not self._confirm_destroy(info, host):
            self._output("  Destroy cancelled.")
            return
        destroy_container(host, vmid, force=force)
        self._output(f"  Destroyed container {vmid} on {host.name}.")

    def _cmd_health(self, args: list[str]) -> None:
        host = self._require_host()
        vmid = self._parse_vmid(args, "health")
        report = health_check(host, vmid)
        self._output(_format_health(report))

    @staticmethod
    def _parse_vmid(args: list[str], cmd: str) -> int:
        if len(args) != 1:
            raise ValueError(f"Usage: {cmd} <vmid>")
        try:
            vmid = int(args[0])
        except ValueError:
            raise ValueError(f"VMID must be an integer, got '{args[0]}'")
        if vmid <= 0:
            raise ValueError(f"VMID must be positive, got {vmid}")
        return vmid


def run_proxmox_shell(workspace: Optional[str] = None) -> int:
    """Entry point used by the CLI ``proxmox`` subcommand without args."""
    shell = ProxmoxShell(workspace=workspace)
    return shell.run()
