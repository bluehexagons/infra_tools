#!/usr/bin/env python3
"""Workspace registry of known Proxmox hosts.

Each host record persists the connection details needed to manage Proxmox
guests on it (IP/hostname, SSH user, optional SSH key, optional default
storage pool, optional friendly description). Records are stored in
``proxmox_hosts.json`` inside the active workspace.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Optional, cast

from lib.types import JSONDict, JSONList
from lib.workspace import ensure_workspace_dir, normalize_workspace_dir


PROXMOX_HOSTS_FILENAME = "proxmox_hosts.json"


@dataclass
class ProxmoxHost:
    """Connection details for a single Proxmox node."""

    name: str
    address: str
    user: str = "root"
    ssh_key: Optional[str] = None
    description: Optional[str] = None
    default_storage: Optional[str] = None
    default_bridge: Optional[str] = None
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> JSONDict:
        return cast(JSONDict, asdict(self))

    @classmethod
    def from_dict(cls, data: JSONDict) -> "ProxmoxHost":
        if "name" not in data or "address" not in data:
            raise ValueError("Proxmox host record missing 'name' or 'address'")
        tags_raw = data.get("tags") or []
        if not isinstance(tags_raw, list):
            raise ValueError("Proxmox host 'tags' must be a list")
        return cls(
            name=str(data["name"]),
            address=str(data["address"]),
            user=str(data.get("user") or "root"),
            ssh_key=cast(Optional[str], data.get("ssh_key")),
            description=cast(Optional[str], data.get("description")),
            default_storage=cast(Optional[str], data.get("default_storage")),
            default_bridge=cast(Optional[str], data.get("default_bridge")),
            tags=[str(t) for t in tags_raw],
        )


def get_proxmox_hosts_path(workspace: Optional[str] = None) -> str:
    """Return the registry JSON path inside the workspace."""
    return os.path.join(normalize_workspace_dir(workspace), PROXMOX_HOSTS_FILENAME)


def _load_raw(path: str) -> JSONList:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Failed to read Proxmox host registry {path}: {exc}")
    if not isinstance(data, list):
        raise ValueError(
            f"Proxmox host registry {path} must contain a JSON array"
        )
    return cast(JSONList, data)


def load_proxmox_hosts(workspace: Optional[str] = None) -> list[ProxmoxHost]:
    """Load all registered Proxmox hosts."""
    path = get_proxmox_hosts_path(workspace)
    raw = _load_raw(path)
    hosts: list[ProxmoxHost] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError(f"Invalid entry in {path}: expected object")
        hosts.append(ProxmoxHost.from_dict(cast(JSONDict, entry)))
    return hosts


def save_proxmox_hosts(
    hosts: list[ProxmoxHost],
    workspace: Optional[str] = None,
) -> str:
    """Persist the registry, returning the file path."""
    ensure_workspace_dir(workspace)
    path = get_proxmox_hosts_path(workspace)
    payload = [host.to_dict() for host in hosts]
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp_path, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def find_proxmox_host(
    name_or_address: str, workspace: Optional[str] = None
) -> Optional[ProxmoxHost]:
    """Find a host by exact name or address match (case-insensitive name)."""
    needle = name_or_address.strip()
    needle_lc = needle.lower()
    for host in load_proxmox_hosts(workspace):
        if host.name.lower() == needle_lc or host.address == needle:
            return host
    return None


def add_proxmox_host(
    host: ProxmoxHost,
    workspace: Optional[str] = None,
    *,
    replace: bool = False,
) -> ProxmoxHost:
    """Add or replace a host in the registry.

    Raises ValueError if the host already exists and ``replace`` is False.
    """
    if not host.name or not host.name.strip():
        raise ValueError("Proxmox host name is required")
    if not host.address or not host.address.strip():
        raise ValueError("Proxmox host address is required")

    hosts = load_proxmox_hosts(workspace)
    name_lc = host.name.lower()
    for i, existing in enumerate(hosts):
        if existing.name.lower() == name_lc:
            if not replace:
                raise ValueError(
                    f"Proxmox host '{host.name}' already exists; "
                    f"use replace=True to update"
                )
            hosts[i] = host
            save_proxmox_hosts(hosts, workspace)
            return host
    hosts.append(host)
    save_proxmox_hosts(hosts, workspace)
    return host


def remove_proxmox_host(
    name_or_address: str, workspace: Optional[str] = None
) -> bool:
    """Remove a host by name or address; returns True if removed."""
    needle = name_or_address.strip()
    needle_lc = needle.lower()
    hosts = load_proxmox_hosts(workspace)
    new_hosts = [
        h for h in hosts
        if h.name.lower() != needle_lc and h.address != needle
    ]
    if len(new_hosts) == len(hosts):
        return False
    save_proxmox_hosts(new_hosts, workspace)
    return True
