"""Proxmox orphaned-volume detection and cleanup.

An "orphaned" volume is a guest disk (images or rootdir content type) whose
recorded VMID does not match any currently defined guest on the node.  These
accumulate after VM or LXC destruction when ``--purge`` was not used, or
after failed imports.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass

from lib.proxmox_guest import _ssh_opts, _ssh_run
from lib.proxmox_hosts import ProxmoxHost


class ProxmoxStorageError(Exception):
    """Raised when a storage management operation fails."""


@dataclass
class OrphanedVolume:
    """A volume in guest storage whose VMID no longer exists."""

    volid: str
    storage: str
    vmid: int
    size: str
    format: str = ""


def _run(
    host: ProxmoxHost,
    cmd: str,
    *,
    dry_run: bool = False,
) -> subprocess.CompletedProcess[str]:
    return _ssh_run(host.address, host.user, _ssh_opts(host.ssh_key), cmd, dry_run=dry_run)


def _active_vmids(host: ProxmoxHost) -> set[int]:
    """Return all VMIDs currently defined on ``host`` (VMs + LXC)."""
    vmids: set[int] = set()
    for cmd in ("qm list", "pct list"):
        result = _run(host, cmd)
        if result.returncode != 0:
            continue
        for line in result.stdout.splitlines()[1:]:   # skip header row
            parts = line.split()
            if parts:
                try:
                    vmids.add(int(parts[0]))
                except ValueError:
                    pass
    return vmids


def _guest_storage_names(host: ProxmoxHost) -> list[str]:
    """Return active storage pools that hold guest disks (images or rootdir)."""
    result = _run(host, "pvesm status")
    if result.returncode != 0:
        raise ProxmoxStorageError(
            f"pvesm status failed on {host.address}: "
            f"{(result.stderr or '').strip() or 'unknown error'}"
        )
    pools: list[str] = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        # pvesm status columns: Name Type Status Total Used Available %
        if len(parts) >= 3 and parts[2] == "active":
            pools.append(parts[0])
    return pools


def _parse_pvesm_list(stdout: str) -> list[tuple[str, int, str, str]]:
    """Parse ``pvesm list <storage>`` into (volid, vmid, size, format) tuples.

    Only includes guest disk content types (images, rootdir).
    """
    entries: list[tuple[str, int, str, str]] = []
    for line in stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 4:
            continue
        volid = parts[0]
        fmt = parts[1]
        content_type = parts[2]
        size = parts[3]
        vmid_str = parts[4] if len(parts) >= 5 else ""
        if content_type not in ("images", "rootdir"):
            continue
        try:
            vmid = int(vmid_str)
        except ValueError:
            continue
        entries.append((volid, vmid, size, fmt))
    return entries


def list_orphaned_volumes(host: ProxmoxHost) -> list[OrphanedVolume]:
    """Return volumes in guest-storage pools whose VMID no longer exists."""
    active = _active_vmids(host)
    orphans: list[OrphanedVolume] = []
    for storage in _guest_storage_names(host):
        result = _run(host, f"pvesm list {shlex.quote(storage)}")
        if result.returncode != 0:
            continue
        for volid, vmid, size, fmt in _parse_pvesm_list(result.stdout):
            if vmid not in active:
                orphans.append(OrphanedVolume(
                    volid=volid,
                    storage=storage,
                    vmid=vmid,
                    size=size,
                    format=fmt,
                ))
    return orphans


def delete_volume(
    host: ProxmoxHost,
    volid: str,
    *,
    dry_run: bool = False,
) -> None:
    """Delete a storage volume by its volid (e.g. ``local-lvm:vm-999-disk-0``)."""
    result = _run(host, shlex.join(["pvesm", "free", volid]), dry_run=dry_run)
    if result.returncode != 0:
        raise ProxmoxStorageError(
            f"pvesm free {volid!r} failed on {host.address}: "
            f"{(result.stderr or result.stdout or '').strip() or 'unknown error'}"
        )


__all__ = [
    "OrphanedVolume",
    "ProxmoxStorageError",
    "delete_volume",
    "list_orphaned_volumes",
]
