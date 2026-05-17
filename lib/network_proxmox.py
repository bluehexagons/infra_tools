"""Proxmox adapters for the generic network inventory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from lib.network_inventory import (
    NetworkHost,
    NetworkProfile,
    find_network_profile,
    save_network_profile,
)
from lib.proxmox_hosts import ProxmoxHost, load_proxmox_hosts


@dataclass
class ProxmoxImportResult:
    """Summary of importing registered Proxmox hosts into a network profile."""

    profile: NetworkProfile
    imported_hosts: list[NetworkHost]
    control_plane_added: list[str]
    skipped_hosts: list[str]


def import_registered_proxmox_hosts(
    profile_name: str,
    workspace: Optional[str] = None,
    *,
    targets: Optional[list[str]] = None,
    tags: Optional[list[str]] = None,
    include_control_plane: bool = True,
) -> ProxmoxImportResult:
    """Import registered Proxmox nodes into a generic network profile.

    The import is idempotent: Proxmox-sourced host records are replaced when
    they match by name, address, or ``profile_ref``. Non-Proxmox records are not
    overwritten; those conflicts are reported as skipped hosts.
    """

    profile = find_network_profile(profile_name, workspace) or NetworkProfile(
        name=profile_name
    )
    proxmox_hosts = _filter_proxmox_hosts(
        load_proxmox_hosts(workspace),
        targets=targets,
        tags=tags,
    )
    if not proxmox_hosts:
        raise ValueError("No registered Proxmox hosts matched the import filters")

    imported: list[NetworkHost] = []
    skipped: list[str] = []
    control_added: list[str] = []

    for proxmox_host in proxmox_hosts:
        network_host = _network_host_from_proxmox(proxmox_host)
        if _upsert_proxmox_network_host(profile, network_host):
            imported.append(network_host)
            if (
                include_control_plane
                and network_host.address not in profile.control_plane
            ):
                profile.control_plane.append(network_host.address)
                control_added.append(network_host.address)
        else:
            skipped.append(proxmox_host.name)

    save_network_profile(profile, workspace)
    return ProxmoxImportResult(
        profile=profile,
        imported_hosts=imported,
        control_plane_added=control_added,
        skipped_hosts=skipped,
    )


def _filter_proxmox_hosts(
    hosts: list[ProxmoxHost],
    *,
    targets: Optional[list[str]],
    tags: Optional[list[str]],
) -> list[ProxmoxHost]:
    target_set = {target.lower() for target in targets or []}
    tag_set = set(tags or [])
    filtered: list[ProxmoxHost] = []
    for host in hosts:
        if target_set and host.name.lower() not in target_set and host.address not in target_set:
            continue
        if tag_set and not tag_set.issubset(set(host.tags)):
            continue
        filtered.append(host)
    return filtered


def _network_host_from_proxmox(host: ProxmoxHost) -> NetworkHost:
    roles = ["control-plane", "proxmox"]
    return NetworkHost(
        name=host.name,
        address=host.address,
        provider="proxmox",
        roles=roles,
        profile_ref=f"proxmox:{host.name}",
    )


def _upsert_proxmox_network_host(
    profile: NetworkProfile,
    incoming: NetworkHost,
) -> bool:
    for index, existing in enumerate(profile.hosts):
        matched = (
            existing.profile_ref == incoming.profile_ref
            or existing.name.lower() == incoming.name.lower()
            or existing.address == incoming.address
        )
        if not matched:
            continue
        if existing.provider != "proxmox" and existing.profile_ref != incoming.profile_ref:
            return False
        profile.hosts[index] = incoming
        return True
    profile.hosts.append(incoming)
    return True


__all__ = [
    "ProxmoxImportResult",
    "import_registered_proxmox_hosts",
]
