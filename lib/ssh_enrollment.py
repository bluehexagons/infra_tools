"""Explicit SSH host-key enrollment for workspace-managed connections."""

from __future__ import annotations

import os
import stat
import subprocess
from typing import Callable, Optional

from lib.ssh_utils import get_workspace_known_hosts_path
from lib.validators import validate_host


def _fingerprint(scan: str) -> str:
    result = subprocess.run(
        ["ssh-keygen", "-lf", "-"],
        input=scan,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError("could not calculate the SSH host-key fingerprint")
    return result.stdout.strip()


def enroll_host_key(
    host: str,
    *,
    port: int = 22,
    assume_yes: bool = False,
    input_fn: Optional[Callable[[str], str]] = None,
) -> int:
    """Scan, display, and optionally persist a host key after confirmation."""
    if not validate_host(host):
        raise ValueError(f"Invalid host: {host}")
    if not 1 <= port <= 65535:
        raise ValueError("SSH port must be between 1 and 65535")

    result = subprocess.run(
        ["ssh-keyscan", "-T", "10", "-p", str(port), host],
        capture_output=True,
        text=True,
        check=False,
    )
    scan = result.stdout.strip()
    if result.returncode != 0 or not scan:
        detail = result.stderr.strip() or "no host key was returned"
        print(f"Error enrolling {host}: {detail}")
        return 1

    print(f"SSH host-key fingerprint for {host}:{port}:")
    print(_fingerprint(scan))
    if not assume_yes:
        response = (input_fn or input)(
            "Verify this fingerprint out of band and enroll it? [y/N] "
        )
        if response.strip().lower() not in {"y", "yes"}:
            print("Cancelled; no host key was saved.")
            return 1

    known_hosts = get_workspace_known_hosts_path()
    os.makedirs(os.path.dirname(known_hosts), mode=0o700, exist_ok=True)
    if os.path.exists(known_hosts):
        os.chmod(known_hosts, stat.S_IRUSR | stat.S_IWUSR)
    with open(known_hosts, "a", encoding="utf-8") as file_obj:
        file_obj.write(scan + "\n")
    os.chmod(known_hosts, stat.S_IRUSR | stat.S_IWUSR)
    print(f"Enrolled host key in {known_hosts}")
    return 0
