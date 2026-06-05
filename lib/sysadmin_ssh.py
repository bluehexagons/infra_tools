"""SSH session convenience wrapper using saved config."""

from __future__ import annotations

import os
import sys
from typing import Optional

from lib.cache import load_setup_command
from lib.ssh_utils import build_ssh_command


def run_ssh(
    host: str,
    username: Optional[str] = None,
    ssh_key: Optional[str] = None,
    port: Optional[int] = None,
    remote_command: Optional[list[str]] = None,
) -> int:
    config = load_setup_command(host)
    if config:
        if not username:
            username = config.username
        if not ssh_key:
            ssh_key = config.ssh_key
        if port is None:
            port = getattr(config, "port", None)

    username = username or "root"

    cmd = build_ssh_command(
        host,
        username,
        ssh_key,
        port=port,
        batch_mode=False,
        connect_timeout=30,
        server_alive_interval=30,
    )

    # Add ControlMaster for connection reuse
    cmd = (
        cmd[:1]
        + ["-o", "ControlMaster=auto", "-o", "ControlPersist=60s"]
        + cmd[1:]
    )

    if remote_command:
        # Append remote command as a single shell string
        import shlex
        cmd.append(shlex.join(remote_command))

    os.execvp(cmd[0], cmd)
    # execvp replaces the process; this line is never reached
    return 0  # pragma: no cover
