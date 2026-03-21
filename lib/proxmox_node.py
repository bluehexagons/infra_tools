#!/usr/bin/env python3
"""Proxmox LXC container provisioning via SSH.

Handles creating containers on a Proxmox host using pct/pveam CLI tools.
Designed to be called locally before remote_setup runs against the container.
"""

from __future__ import annotations

import re
import subprocess
import shlex
import sys
from typing import Optional

from lib.types import StrList


class ContainerAlreadyExists(Exception):
    """Raised when the target container already exists on the Proxmox node."""


class ProvisionError(Exception):
    """Raised when container provisioning fails."""


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
    dry_run: bool = False
) -> subprocess.CompletedProcess[str]:
    """Run a command on the Proxmox host via SSH."""
    log_cmd = cmd[:80] + "..." if len(cmd) > 80 else cmd
    print(f"  Running on {node_ip}: {log_cmd}")
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


def check_container_exists(
    node_ip: str,
    target_ip: str,
    user: str = "root",
    hosted_key: Optional[str] = None,
    dry_run: bool = False
) -> bool:
    """Check if a container with the target IP already exists on the node.

    Checks all running/stopped containers' network config for the target IP.
    """
    opts = _ssh_opts(hosted_key)
    result = _ssh_run(
        node_ip, user, opts,
        "pct list | awk 'NR>1 {print $1}'",
        dry_run=dry_run
    )

    if dry_run or not result.stdout.strip():
        return False

    for vmid in result.stdout.strip().split('\n'):
        vmid = vmid.strip()
        if not vmid:
            continue
        config_result = _ssh_run(
            node_ip, user, opts,
            f"pct config {vmid}",
            dry_run=dry_run
        )
        if target_ip in config_result.stdout:
            print(f"  ✓ Container VMID {vmid} already exists with IP {target_ip}")
            return True

    return False


def auto_detect_bridge(
    node_ip: str,
    user: str = "root",
    hosted_key: Optional[str] = None,
    dry_run: bool = False
) -> str:
    """Auto-detect the network bridge on the Proxmox host.

    Looks for vmbr* interfaces, preferring vmbr0.
    """
    opts = _ssh_opts(hosted_key)
    result = _ssh_run(
        node_ip, user, opts,
        "ip -o link show | grep -o 'vmbr[0-9]*' | head -5",
        dry_run=dry_run
    )

    if dry_run:
        print("  [DRY-RUN] Would detect bridge")
        return "vmbr0"

    bridges = result.stdout.strip().split('\n') if result.stdout.strip() else []

    if not bridges:
        raise ProvisionError(
            "No vmbr* network bridge found on the Proxmox host"
        )

    bridge = bridges[0].strip()
    if bridge != "vmbr0" and "vmbr0" in bridges:
        bridge = "vmbr0"

    print(f"  ✓ Detected bridge: {bridge}")
    return bridge


def _get_host_gateway(
    node_ip: str,
    user: str,
    ssh_opts: StrList,
    dry_run: bool = False
) -> str:
    """Get the default gateway from the Proxmox host."""
    result = _ssh_run(
        node_ip, user, ssh_opts,
        "ip route | awk '/default/ {print $3; exit}'",
        dry_run=dry_run
    )

    if dry_run:
        return "10.0.0.1"

    gateway = result.stdout.strip()
    if not gateway:
        raise ProvisionError("Could not detect default gateway on Proxmox host")

    print(f"  ✓ Detected gateway: {gateway}")
    return gateway


def _get_host_nameservers(
    node_ip: str,
    user: str,
    ssh_opts: StrList,
    dry_run: bool = False
) -> StrList:
    """Get nameservers from the Proxmox host."""
    result = _ssh_run(
        node_ip, user, ssh_opts,
        "grep -oP '^nameserver\\s+\\K.*' /etc/resolv.conf | head -3",
        dry_run=dry_run
    )

    if dry_run:
        return ["8.8.8.8"]

    nameservers = [
        ns.strip() for ns in result.stdout.strip().split('\n')
        if ns.strip()
    ]

    if not nameservers:
        print("  ⚠ No nameservers found, using 8.8.8.8")
        return ["8.8.8.8"]

    print(f"  ✓ Detected nameservers: {', '.join(nameservers)}")
    return nameservers


def _get_next_vmid(
    node_ip: str,
    user: str,
    ssh_opts: StrList,
    dry_run: bool = False
) -> int:
    """Get the next available VMID from the Proxmox cluster."""
    result = _ssh_run(
        node_ip, user, ssh_opts,
        "pvesh get /cluster/nextid",
        dry_run=dry_run
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
    dry_run: bool = False
) -> str:
    """Resolve a storage pool name.

    If pool_arg is 'auto', find the first enabled pool with available space
    that supports the requested content type.
    """
    if pool_arg != "auto":
        print(f"  ✓ Using storage pool: {pool_arg}")
        return pool_arg

    result = _ssh_run(
        node_ip, user, ssh_opts,
        "pvesm status --content images,rootdir 2>/dev/null || pvesm status",
        dry_run=dry_run
    )

    if dry_run:
        print("  [DRY-RUN] Would resolve storage pool")
        return "local-lvm"

    for line in result.stdout.strip().split('\n')[1:]:  # skip header
        parts = line.split()
        # pvesm status columns: Name Type Status Total Used Available %
        if len(parts) >= 3 and parts[2] == "active":
            pool = parts[0]
            print(f"  ✓ Auto-selected storage pool: {pool}")
            return pool

    raise ProvisionError(
        "No suitable storage pool found. Specify one explicitly with --storage TYPE POOL AMOUNT"
    )


def _resolve_template_storage(
    root_pool: str,
    node_ip: str,
    user: str,
    ssh_opts: StrList,
    dry_run: bool = False
) -> str:
    """Find a storage pool that supports vztmpl content.

    Falls back to root_pool if it supports templates.
    """
    result = _ssh_run(
        node_ip, user, ssh_opts,
        "pvesm status --content vztmpl 2>/dev/null",
        dry_run=dry_run
    )

    if dry_run:
        return root_pool

    for line in result.stdout.strip().split('\n')[1:]:
        parts = line.split()
        if len(parts) >= 3 and parts[2] == "active":
            pool = parts[0]
            print(f"  ✓ Template storage pool: {pool}")
            return pool

    # Fall back: check if root pool supports templates
    check = _ssh_run(
        node_ip, user, ssh_opts,
        f"pvesm status | grep '^{shlex.quote(root_pool)}'",
        dry_run=dry_run
    )
    if root_pool in check.stdout:
        print(f"  ✓ Using root storage pool for templates: {root_pool}")
        return root_pool

    raise ProvisionError(
        "No template storage pool found on the Proxmox host"
    )


def _resolve_template_name(
    base_arg: str,
    template_storage: str,
    node_ip: str,
    user: str,
    ssh_opts: StrList,
    dry_run: bool = False
) -> str:
    """Resolve a base OS argument to a concrete template path.

    Queries pveam available on the host to find the latest matching template.
    """
    # Update template list
    _ssh_run(node_ip, user, ssh_opts, "pveam update", dry_run=dry_run)

    if dry_run:
        return f"/var/lib/vz/template/cache/{base_arg}-12-standard_12.0-1_amd64.tar.zst"

    # List available templates
    result = _ssh_run(
        node_ip, user, ssh_opts,
        f"pveam available --section {shlex.quote(template_storage)} 2>/dev/null || pveam available",
        dry_run=dry_run
    )

    system = base_arg.lower()
    candidates = []

    for line in result.stdout.strip().split('\n'):
        line = line.strip()
        if not line or line.startswith("---") or line.startswith("NAME"):
            continue
        # pveam available output: system/ or system-version-standard_version_arch.tar.*
        parts = line.split('/')
        template_name = parts[-1] if len(parts) > 1 else parts[0]
        if template_name.lower().startswith(system):
            candidates.append(template_name)

    if not candidates:
        # Also check what's already downloaded
        local_result = _ssh_run(
            node_ip, user, ssh_opts,
            f"pveam list {shlex.quote(template_storage)} 2>/dev/null",
            dry_run=dry_run
        )
        for line in local_result.stdout.strip().split('\n')[1:]:
            parts = line.split()
            if parts and parts[0].lower().startswith(system):
                template_path = f"/var/lib/vz/template/cache/{parts[0]}"
                if not template_storage.startswith("local"):
                    template_path = f"{template_storage}:vztmpl/{parts[0]}"
                print(f"  ✓ Found downloaded template: {parts[0]}")
                return template_path

        raise ProvisionError(
            f"No template found matching '{base_arg}'. "
            f"Available templates can be listed with 'pveam available' on the Proxmox host"
        )

    # Pick the latest (last in sorted order, which for versioned names gives latest)
    candidates.sort()
    template_name = candidates[-1]

    # Download if not already present
    print(f"  Downloading template: {template_name}")
    _ssh_run(
        node_ip, user, ssh_opts,
        f"pveam download {shlex.quote(template_storage)} {shlex.quote(template_name)}",
        dry_run=dry_run
    )

    template_path = f"/var/lib/vz/template/cache/{template_name}"
    if not template_storage.startswith("local"):
        template_path = f"{template_storage}:vztmpl/{template_name}"

    print(f"  ✓ Template path: {template_path}")
    return template_path


def _build_container_hostname(target_ip: str, friendly_name: Optional[str]) -> str:
    """Derive a hostname for the container.

    Uses friendly_name if set, otherwise derives from IP.
    """
    if friendly_name:
        # Sanitize: lowercase, replace non-alphanumeric with hyphens
        hostname = re.sub(r'[^a-z0-9-]', '-', friendly_name.lower()).strip('-')
        # Remove consecutive hyphens
        hostname = re.sub(r'-+', '-', hostname)
        if hostname:
            return hostname

    # Derive from IP: 10.0.0.50 → lxc-10-0-0-50
    return "lxc-" + target_ip.replace(".", "-")


def _create_container(
    vmid: int,
    target_ip: str,
    template_path: str,
    memory: str,
    cores: int,
    root_pool: str,
    storage_amount: str,
    bridge: str,
    gateway: str,
    nameservers: StrList,
    hostname: str,
    node_ip: str,
    user: str,
    ssh_opts: StrList,
    privileged: bool = False,
    dry_run: bool = False
) -> None:
    """Create and start the LXC container on the Proxmox host."""
    unprivileged = "0" if privileged else "1"

    cmd = (
        f"pct create {vmid} {shlex.quote(template_path)} "
        f"--hostname {shlex.quote(hostname)} "
        f"--memory {shlex.quote(memory)} "
        f"--cores {cores} "
        f"--rootfs {shlex.quote(root_pool)}:{shlex.quote(storage_amount)} "
        f"--net0 name=eth0,bridge={shlex.quote(bridge)},"
        f"ip={shlex.quote(target_ip)}/24,gw={shlex.quote(gateway)},type=veth "
        f"--nameserver {shlex.quote(' '.join(nameservers))} "
        f"--unprivileged {unprivileged} "
        f"--start 1"
    )

    _ssh_run(node_ip, user, ssh_opts, cmd, dry_run=dry_run)

    if not dry_run:
        # Verify it started
        status_result = _ssh_run(
            node_ip, user, ssh_opts,
            f"pct status {vmid}",
            dry_run=dry_run
        )
        if "running" not in status_result.stdout:
            raise ProvisionError(
                f"Container {vmid} was created but is not running. "
                f"Status: {status_result.stdout.strip()}"
            )

    print(f"  ✓ Container {vmid} created and started ({hostname}, {target_ip})")


def provision_container(config) -> None:
    """Orchestrate LXC container provisioning on a Proxmox host.

    Args:
        config: SetupConfig with hosted_node, container_memory, container_storage, etc.

    Raises:
        ContainerAlreadyExists: If a container with the target IP already exists.
        ProvisionError: If provisioning fails at any step.
    """
    node_ip = config.hosted_node
    user = config.hosted_user
    target_ip = config.host
    ssh_opts = _ssh_opts(config.hosted_key)
    dry_run = config.dry_run

    if dry_run:
        print("[DRY RUN] Would provision LXC container:")
        print(f"  Proxmox node: {node_ip}")
        print(f"  Target IP: {target_ip}")
        print(f"  Memory: {config.container_memory}")
        print(f"  Cores: {config.container_cores}")
        print(f"  Storage: {config.container_storage}")
        print(f"  Base: {config.container_base}")
        return

    # Check if already provisioned
    if check_container_exists(
        node_ip, target_ip, user, config.hosted_key, dry_run=False
    ):
        raise ContainerAlreadyExists(
            f"Container with IP {target_ip} already exists on {node_ip}"
        )

    # Resolve hostname
    hostname = _build_container_hostname(target_ip, config.friendly_name)
    print(f"  Hostname: {hostname}")

    # Auto-detect bridge
    bridge = auto_detect_bridge(
        node_ip, user, config.hosted_key
    )

    # Detect gateway and nameservers
    gateway = _get_host_gateway(node_ip, user, ssh_opts)
    nameservers = _get_host_nameservers(node_ip, user, ssh_opts)

    # Resolve storage pools
    storage_type = config.container_storage[0]
    root_pool_arg = config.container_storage[1]
    storage_amount = config.container_storage[2]

    root_pool = _resolve_storage_pool(root_pool_arg, node_ip, user, ssh_opts)

    # Template storage
    if storage_type == "template":
        template_storage = _resolve_storage_pool(
            root_pool_arg, node_ip, user, ssh_opts
        )
    else:
        template_storage = _resolve_template_storage(
            root_pool, node_ip, user, ssh_opts
        )

    # Resolve and download template
    template_path = _resolve_template_name(
        config.container_base, template_storage, node_ip, user, ssh_opts
    )

    # Get next VMID
    vmid = _get_next_vmid(node_ip, user, ssh_opts)

    # Determine privileged/unprivileged
    privileged = config.machine_type == "privileged"

    # Create container
    _create_container(
        vmid=vmid,
        target_ip=target_ip,
        template_path=template_path,
        memory=config.container_memory,
        cores=config.container_cores,
        root_pool=root_pool,
        storage_amount=storage_amount,
        bridge=bridge,
        gateway=gateway,
        nameservers=nameservers,
        hostname=hostname,
        node_ip=node_ip,
        user=user,
        ssh_opts=ssh_opts,
        privileged=privileged,
        dry_run=False
    )
