"""Shared SSH/SCP/rsync command builders."""

from __future__ import annotations

import hashlib
import os
import shlex
import subprocess
import sys
import tempfile
from typing import Sequence

from lib.workspace import ensure_workspace_dir, get_known_hosts_path


def ssh_batch_mode() -> bool:
    """Return whether SSH should fail instead of prompting for input.

    OpenSSH can ask for a passphrase through the controlling terminal even
    when its stdout and stderr are captured.  Keep that behavior for commands
    started from a terminal.  Commands started with redirected stdin cannot
    answer a prompt reliably, so they must use an already-loaded SSH agent (or
    fail clearly instead of hanging).
    """

    return not sys.stdin.isatty()


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


def get_ssh_control_path(
    host: str,
    username: str,
    ssh_key: str | None = None,
) -> str:
    """Return a private, reusable OpenSSH multiplexing socket path.

    A Proxmox inspection command can execute many SSH sessions in sequence.
    Multiplexing lets the first session authenticate an encrypted key and lets
    the remaining sessions reuse that authenticated connection instead of
    prompting for the key passphrase repeatedly.  The short-lived socket is
    stable across adjacent CLI invocations so ``probe`` followed by ``audit``
    can reuse it while OpenSSH's ``ControlPersist`` window is active.
    """
    identity = "\0".join((host, username, ssh_key or ""))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    control_dir = os.path.join(
        tempfile.gettempdir(), f"infra-tools-ssh-{os.getuid()}"
    )
    os.makedirs(control_dir, mode=0o700, exist_ok=True)
    try:
        os.chmod(control_dir, 0o700)
    except OSError:
        pass
    return os.path.join(control_dir, f"{digest}.sock")


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
    control_path: str | None = None,
    allocate_tty: bool = False,
) -> list[str]:
    """Build an SSH command with consistent options."""

    command = ["ssh"]
    if allocate_tty:
        command.append("-tt")
    if ssh_key:
        command.extend(["-i", ssh_key])
    if port is not None:
        command.extend(["-p", str(port)])

    command.extend(["-o", f"UserKnownHostsFile={get_workspace_known_hosts_path()}"])
    command.extend(["-o", "StrictHostKeyChecking=yes"])
    if batch_mode is None:
        batch_mode = ssh_batch_mode()
    if batch_mode is True:
        command.extend(["-o", "BatchMode=yes"])
    elif batch_mode is False:
        command.extend(["-o", "BatchMode=no"])
    if connect_timeout is not None:
        command.extend(["-o", f"ConnectTimeout={connect_timeout}"])
    if server_alive_interval is not None:
        command.extend(["-o", f"ServerAliveInterval={server_alive_interval}"])
    if control_path:
        command.extend([
            "-o", "ControlMaster=auto",
            "-o", "ControlPersist=60s",
            "-o", f"ControlPath={control_path}",
        ])

    command.append(f"{username}@{host}")
    if remote_command is not None:
        command.append(remote_command)
    return command


def ensure_remote_sudo(
    host: str,
    username: str,
    ssh_key: str | None = None,
    *,
    control_path: str | None = None,
    timeout: int = 60,
) -> bool:
    """Verify remote sudo and interactively authenticate when necessary.

    Setup uploads use SSH stdin for a tar stream, so a remote sudo prompt
    cannot safely be allowed to consume that stream. Probe non-interactively
    first; when the caller has a terminal, authenticate with a separate
    terminal-backed ``sudo -v`` session and verify the cached authorization
    before returning.
    """
    if username == "root":
        return True

    probe = build_ssh_command(
        host,
        username,
        ssh_key,
        remote_command="sudo -n true",
        batch_mode=ssh_batch_mode(),
        connect_timeout=30,
        server_alive_interval=30,
        control_path=control_path,
    )
    try:
        result = subprocess.run(
            probe,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"Error: could not verify remote sudo for {username}@{host}: {exc}")
        return False

    if result.returncode == 0:
        return True

    detail = (result.stderr or result.stdout or "").strip()
    if result.returncode == 255:
        print(
            f"Error: could not establish SSH for remote sudo verification "
            f"to {username}@{host}."
        )
        if detail:
            print(f"  SSH check: {detail[:240]}")
        return False
    if not sys.stdin.isatty():
        print(
            f"Error: {username}@{host} does not provide passwordless sudo and "
            "setup has no terminal for a password prompt. Run setup from a "
            "terminal, load the SSH key into ssh-agent, or configure the setup "
            "user with the required NOPASSWD sudo rule."
        )
        if detail:
            print(f"  Remote sudo check: {detail[:240]}")
        return False

    print(
        f"  Remote sudo authentication is required for {username}@{host}; "
        "enter the guest sudo password if prompted."
    )
    authenticate = build_ssh_command(
        host,
        username,
        ssh_key,
        remote_command="sudo -v",
        batch_mode=False,
        connect_timeout=30,
        server_alive_interval=30,
        control_path=control_path,
        allocate_tty=True,
    )
    try:
        auth_result = subprocess.run(authenticate, check=False, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"Error: remote sudo authentication could not run: {exc}")
        return False
    if auth_result.returncode != 0:
        print(
            f"Error: remote sudo authentication failed for {username}@{host} "
            f"(exit {auth_result.returncode})."
        )
        return False

    try:
        verification = subprocess.run(
            probe,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"Error: could not verify remote sudo after authentication: {exc}")
        return False
    if verification.returncode != 0:
        detail = (verification.stderr or verification.stdout or "").strip()
        print(f"Error: remote sudo remains unavailable for {username}@{host}.")
        if detail:
            print(f"  Remote sudo check: {detail[:240]}")
        return False

    print(f"  ✓ Remote sudo access verified for {username}@{host}")
    return True


def build_scp_command(
    host: str,
    username: str,
    source_path: str,
    destination_path: str,
    ssh_key: str | None = None,
    *,
    port: int | str | None = None,
    batch_mode: bool | None = None,
    connect_timeout: int | None = 30,
) -> list[str]:
    """Build an SCP command with consistent options."""

    command = ["scp"]
    if ssh_key:
        command.extend(["-i", ssh_key])
    if port is not None:
        command.extend(["-P", str(port)])

    command.extend(["-o", f"UserKnownHostsFile={get_workspace_known_hosts_path()}"])
    command.extend(["-o", "StrictHostKeyChecking=yes"])
    if batch_mode is None:
        batch_mode = ssh_batch_mode()
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
    batch_mode: bool | None = None,
    connect_timeout: int | None = 30,
) -> str:
    """Build the rsync -e SSH transport string with quoted argv."""

    ssh_command = ["ssh"]
    if ssh_key:
        ssh_command.extend(["-i", ssh_key])
    if port is not None:
        ssh_command.extend(["-p", str(port)])
    ssh_command.extend(["-o", f"UserKnownHostsFile={get_workspace_known_hosts_path()}"])
    ssh_command.extend(["-o", "StrictHostKeyChecking=yes"])
    if batch_mode is None:
        batch_mode = ssh_batch_mode()
    if batch_mode is True:
        ssh_command.extend(["-o", "BatchMode=yes"])
    elif batch_mode is False:
        ssh_command.extend(["-o", "BatchMode=no"])
    if connect_timeout is not None:
        ssh_command.extend(["-o", f"ConnectTimeout={connect_timeout}"])
    return shell_join(ssh_command)
