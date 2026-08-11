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

from lib.proxmox_hosts import ProxmoxHost, ProxmoxHostFacts, ProxmoxStoragePool
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


def _list_proxmox_bridges(
    node_ip: str,
    user: str,
    ssh_opts: StrList,
    dry_run: bool = False,
) -> StrList:
    """Return available Linux bridge interfaces on the Proxmox host."""
    result = _ssh_run(
        node_ip,
        user,
        ssh_opts,
        "ip -o link show type bridge | awk -F': ' '{print $2}' | cut -d@ -f1 | sort -u",
        dry_run=dry_run,
    )

    if dry_run:
        return ["vmbr0"]

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise ProvisionError(
            f"Failed to query bridges on Proxmox host {node_ip}: "
            f"{stderr or 'ssh command failed'}"
        )

    bridges = [bridge.strip() for bridge in result.stdout.splitlines() if bridge.strip()]
    if "vmbr0" in bridges:
        bridges = ["vmbr0"] + [bridge for bridge in bridges if bridge != "vmbr0"]
    return bridges


def auto_detect_bridge(
    node_ip: str,
    user: str = "root",
    hosted_key: Optional[str] = None,
    dry_run: bool = False,
    preferred_bridge: Optional[str] = None,
) -> str:
    """Auto-detect the guest bridge, preferring the host's default route."""
    opts = _ssh_opts(hosted_key)
    bridges = _list_proxmox_bridges(node_ip, user, opts, dry_run=dry_run)

    if not bridges:
        raise ProvisionError(
            "No Linux network bridge found on the Proxmox host"
        )

    if preferred_bridge:
        if preferred_bridge not in bridges:
            raise ProvisionError(
                f"Configured bridge '{preferred_bridge}' was not found on the Proxmox host"
            )
        bridge = preferred_bridge
    else:
        route_result = _ssh_run(
            node_ip,
            user,
            opts,
            "ip route show default | awk '{for (i=1; i<=NF; i++) if ($i == \"dev\") {print $(i+1); exit}}'",
            dry_run=dry_run,
        )
        route_bridge = (route_result.stdout or "").strip()
        if route_bridge and route_bridge not in bridges:
            raise ProvisionError(
                f"Default route uses '{route_bridge}', which is not a Proxmox bridge; "
                "specify --bridge explicitly"
            )
        bridge = route_bridge or bridges[0]
    print(f"  ✓ Detected bridge: {bridge}")
    return bridge


def _get_node_name(
    node_ip: str,
    user: str,
    ssh_opts: StrList,
    dry_run: bool = False,
) -> Optional[str]:
    """Return the short hostname for the Proxmox node."""
    result = _ssh_run(
        node_ip,
        user,
        ssh_opts,
        "hostname -s",
        dry_run=dry_run,
    )
    if dry_run:
        return "pve"
    if result.returncode != 0:
        return None
    node_name = (result.stdout or "").strip()
    return node_name or None


def _get_corosync_config(
    node_ip: str,
    user: str,
    ssh_opts: StrList,
    dry_run: bool = False,
) -> str:
    """Return the cluster corosync config when available."""
    result = _ssh_run(
        node_ip,
        user,
        ssh_opts,
        "cat /etc/pve/corosync.conf",
        dry_run=dry_run,
    )
    if dry_run:
        return (
            "totem {\n"
            "  cluster_name: homelab\n"
            "}\n"
            "nodelist {\n"
            "  node {\n"
            "    name: pve1\n"
            "    ring0_addr: 10.0.0.10\n"
            "  }\n"
            "  node {\n"
            "    name: pve2\n"
            "    ring0_addr: 10.0.0.11\n"
            "  }\n"
            "}\n"
        )
    if result.returncode != 0:
        return ""
    return result.stdout or ""


def _parse_corosync_config(config_text: str) -> tuple[Optional[str], list[tuple[str, str]]]:
    """Extract cluster name and member node addresses from corosync config text."""
    cluster_match = re.search(r"cluster_name:\s*(\S+)", config_text)
    cluster_name = cluster_match.group(1) if cluster_match else None

    nodes: list[tuple[str, str]] = []
    for block in re.findall(r"node\s*\{(.*?)\}", config_text, flags=re.DOTALL):
        name_match = re.search(r"name:\s*(\S+)", block)
        address_match = re.search(r"ring0_addr:\s*(\S+)", block)
        if not name_match or not address_match:
            continue
        nodes.append((name_match.group(1), address_match.group(1)))
    return cluster_name, nodes


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
        return "local" if content_filter in {"iso", "snippets"} else "local-lvm"

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


def _list_storage_pools(
    node_ip: str,
    user: str,
    ssh_opts: StrList,
    dry_run: bool = False,
) -> list[ProxmoxStoragePool]:
    """Return storage pools reported by ``pvesm status``."""
    result = _ssh_run(
        node_ip,
        user,
        ssh_opts,
        "pvesm status",
        dry_run=dry_run,
    )
    if dry_run:
        return [
            ProxmoxStoragePool(
                name="local",
                type="dir",
                status="active",
                content=["iso", "backup", "vztmpl"],
            ),
            ProxmoxStoragePool(
                name="local-lvm",
                type="lvmthin",
                status="active",
                content=["images", "rootdir"],
            ),
        ]
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise ProvisionError(
            f"Could not query storage pools on {node_ip}: "
            f"{stderr or 'ssh command failed'}"
        )

    storage_pools: list[ProxmoxStoragePool] = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 3:
            continue
        storage_pools.append(
            ProxmoxStoragePool(
                name=parts[0],
                type=parts[1],
                status=parts[2],
            )
        )
    return storage_pools


def _list_storage_names_for_content(
    node_ip: str,
    user: str,
    ssh_opts: StrList,
    content_type: str,
    dry_run: bool = False,
) -> set[str]:
    """Return pools supporting a specific content type."""
    result = _ssh_run(
        node_ip,
        user,
        ssh_opts,
        f"pvesm status --content {shlex.quote(content_type)}",
        dry_run=dry_run,
    )
    if dry_run:
        defaults = {
            "images": {"local-lvm"},
            "rootdir": {"local-lvm"},
            "vztmpl": {"local"},
        }
        return set(defaults.get(content_type, set()))
    if result.returncode != 0:
        return set()

    pools: set[str] = set()
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 3:
            continue
        if parts[2] == "active":
            pools.add(parts[0])
    return pools


def _choose_storage_pool(
    storage_pools: list[ProxmoxStoragePool],
    *,
    required_content: tuple[str, ...],
    preferred_names: tuple[str, ...],
) -> Optional[str]:
    """Pick a preferred active pool supporting at least one required content type."""
    active_pools = [
        pool for pool in storage_pools
        if (pool.status or "").lower() == "active"
    ]
    candidates = [
        pool for pool in active_pools
        if any(content in pool.content for content in required_content)
    ]
    if not candidates:
        return None

    for preferred in preferred_names:
        if not preferred:
            continue
        for pool in candidates:
            if pool.name == preferred:
                return pool.name
    return candidates[0].name


def probe_proxmox_host(
    node_ip: str,
    user: str = "root",
    hosted_key: Optional[str] = None,
    dry_run: bool = False,
) -> ProxmoxHostFacts:
    """Probe a Proxmox node for bridges, gateway, nameservers, and storage defaults."""
    ssh_opts = _ssh_opts(hosted_key)
    bridges = _list_proxmox_bridges(node_ip, user, ssh_opts, dry_run=dry_run)
    storage_pools = _list_storage_pools(node_ip, user, ssh_opts, dry_run=dry_run)

    images_pools = _list_storage_names_for_content(
        node_ip, user, ssh_opts, "images", dry_run=dry_run
    )
    rootdir_pools = _list_storage_names_for_content(
        node_ip, user, ssh_opts, "rootdir", dry_run=dry_run
    )
    vztmpl_pools = _list_storage_names_for_content(
        node_ip, user, ssh_opts, "vztmpl", dry_run=dry_run
    )
    for pool in storage_pools:
        content: list[str] = []
        if pool.name in images_pools:
            content.append("images")
        if pool.name in rootdir_pools:
            content.append("rootdir")
        if pool.name in vztmpl_pools:
            content.append("vztmpl")
        pool.content = content

    default_root_storage = _choose_storage_pool(
        storage_pools,
        required_content=("images", "rootdir"),
        preferred_names=("local-lvm", "local"),
    )
    default_template_storage = _choose_storage_pool(
        storage_pools,
        required_content=("vztmpl",),
        preferred_names=("local", default_root_storage or ""),
    )

    return ProxmoxHostFacts(
        node_name=_get_node_name(node_ip, user, ssh_opts, dry_run=dry_run),
        bridges=bridges,
        gateway=_get_host_gateway(node_ip, user, ssh_opts, dry_run=dry_run),
        nameservers=_get_host_nameservers(node_ip, user, ssh_opts, dry_run=dry_run),
        storage_pools=storage_pools,
        default_root_storage=default_root_storage,
        default_template_storage=default_template_storage,
        default_bridge=bridges[0] if bridges else None,
    )


def probe_proxmox_cluster(
    seed_address: str,
    user: str = "root",
    hosted_key: Optional[str] = None,
    *,
    tags: Optional[StrList] = None,
    dry_run: bool = False,
) -> list[ProxmoxHost]:
    """Probe every node in a Proxmox cluster from a single reachable seed node."""
    ssh_opts = _ssh_opts(hosted_key)
    _cluster_name, members = _parse_corosync_config(
        _get_corosync_config(seed_address, user, ssh_opts, dry_run=dry_run)
    )
    if not members:
        seed_name = _get_node_name(seed_address, user, ssh_opts, dry_run=dry_run)
        members = [(seed_name or seed_address, seed_address)]

    discovered_hosts: list[ProxmoxHost] = []
    seen_names: set[str] = set()
    seen_addresses: set[str] = set()
    for configured_name, address in members:
        facts = probe_proxmox_host(
            address,
            user=user,
            hosted_key=hosted_key,
            dry_run=dry_run,
        )
        host_name = facts.node_name or configured_name or address
        if host_name.lower() in seen_names or address in seen_addresses:
            continue
        seen_names.add(host_name.lower())
        seen_addresses.add(address)
        discovered_hosts.append(
            ProxmoxHost(
                name=host_name,
                address=address,
                user=user,
                ssh_key=hosted_key,
                default_storage=facts.default_root_storage,
                default_template_storage=facts.default_template_storage,
                default_bridge=facts.default_bridge,
                facts=facts,
                tags=list(tags or []),
            )
        )
    return discovered_hosts


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
    "_get_corosync_config",
    "_get_host_gateway",
    "_get_host_nameservers",
    "_get_next_vmid",
    "_get_node_name",
    "_is_usable_nameserver",
    "_parse_corosync_config",
    "_list_proxmox_bridges",
    "_list_storage_names_for_content",
    "_list_storage_pools",
    "_resolve_public_key_path",
    "_resolve_storage_pool",
    "_ssh_opts",
    "_ssh_run",
    "_storage_pool_supports_content",
    "_wait_for_guest_ssh",
    "auto_detect_bridge",
    "probe_proxmox_cluster",
    "probe_proxmox_host",
]
