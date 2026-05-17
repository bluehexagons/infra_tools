"""Proxmox backup management: list and trigger vzdump backups for guests."""

from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from typing import Optional

from lib.proxmox_guest import _ssh_opts, _ssh_run
from lib.proxmox_hosts import ProxmoxHost


class ProxmoxBackupError(Exception):
    """Raised when a backup operation fails."""


@dataclass
class BackupInfo:
    """One backup entry from Proxmox storage content."""

    volid: str
    vmid: int
    size: int           # bytes
    ctime: Optional[int] = None
    format: str = ""
    notes: str = ""

    @property
    def storage(self) -> str:
        return self.volid.split(":", 1)[0] if ":" in self.volid else ""

    @property
    def filename(self) -> str:
        return self.volid.split(":", 1)[1] if ":" in self.volid else self.volid


_VALID_MODES = ("snapshot", "suspend", "stop")
_VALID_COMPRESS = ("zstd", "gzip", "lzo", "0")


def _run(
    host: ProxmoxHost,
    cmd: str,
    *,
    dry_run: bool = False,
) -> subprocess.CompletedProcess[str]:
    return _ssh_run(host.address, host.user, _ssh_opts(host.ssh_key), cmd, dry_run=dry_run)


def _backup_storages(host: ProxmoxHost) -> list[str]:
    """Return active storage names that support the backup content type."""
    result = _run(
        host,
        "pvesh get /nodes/$(hostname -s)/storage --output-format json 2>/dev/null",
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    return [
        entry["storage"]
        for entry in data
        if isinstance(entry, dict)
        and "backup" in entry.get("content", "")
        and entry.get("active", 0)
    ]


def list_backups(host: ProxmoxHost, vmid: int) -> list[BackupInfo]:
    """Return all backups for ``vmid`` across every backup-capable storage pool."""
    backups: list[BackupInfo] = []
    for storage in _backup_storages(host):
        cmd = (
            f"pvesh get /nodes/$(hostname -s)/storage/{shlex.quote(storage)}/content"
            f" --content backup --output-format json 2>/dev/null"
        )
        result = _run(host, cmd)
        if result.returncode != 0 or not result.stdout.strip():
            continue
        try:
            entries = json.loads(result.stdout)
        except json.JSONDecodeError:
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if int(entry.get("vmid", -1)) != vmid:
                continue
            backups.append(BackupInfo(
                volid=str(entry.get("volid", "")),
                vmid=vmid,
                size=int(entry.get("size", 0)),
                ctime=entry.get("ctime"),
                format=str(entry.get("format", "")),
                notes=str(entry.get("notes", "")),
            ))
    return sorted(backups, key=lambda b: b.ctime or 0)


def create_backup(
    host: ProxmoxHost,
    vmid: int,
    *,
    storage: Optional[str] = None,
    mode: str = "snapshot",
    compress: str = "zstd",
    dry_run: bool = False,
) -> None:
    """Trigger an immediate vzdump backup for ``vmid``.

    mode: snapshot (no downtime for VMs, default), suspend, or stop.
    compress: zstd (default), gzip, lzo, or 0 (none).
    storage: target pool; auto-selects the first backup-capable pool if omitted.
    """
    if mode not in _VALID_MODES:
        raise ValueError(
            f"Invalid backup mode {mode!r}. Use one of: {', '.join(_VALID_MODES)}."
        )
    if compress not in _VALID_COMPRESS:
        raise ValueError(
            f"Invalid compress value {compress!r}. Use one of: {', '.join(_VALID_COMPRESS)}."
        )

    target_storage = storage
    if not target_storage:
        pools = _backup_storages(host)
        if not pools:
            raise ProxmoxBackupError(
                f"No backup-capable storage found on {host.address}. "
                "Add a storage pool with 'backup' content type in Proxmox."
            )
        target_storage = pools[0]

    cmd = shlex.join([
        "vzdump", str(int(vmid)),
        "--storage", target_storage,
        "--mode", mode,
        "--compress", compress,
        "--remove", "0",   # never auto-remove via retention; let the user manage that
    ])
    result = _run(host, cmd, dry_run=dry_run)
    if result.returncode != 0:
        raise ProxmoxBackupError(
            f"vzdump {vmid} failed on {host.address}: "
            f"{(result.stderr or result.stdout or '').strip() or 'unknown error'}"
        )


__all__ = [
    "BackupInfo",
    "ProxmoxBackupError",
    "create_backup",
    "list_backups",
]
