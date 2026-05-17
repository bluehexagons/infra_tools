"""Proxmox adapters for the generic network inventory."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Optional

from lib.network_inventory import (
    NetworkHost,
    NetworkProfile,
    NetworkSubnet,
    find_network_profile,
    save_network_profile,
)
from lib.proxmox_hosts import ProxmoxHost, load_proxmox_hosts
from lib.proxmox_manage import (
    ContainerInfo,
    ProxmoxManageError,
    get_container_config,
    list_containers,
)


@dataclass
class ProxmoxImportResult:
    """Summary of importing registered Proxmox hosts into a network profile."""

    profile: NetworkProfile
    imported_hosts: list[NetworkHost]
    control_plane_added: list[str]
    skipped_hosts: list[str]


@dataclass
class ProxmoxGuestNetworkImportResult:
    """Summary of importing guest networks from Proxmox guest configs."""

    profile: NetworkProfile
    imported_networks: list[str]
    imported_subnets: list[NetworkSubnet]
    scanned_guests: int
    skipped_guests: list[str]


_CONFIG_IP_RE = re.compile(r"\bip=([^,\s]+)")
_CONFIG_VLAN_RE = re.compile(r"\b(?:tag|vlan)=(\d{1,4})\b")


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


def import_proxmox_guest_networks(
    profile_name: str,
    workspace: Optional[str] = None,
    *,
    targets: Optional[list[str]] = None,
    tags: Optional[list[str]] = None,
) -> ProxmoxGuestNetworkImportResult:
    """Import guest subnets from registered Proxmox guest configurations."""

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

    imported_networks: list[str] = []
    imported_subnets: list[NetworkSubnet] = []
    skipped_guests: list[str] = []
    scanned_guests = 0

    for proxmox_host in proxmox_hosts:
        try:
            guests = list_containers(proxmox_host)
        except ProxmoxManageError as exc:
            skipped_guests.append(f"{proxmox_host.name}: {exc}")
            continue
        for guest in guests:
            scanned_guests += 1
            try:
                config = get_container_config(proxmox_host, guest.vmid)
            except ProxmoxManageError as exc:
                skipped_guests.append(f"{proxmox_host.name}/{guest.vmid}: {exc}")
                continue
            for subnet in _guest_subnets_from_config(proxmox_host, guest, config):
                if subnet.cidr not in profile.guest_networks:
                    profile.guest_networks.append(subnet.cidr)
                    imported_networks.append(subnet.cidr)
                if _add_subnet_if_missing(profile, subnet):
                    imported_subnets.append(subnet)

    save_network_profile(profile, workspace)
    return ProxmoxGuestNetworkImportResult(
        profile=profile,
        imported_networks=imported_networks,
        imported_subnets=imported_subnets,
        scanned_guests=scanned_guests,
        skipped_guests=skipped_guests,
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


def _guest_subnets_from_config(
    host: ProxmoxHost,
    guest: ContainerInfo,
    config: dict[str, str],
) -> list[NetworkSubnet]:
    subnets: list[NetworkSubnet] = []
    for key, value in config.items():
        if not (key.startswith("net") or key.startswith("ipconfig")):
            continue
        match = _CONFIG_IP_RE.search(value)
        if not match:
            continue
        raw_ip = match.group(1).strip()
        if not raw_ip or raw_ip.lower() in {"dhcp", "manual", "auto"}:
            continue
        try:
            interface = ipaddress.ip_interface(raw_ip)
        except ValueError:
            continue
        if interface.version != 4:
            continue
        vlan_id = _vlan_id_from_config(value)
        cidr = str(interface.network)
        subnets.append(
            NetworkSubnet(
                name=_subnet_name(host.name, guest.vmid, cidr),
                cidr=cidr,
                zone="guests",
                vlan_id=vlan_id,
            )
        )
    return subnets


def _vlan_id_from_config(value: str) -> Optional[int]:
    match = _CONFIG_VLAN_RE.search(value)
    if not match:
        return None
    vlan_id = int(match.group(1))
    if not 1 <= vlan_id <= 4094:
        return None
    return vlan_id


def _subnet_name(host_name: str, vmid: int, cidr: str) -> str:
    safe_cidr = (
        cidr.replace(".", "-")
        .replace("/", "-")
        .replace(":", "-")
    )
    return f"proxmox-{host_name}-{int(vmid)}-{safe_cidr}"[:64]


def _add_subnet_if_missing(profile: NetworkProfile, incoming: NetworkSubnet) -> bool:
    existing_cidrs = {subnet.cidr for subnet in profile.subnets}
    if incoming.cidr in existing_cidrs:
        return False
    existing_names = {subnet.name.lower() for subnet in profile.subnets}
    name = incoming.name
    suffix = 2
    while name.lower() in existing_names:
        suffix_text = f"-{suffix}"
        name = incoming.name[: 64 - len(suffix_text)] + suffix_text
        suffix += 1
    if name != incoming.name:
        incoming = NetworkSubnet(
            name=name,
            cidr=incoming.cidr,
            zone=incoming.zone,
            vlan_id=incoming.vlan_id,
            gateway=incoming.gateway,
        )
    profile.subnets.append(incoming)
    return True


__all__ = [
    "ProxmoxGuestNetworkImportResult",
    "ProxmoxImportResult",
    "import_proxmox_guest_networks",
    "import_registered_proxmox_hosts",
]
