#!/usr/bin/env python3
"""Shared Proxmox guest-provisioning helpers."""

from __future__ import annotations

import ipaddress
import os
import re
import shlex
import subprocess
import sys
import time
from typing import Optional

from lib.types import StrList


class ProvisionError(Exception):
    """Raised when guest provisioning fails."""


def _ssh_opts(hosted_key: Optional[str] = None) -> StrList:
    """Build SSH options list for Proxmox node connections."""
    opts = [
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=30",
        "-o", "ServerAliveInterval=30",
    ]
    if hosted_key:
        opts.extend(["-i", hosted_key])
    return opts


def _ssh_run(
    node_ip: str,
    user: str,
    ssh_opts: StrList,
    cmd: str,
    dry_run: bool = False,
    log_cmd: Optional[str] = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command on the Proxmox host via SSH."""
    display_cmd = log_cmd if log_cmd is not None else cmd
    display_cmd = display_cmd[:80] + "..." if len(display_cmd) > 80 else display_cmd
    print(f"  Running on {node_ip}: {display_cmd}")
    sys.stdout.flush()

    if dry_run:
        print("  [DRY-RUN] Command not executed")
        return subprocess.CompletedProcess(
            args=[cmd], returncode=0, stdout="", stderr=""
        )

    ssh_cmd = ["ssh"] + ssh_opts + [f"{user}@{node_ip}", cmd]
    result = subprocess.run(
        ssh_cmd, capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if stderr:
            print(f"    Warning: {stderr[:200]}")
        sys.stdout.flush()
    return result


def _storage_pool_supports_content(
    pool: str,
    content_filter: str,
    node_ip: str,
    user: str,
    ssh_opts: StrList,
    dry_run: bool = False,
) -> bool:
    result = _ssh_run(
        node_ip, user, ssh_opts,
        f"pvesm status --content {shlex.quote(content_filter)}",
        dry_run=dry_run,
    )

    if dry_run:
        return True

    if result.returncode != 0:
        fallback_result = _ssh_run(
            node_ip, user, ssh_opts,
            "pvesm status",
            dry_run=dry_run,
        )
        if fallback_result.returncode != 0:
            return False

        for line in fallback_result.stdout.strip().split('\n')[1:]:
            parts = line.split()
            if parts and parts[0] == pool and len(parts) >= 3 and parts[2] == "active":
                return True
        return False

    for line in result.stdout.strip().split('\n')[1:]:
        parts = line.split()
        if parts and parts[0] == pool and len(parts) >= 3 and parts[2] == "active":
            return True

    return False


def auto_detect_bridge(
    node_ip: str,
    user: str = "root",
    hosted_key: Optional[str] = None,
    dry_run: bool = False,
) -> str:
    """Auto-detect the network bridge on the Proxmox host."""
    opts = _ssh_opts(hosted_key)
    result = _ssh_run(
        node_ip, user, opts,
        "ip -o link show | grep -o 'vmbr[0-9]*' | head -5",
        dry_run=dry_run,
    )

    if dry_run:
        print("  [DRY-RUN] Would detect bridge")
        return "vmbr0"

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise ProvisionError(
            f"Failed to query bridges on Proxmox host {node_ip}: "
            f"{stderr or 'ssh command failed'}"
        )

    bridges = [b.strip() for b in result.stdout.strip().split('\n') if b.strip()]

    if not bridges:
        raise ProvisionError(
            "No vmbr* network bridge found on the Proxmox host"
        )

    bridge = bridges[0]
    if bridge != "vmbr0" and "vmbr0" in bridges:
        bridge = "vmbr0"

    print(f"  ✓ Detected bridge: {bridge}")
    return bridge


def _get_bridge_prefix_length(
    node_ip: str,
    user: str,
    ssh_opts: StrList,
    bridge: str,
    dry_run: bool = False,
) -> str:
    result = _ssh_run(
        node_ip, user, ssh_opts,
        f"ip -o -f inet addr show dev {shlex.quote(bridge)} | awk 'NR==1 {{print $4}}'",
        dry_run=dry_run,
    )

    if dry_run:
        return "24"

    cidr = result.stdout.strip()
    if not cidr or "/" not in cidr:
        raise ProvisionError(f"Could not detect IPv4 prefix length for bridge {bridge}")

    prefix = cidr.split("/", 1)[1]
    print(f"  ✓ Detected bridge network: {cidr}")
    return prefix


def _get_host_gateway(
    node_ip: str,
    user: str,
    ssh_opts: StrList,
    dry_run: bool = False,
) -> str:
    """Get the default gateway from the Proxmox host."""
    result = _ssh_run(
        node_ip, user, ssh_opts,
        "ip route | awk '/default/ {print $3; exit}'",
        dry_run=dry_run,
    )

    if dry_run:
        return "10.0.0.1"

    gateway = result.stdout.strip()
    if not gateway:
        raise ProvisionError("Could not detect default gateway on Proxmox host")

    print(f"  ✓ Detected gateway: {gateway}")
    return gateway


def _is_usable_nameserver(addr: str) -> bool:
    """Return True if addr is a globally routable nameserver the guest can reach."""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    if ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast:
        return False
    return True


def _get_host_nameservers(
    node_ip: str,
    user: str,
    ssh_opts: StrList,
    dry_run: bool = False,
) -> StrList:
    """Get nameservers from the Proxmox host, filtering out unreachable addresses."""
    result = _ssh_run(
        node_ip, user, ssh_opts,
        "resolvectl dns 2>/dev/null | awk '{for (i=2;i<=NF;i++) print $i}' | sort -u; "
        "grep -oP '^nameserver\\s+\\K\\S+' /etc/resolv.conf",
        dry_run=dry_run,
    )

    if dry_run:
        return ["8.8.8.8"]

    seen: set[str] = set()
    nameservers: StrList = []
    for ns in (result.stdout or "").split('\n'):
        ns = ns.strip()
        if not ns or ns in seen:
            continue
        if not _is_usable_nameserver(ns):
            continue
        seen.add(ns)
        nameservers.append(ns)
        if len(nameservers) >= 3:
            break

    if not nameservers:
        print("  ⚠ No usable nameservers detected on host (only loopback?), using 1.1.1.1")
        return ["1.1.1.1"]

    print(f"  ✓ Detected nameservers: {', '.join(nameservers)}")
    return nameservers


def _get_next_vmid(
    node_ip: str,
    user: str,
    ssh_opts: StrList,
    dry_run: bool = False,
) -> int:
    """Get the next available VMID from the Proxmox cluster."""
    result = _ssh_run(
        node_ip, user, ssh_opts,
        "pvesh get /cluster/nextid",
        dry_run=dry_run,
    )

    if dry_run:
        return 100

    try:
        vmid = int(result.stdout.strip())
    except (ValueError, TypeError):
        raise ProvisionError(
            f"Could not determine next VMID: {result.stdout.strip()}"
        )

    print(f"  ✓ Next VMID: {vmid}")
    return vmid


def _resolve_storage_pool(
    pool_arg: str,
    node_ip: str,
    user: str,
    ssh_opts: StrList,
    content_filter: str,
    dry_run: bool = False,
) -> str:
    """Resolve a storage pool name."""
    if pool_arg != "auto":
        print(f"  ✓ Using storage pool: {pool_arg}")
        if not _storage_pool_supports_content(
            pool_arg, content_filter, node_ip, user, ssh_opts, dry_run=dry_run
        ):
            raise ProvisionError(
                f"Storage pool '{pool_arg}' does not support content type '{content_filter}'"
            )
        return pool_arg

    result = _ssh_run(
        node_ip, user, ssh_opts,
        f"pvesm status --content {shlex.quote(content_filter)}",
        dry_run=dry_run,
    )

    if dry_run:
        print("  [DRY-RUN] Would resolve storage pool")
        return "local-lvm"

    if result.returncode != 0:
        raise ProvisionError(
            f"Could not query storage pools for content type '{content_filter}'"
        )

    for line in result.stdout.strip().split('\n')[1:]:
        parts = line.split()
        if len(parts) >= 3 and parts[2] == "active":
            pool = parts[0]
            print(f"  ✓ Auto-selected storage pool: {pool}")
            return pool

    raise ProvisionError(
        "No suitable storage pool found. Specify one explicitly with --storage root POOL AMOUNT or --storage template POOL"
    )


def _build_guest_hostname(
    target_ip: str,
    friendly_name: Optional[str],
    *,
    default_prefix: str = "guest",
) -> str:
    """Derive a hostname for any Proxmox guest."""
    if friendly_name:
        hostname = re.sub(r'[^a-z0-9-]', '-', friendly_name.lower()).strip('-')
        hostname = re.sub(r'-+', '-', hostname)
        if hostname:
            return hostname[:63].rstrip('-') or hostname[:63]

    return (f"{default_prefix}-{target_ip.replace('.', '-')}")[:63]


def _resolve_public_key_path(ssh_key: Optional[str]) -> Optional[str]:
    """Return the local path to the public key matching the given private key, if any."""
    if not ssh_key:
        return None
    pub_path = ssh_key + ".pub"
    try:
        if os.path.isfile(pub_path) and os.path.getsize(pub_path) > 0:
            return pub_path
    except OSError:
        return None
    return None


def _wait_for_guest_ssh(
    target_ip: str,
    node_ip: str,
    user: str,
    ssh_opts: StrList,
    timeout: int = 90,
    dry_run: bool = False,
    *,
    label: str = "Guest",
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
            print(f"  ✓ {label} SSH is reachable at {target_ip}:22")
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
    "_is_usable_nameserver",
    "_resolve_public_key_path",
    "_resolve_storage_pool",
    "_ssh_opts",
    "_ssh_run",
    "_storage_pool_supports_content",
    "_wait_for_guest_ssh",
    "auto_detect_bridge",
]
