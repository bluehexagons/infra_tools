"""Shared SSH/SCP/rsync command builders."""

from __future__ import annotations

import shlex
from typing import Sequence

from lib.workspace import ensure_workspace_dir, get_known_hosts_path


def shell_join(argv: Sequence[str]) -> str:
    """Quote an argv sequence for remote shell execution."""

    return shlex.join(list(argv))


def chain_remote_commands(commands: Sequence[Sequence[str]]) -> str:
    """Quote and chain multiple remote commands with &&."""

    return " && ".join(shell_join(command) for command in commands)


def get_workspace_known_hosts_path() -> str:
    """Return the active workspace known_hosts path, ensuring the workspace exists."""

    ensure_workspace_dir()
    return get_known_hosts_path()


def build_ssh_command(
    host: str,
    username: str,
    ssh_key: str | None = None,
    *,
    port: int | str | None = None,
    remote_command: str | None = None,
    batch_mode: bool | None = None,
    connect_timeout: int | None = 30,
    server_alive_interval: int | None = 30,
) -> list[str]:
    """Build an SSH command with consistent options."""

    command = ["ssh"]
    if ssh_key:
        command.extend(["-i", ssh_key])
    if port is not None:
        command.extend(["-p", str(port)])

    command.extend(["-o", f"UserKnownHostsFile={get_workspace_known_hosts_path()}"])
    command.extend(["-o", "StrictHostKeyChecking=accept-new"])
    if batch_mode is True:
        command.extend(["-o", "BatchMode=yes"])
    elif batch_mode is False:
        command.extend(["-o", "BatchMode=no"])
    if connect_timeout is not None:
        command.extend(["-o", f"ConnectTimeout={connect_timeout}"])
    if server_alive_interval is not None:
        command.extend(["-o", f"ServerAliveInterval={server_alive_interval}"])

    command.append(f"{username}@{host}")
    if remote_command is not None:
        command.append(remote_command)
    return command


def build_scp_command(
    host: str,
    username: str,
    source_path: str,
    destination_path: str,
    ssh_key: str | None = None,
    *,
    port: int | str | None = None,
    batch_mode: bool | None = True,
    connect_timeout: int | None = 30,
) -> list[str]:
    """Build an SCP command with consistent options."""

    command = ["scp"]
    if ssh_key:
        command.extend(["-i", ssh_key])
    if port is not None:
        command.extend(["-P", str(port)])

    command.extend(["-o", f"UserKnownHostsFile={get_workspace_known_hosts_path()}"])
    command.extend(["-o", "StrictHostKeyChecking=accept-new"])
    if batch_mode is True:
        command.extend(["-o", "BatchMode=yes"])
    elif batch_mode is False:
        command.extend(["-o", "BatchMode=no"])
    if connect_timeout is not None:
        command.extend(["-o", f"ConnectTimeout={connect_timeout}"])

    command.extend([source_path, f"{username}@{host}:{destination_path}"])
    return command


def build_rsync_ssh_transport(
    *,
    ssh_key: str | None = None,
    port: int | str | None = None,
    batch_mode: bool = True,
    connect_timeout: int | None = 30,
) -> str:
    """Build the rsync -e SSH transport string with quoted argv."""

    ssh_command = ["ssh"]
    if ssh_key:
        ssh_command.extend(["-i", ssh_key])
    if port is not None:
        ssh_command.extend(["-p", str(port)])
    ssh_command.extend(["-o", f"UserKnownHostsFile={get_workspace_known_hosts_path()}"])
    ssh_command.extend(["-o", "StrictHostKeyChecking=accept-new"])
    if batch_mode:
        ssh_command.extend(["-o", "BatchMode=yes"])
    if connect_timeout is not None:
        ssh_command.extend(["-o", f"ConnectTimeout={connect_timeout}"])
    return shell_join(ssh_command)
