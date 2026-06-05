"""Network helpers for Proxmox: suggest unassigned IPs on a bridge subnet."""

from __future__ import annotations

import ipaddress
import re
import subprocess

from lib.proxmox_guest import _ssh_opts, _ssh_run
from lib.proxmox_hosts import ProxmoxHost


def _run(host: ProxmoxHost, cmd: str) -> subprocess.CompletedProcess[str]:
    return _ssh_run(host.address, host.user, _ssh_opts(host.ssh_key), cmd)


def _assigned_guest_ips(host: ProxmoxHost) -> set[str]:
    """Return all IPs currently assigned to guests via their Proxmox configs.

    Reads directly from the PVE config directories in one SSH call rather
    than iterating per-guest.
    """
    result = _run(
        host,
        r"grep -rh 'ip=' /etc/pve/qemu-server/ /etc/pve/lxc/ 2>/dev/null"
        r" | grep -oE 'ip=[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+'"
        r" | cut -d= -f2",
    )
    ips: set[str] = set()
    for line in (result.stdout or "").splitlines():
        ip = line.strip()
        if ip:
            ips.add(ip)
    return ips


def _arp_ips(host: ProxmoxHost, bridge: str) -> set[str]:
    """Return IPs visible in the ARP/neighbour table on ``bridge``."""
    result = _run(host, f"ip neigh show dev {bridge} 2>/dev/null")
    ips: set[str] = set()
    ip_re = re.compile(r"^([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)")
    for line in (result.stdout or "").splitlines():
        m = ip_re.match(line.strip())
        if m:
            ips.add(m.group(1))
    return ips


def _gateway(host: ProxmoxHost) -> str:
    """Return the default gateway on the Proxmox node."""
    result = _run(host, "ip route | awk '/default/ {print $3; exit}'")
    return result.stdout.strip() if result.returncode == 0 else ""


def suggest_free_ips(
    host: ProxmoxHost,
    *,
    bridge: str | None = None,
    count: int = 5,
) -> list[str]:
    """Return up to ``count`` unassigned IPs on the host's bridge subnet.

    Skips IPs already assigned to any guest, IPs seen in the ARP table on
    the bridge, the gateway, and the network/broadcast addresses.  Returns
    an empty list if the subnet cannot be determined.
    """
    used_bridge = (
        bridge
        or (host.facts.default_bridge if host.facts else None)
        or "vmbr0"
    )

    cidr_result = _run(
        host,
        f"ip -o -f inet addr show dev {used_bridge} 2>/dev/null"
        f" | awk 'NR==1 {{print $4}}'",
    )
    cidr_str = cidr_result.stdout.strip()
    if not cidr_str:
        return []
    try:
        network = ipaddress.IPv4Network(cidr_str, strict=False)
    except ValueError:
        return []

    reserved = (
        _assigned_guest_ips(host)
        | _arp_ips(host, used_bridge)
        | {_gateway(host)}
    )

    suggestions: list[str] = []
    for addr in network.hosts():
        ip_str = str(addr)
        if ip_str not in reserved:
            suggestions.append(ip_str)
            if len(suggestions) >= count:
                break
    return suggestions


__all__ = [
    "suggest_free_ips",
]
