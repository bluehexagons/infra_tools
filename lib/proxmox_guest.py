#!/usr/bin/env python3
"""Shared Proxmox guest-provisioning helpers.

This module provides guest-oriented access to the generic SSH/network/storage
helpers that were originally introduced alongside LXC provisioning. VM and
management code should depend on this module rather than importing generic
helpers directly from the LXC-specific provisioning module.
"""

from __future__ import annotations

import shlex
import sys
import subprocess
import time
from typing import Optional

from lib.proxmox_node import (
    ProvisionError,
    _build_container_hostname,
    _get_bridge_prefix_length,
    _get_host_gateway,
    _get_host_nameservers,
    _get_next_vmid,
    _resolve_public_key_path,
    _resolve_storage_pool,
    _ssh_opts,
    _ssh_run,
    auto_detect_bridge,
)
from lib.types import StrList


def _build_guest_hostname(
    target_ip: str,
    friendly_name: Optional[str],
    *,
    default_prefix: str = "guest",
) -> str:
    """Derive a hostname for any Proxmox guest.

    Friendly names are passed through the existing hostname sanitizer. When no
    friendly name is set, the legacy helper derives an ``lxc-`` hostname, which
    we rewrite to the requested guest prefix.
    """
    hostname = _build_container_hostname(target_ip, friendly_name)
    if hostname.startswith("lxc-"):
        return f"{default_prefix}{hostname[3:]}"
    return hostname


def _wait_for_guest_ssh(
    target_ip: str,
    node_ip: str,
    user: str,
    ssh_opts: StrList,
    timeout: int = 90,
    dry_run: bool = False,
) -> None:
    """Wait for sshd inside a newly provisioned guest to accept TCP connections."""
    if dry_run:
        return

    deadline = time.monotonic() + timeout
    probe = (
        f"timeout 3 bash -c '</dev/tcp/{shlex.quote(target_ip)}/22' "
        f"&& echo READY"
    )
    last_err = ""
    while time.monotonic() < deadline:
        result = _ssh_run(node_ip, user, ssh_opts, probe, dry_run=False)
        if result.returncode == 0 and "READY" in result.stdout:
            print(f"  ✓ Guest SSH is reachable at {target_ip}:22")
            sys.stdout.flush()
            return
        last_err = (result.stderr or result.stdout or "").strip()
        time.sleep(3)
    raise ProvisionError(
        f"Timed out after {timeout}s waiting for SSH on {target_ip}:22 "
        f"(last probe: {last_err or 'no response'})"
    )


__all__ = [
    "ProvisionError",
    "_build_guest_hostname",
    "_get_bridge_prefix_length",
    "_get_host_gateway",
    "_get_host_nameservers",
    "_get_next_vmid",
    "_resolve_public_key_path",
    "_resolve_storage_pool",
    "_ssh_opts",
    "_ssh_run",
    "_wait_for_guest_ssh",
    "auto_detect_bridge",
]
