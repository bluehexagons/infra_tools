#!/usr/bin/env python3
"""Proxmox LXC container provisioning via SSH.

Handles creating containers on a Proxmox host using pct/pveam CLI tools.
Designed to be called locally before remote_setup runs against the container.
"""

from __future__ import annotations

import ipaddress
import os
import re
import subprocess
import shlex
import sys
import time
from typing import Optional, cast

from lib.config import SetupConfig
from lib.types import NestedStrList, StrList


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


def _normalize_storage_specs(storage_specs: NestedStrList | None) -> list[StrList]:
    if not storage_specs:
        return []

    if isinstance(storage_specs[0], str):
        return [list(storage_specs)]  # type: ignore[list-item]

    return [list(spec) for spec in storage_specs]


def _get_storage_spec(storage_specs: NestedStrList | None, storage_type: str) -> Optional[StrList]:
    for spec in _normalize_storage_specs(storage_specs):
        if spec and spec[0] == storage_type:
            return spec
    return None


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
        for line in config_result.stdout.split('\n'):
            if not line.startswith('net0:'):
                continue
            # net0 line example:
            #   net0: name=eth0,bridge=vmbr0,ip=10.0.0.50/24,gw=10.0.0.1,type=veth
            match = re.search(r'(?:^|,)ip=([^,\s]+)', line)
            if not match:
                continue
            container_ip = match.group(1).split('/', 1)[0].strip()
            if container_ip == target_ip:
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


def _is_usable_nameserver(addr: str) -> bool:
    """Return True if addr is a globally routable nameserver the container can reach."""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    # Containers have their own loopback; the host's resolved stub at 127.0.0.53
    # (or any loopback / link-local / unspecified address) is not reachable from the container.
    if ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast:
        return False
    return True


def _get_host_nameservers(
    node_ip: str,
    user: str,
    ssh_opts: StrList,
    dry_run: bool = False
) -> StrList:
    """Get nameservers from the Proxmox host, filtering out unreachable addresses."""
    # Prefer resolvectl (gives upstream DNS even when /etc/resolv.conf points at the
    # systemd-resolved stub). Fall back to /etc/resolv.conf when resolvectl isn't installed.
    result = _ssh_run(
        node_ip, user, ssh_opts,
        "resolvectl dns 2>/dev/null | awk '{for (i=2;i<=NF;i++) print $i}' | sort -u; "
        "grep -oP '^nameserver\\s+\\K\\S+' /etc/resolv.conf",
        dry_run=dry_run
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
    content_filter: str,
    dry_run: bool = False
) -> str:
    """Resolve a storage pool name.

    If pool_arg is 'auto', find the first enabled pool with available space
    that supports the requested content type.
    """
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
        dry_run=dry_run
    )

    if dry_run:
        print("  [DRY-RUN] Would resolve storage pool")
        return "local-lvm"

    if result.returncode != 0:
        raise ProvisionError(
            f"Could not query storage pools for content type '{content_filter}'"
        )

    for line in result.stdout.strip().split('\n')[1:]:  # skip header
        parts = line.split()
        # pvesm status columns: Name Type Status Total Used Available %
        if len(parts) >= 3 and parts[2] == "active":
            pool = parts[0]
            print(f"  ✓ Auto-selected storage pool: {pool}")
            return pool

    raise ProvisionError(
        "No suitable storage pool found. Specify one explicitly with --storage root POOL AMOUNT or --storage template POOL"
    )


def _resolve_template_storage(
    root_pool: str,
    node_ip: str,
    user: str,
    ssh_opts: StrList,
    dry_run: bool = False
) -> str:
    """Find a storage pool that supports vztmpl content.

    Prefer the root pool if it already supports templates; otherwise auto-select
    the first active template-capable pool.
    """
    if _storage_pool_supports_content(
        root_pool, "vztmpl", node_ip, user, ssh_opts, dry_run=dry_run
    ):
        print(f"  ✓ Using root storage pool for templates: {root_pool}")
        return root_pool

    result = _ssh_run(
        node_ip, user, ssh_opts,
        "pvesm status --content vztmpl 2>/dev/null",
        dry_run=dry_run
    )

    if dry_run:
        print(f"  [DRY-RUN] Would auto-select template storage pool")
        return root_pool

    for line in result.stdout.strip().split('\n')[1:]:
        parts = line.split()
        if len(parts) >= 3 and parts[2] == "active":
            pool = parts[0]
            print(f"  ✓ Template storage pool: {pool}")
            return pool

    raise ProvisionError("No template storage pool found on the Proxmox host")


def _parse_pveam_available(stdout: str, system: str) -> StrList:
    """Parse `pveam available` output and return matching template filenames.

    pveam available emits whitespace-separated columns like:
        section          template_name
        system           debian-12-standard_12.7-1_amd64.tar.zst
        system           ubuntu-24.04-standard_24.04-1_amd64.tar.zst

    Older or differently-formatted output may use `section/template`. We accept either.
    The match requires `<system>-<digits>` so `--base debian` doesn't pull in
    `debian-12-turnkey-*` images by accident.
    """
    system_lc = system.lower()
    pattern = re.compile(rf'^{re.escape(system_lc)}-\d')
    matches: StrList = []
    for raw in (stdout or "").split('\n'):
        line = raw.strip()
        if not line or line.startswith('---') or line.upper().startswith('NAME') or line.upper().startswith('SECTION'):
            continue
        # Pick the last whitespace-separated field, then strip any leading "section/" prefix.
        candidate = line.split()[-1]
        candidate = candidate.rsplit('/', 1)[-1]
        cand_lc = candidate.lower()
        if not pattern.match(cand_lc):
            continue
        # Exclude derivative distributions that share the base name but ship a
        # different OS (e.g. debian-12-turnkey-wordpress is a TurnKey appliance,
        # not a stock Debian image).
        if '-turnkey-' in cand_lc:
            continue
        matches.append(candidate)
    return matches


def _template_sort_key(name: str) -> tuple:
    """Extract a comparable version key from a template filename.

    e.g. debian-12-standard_12.7-1_amd64.tar.zst -> (12, (12, 7, 1))
    Templates that don't match fall back to lexical order at the end.
    """
    m = re.search(r'-(\d+)[-.][^_]*_([\d.]+)', name)
    if not m:
        return (0, (), name)
    major = int(m.group(1))
    sub = tuple(int(p) for p in m.group(2).split('.') if p.isdigit())
    return (major, sub, name)


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
        "pveam available",
        dry_run=dry_run
    )

    system = base_arg.lower()
    candidates = _parse_pveam_available(result.stdout, system)

    if not candidates:
        # Also check what's already downloaded
        local_result = _ssh_run(
            node_ip, user, ssh_opts,
            f"pveam list {shlex.quote(template_storage)} 2>/dev/null",
            dry_run=dry_run
        )
        local_pattern = re.compile(rf'^{re.escape(system)}-\d')
        local_candidates: StrList = []
        for line in (local_result.stdout or "").strip().split('\n')[1:]:
            parts = line.split()
            if not parts:
                continue
            # pveam list rows typically show full storage path: local:vztmpl/<file>
            name = parts[0].rsplit('/', 1)[-1]
            if local_pattern.match(name.lower()):
                local_candidates.append(name)
        if local_candidates:
            local_candidates.sort(key=_template_sort_key)
            chosen = local_candidates[-1]
            template_path = f"/var/lib/vz/template/cache/{chosen}"
            if not template_storage.startswith("local"):
                template_path = f"{template_storage}:vztmpl/{chosen}"
            print(f"  ✓ Found downloaded template: {chosen}")
            return template_path

        raise ProvisionError(
            f"No template found matching '{base_arg}'. "
            f"Available templates can be listed with 'pveam available' on the Proxmox host"
        )

    # Pick the latest by version, not lexical order
    candidates.sort(key=_template_sort_key)
    template_name = candidates[-1]

    # Download if not already present
    print(f"  Downloading template: {template_name}")
    result = _ssh_run(
        node_ip, user, ssh_opts,
        f"pveam download {shlex.quote(template_storage)} {shlex.quote(template_name)}",
        dry_run=dry_run
    )
    if result.returncode != 0:
        raise ProvisionError(
            f"Template download failed for {template_name} on storage {template_storage}. "
            f"Error: {result.stderr.strip() or 'unknown error'}"
        )

    template_path = f"/var/lib/vz/template/cache/{template_name}"
    if not template_storage.startswith("local"):
        template_path = f"{template_storage}:vztmpl/{template_name}"

    print(f"  ✓ Template path: {template_path}")
    return template_path


def _build_container_hostname(target_ip: str, friendly_name: Optional[str]) -> str:
    """Derive a hostname for the container.

    Uses friendly_name if set, otherwise derives from IP. Result is clamped to
    63 characters per RFC 1123 so `pct create --hostname` accepts it.
    """
    if friendly_name:
        # Sanitize: lowercase, replace non-alphanumeric with hyphens
        hostname = re.sub(r'[^a-z0-9-]', '-', friendly_name.lower()).strip('-')
        # Remove consecutive hyphens
        hostname = re.sub(r'-+', '-', hostname)
        if hostname:
            return hostname[:63].rstrip('-') or hostname[:63]

    # Derive from IP: 10.0.0.50 → lxc-10-0-0-50
    return ("lxc-" + target_ip.replace(".", "-"))[:63]


def _resolve_public_key_path(ssh_key: Optional[str]) -> Optional[str]:
    """Return the local path to the public key matching the given private key, if any.

    Convention: <ssh_key>.pub. Returns None if ssh_key is unset, the .pub file is
    missing, or the file is empty.
    """
    if not ssh_key:
        return None
    pub_path = ssh_key + ".pub"
    try:
        if os.path.isfile(pub_path) and os.path.getsize(pub_path) > 0:
            return pub_path
    except OSError:
        return None
    return None


def _upload_pubkey_to_host(
    pub_path: str,
    node_ip: str,
    user: str,
    ssh_opts: StrList,
    dry_run: bool,
) -> Optional[str]:
    """Upload the local public key to a temp file on the Proxmox host.

    Returns the remote temp path so the caller can pass it to `pct create
    --ssh-public-keys`. Returns None on dry runs.
    """
    if dry_run:
        return "/tmp/infra_tools_pubkey.dryrun"

    try:
        with open(pub_path, "r", encoding="utf-8") as fh:
            pub_contents = fh.read()
    except OSError as exc:
        raise ProvisionError(f"Failed to read public key {pub_path}: {exc}")

    # mktemp on the host, then write the contents through ssh stdin.
    mk = _ssh_run(
        node_ip, user, ssh_opts,
        "mktemp /tmp/infra_tools_pubkey.XXXXXX",
        dry_run=False,
    )
    if mk.returncode != 0 or not mk.stdout.strip():
        raise ProvisionError(
            f"Failed to allocate temp file for SSH key on {node_ip}: "
            f"{(mk.stderr or '').strip() or 'mktemp failed'}"
        )
    remote_path = mk.stdout.strip()

    write_cmd = ["ssh"] + ssh_opts + [
        f"{user}@{node_ip}",
        f"cat > {shlex.quote(remote_path)} && chmod 600 {shlex.quote(remote_path)}",
    ]
    proc = subprocess.run(
        write_cmd, input=pub_contents, text=True, capture_output=True, timeout=60
    )
    if proc.returncode != 0:
        raise ProvisionError(
            f"Failed to upload public key to {node_ip}: "
            f"{proc.stderr.strip() or 'unknown error'}"
        )
    return remote_path


def _wait_for_container_ssh(
    target_ip: str,
    node_ip: str,
    user: str,
    ssh_opts: StrList,
    timeout: int = 90,
    dry_run: bool = False,
) -> None:
    """Wait for sshd inside the new container to accept TCP connections.

    Uses /dev/tcp from the Proxmox host so we don't need any local network
    visibility into the container.
    """
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
            print(f"  ✓ Container SSH is reachable at {target_ip}:22")
            return
        last_err = (result.stderr or result.stdout or "").strip()
        time.sleep(3)
    raise ProvisionError(
        f"Timed out after {timeout}s waiting for SSH on {target_ip}:22 "
        f"(last probe: {last_err or 'no response'})"
    )


def _create_container(
    vmid: int,
    target_ip: str,
    template_path: str,
    memory: str,
    cores: int,
    root_pool: str,
    storage_amount: str,
    cidr_prefix: str,
    bridge: str,
    gateway: str,
    nameservers: StrList,
    hostname: str,
    node_ip: str,
    user: str,
    ssh_opts: StrList,
    privileged: bool = False,
    dry_run: bool = False,
    ssh_pubkey_remote_path: Optional[str] = None,
) -> None:
    """Create and start the LXC container on the Proxmox host."""
    unprivileged = "0" if privileged else "1"

    cmd_parts = [
        f"pct create {vmid} {shlex.quote(template_path)}",
        f"--hostname {shlex.quote(hostname)}",
        f"--memory {shlex.quote(memory)}",
        f"--cores {cores}",
        f"--rootfs {shlex.quote(root_pool)}:{shlex.quote(storage_amount)}",
        (
            f"--net0 name=eth0,bridge={shlex.quote(bridge)},"
            f"ip={shlex.quote(target_ip)}/{shlex.quote(cidr_prefix)},"
            f"gw={shlex.quote(gateway)},type=veth"
        ),
        f"--nameserver {shlex.quote(' '.join(nameservers))}",
        f"--unprivileged {unprivileged}",
        "--onboot 1",
        "--start 1",
    ]
    if ssh_pubkey_remote_path:
        cmd_parts.insert(-1, f"--ssh-public-keys {shlex.quote(ssh_pubkey_remote_path)}")

    cmd = " ".join(cmd_parts)

    result = _ssh_run(node_ip, user, ssh_opts, cmd, dry_run=dry_run)
    if result.returncode != 0:
        raise ProvisionError(
            f"Container creation failed for VMID {vmid}: {result.stderr.strip() or result.stdout.strip() or 'unknown error'}"
        )

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


def provision_container(config: SetupConfig) -> None:
    """Orchestrate LXC container provisioning on a Proxmox host.

    Args:
        config: SetupConfig with hosted_node, container_memory, container_storage, etc.

    Raises:
        ContainerAlreadyExists: If a container with the target IP already exists.
        ProvisionError: If provisioning fails at any step.
    """
    node_ip = cast(str, config.hosted_node)
    memory = cast(str, config.container_memory)
    storage_specs = cast(NestedStrList, config.container_storage)
    user: str = config.hosted_user
    target_ip: str = config.host
    ssh_opts = _ssh_opts(config.hosted_key)
    dry_run = config.dry_run

    if dry_run:
        hostname = _build_container_hostname(target_ip, config.friendly_name)
        root_spec = _get_storage_spec(storage_specs, "root")
        template_spec = _get_storage_spec(storage_specs, "template")
        privileged = config.machine_type == "privileged"

        print("[DRY RUN] Would provision LXC container:")
        print(f"  Proxmox node: {node_ip}")
        print(f"  Target IP: {target_ip}")
        print(f"  Hostname: {hostname}")
        print(f"  Memory: {memory}")
        print(f"  Cores: {config.container_cores}")
        print(f"  Container type: {'privileged' if privileged else 'unprivileged'}")
        print(f"  Root storage: {root_spec[1] if root_spec else 'N/A'} ({root_spec[2] if root_spec else 'N/A'})")
        if template_spec:
            print(f"  Template storage: {template_spec[1]}")
        else:
            print(f"  Template storage: auto-detect")
        print(f"  Base OS: {config.container_base}")
        print(f"  Storage specs: {storage_specs}")
        return

    # Check if already provisioned
    if check_container_exists(
        node_ip, target_ip, user, config.hosted_key, dry_run=dry_run
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

    root_spec = _get_storage_spec(storage_specs, "root")
    if not root_spec:
        raise ProvisionError("Missing root storage specification")

    template_spec = _get_storage_spec(storage_specs, "template")

    root_pool_arg = root_spec[1]
    storage_amount = root_spec[2]

    root_pool = _resolve_storage_pool(
        root_pool_arg, node_ip, user, ssh_opts, "images,rootdir"
    )

    # Template storage
    if template_spec:
        template_pool_arg = template_spec[1]
        if template_pool_arg == "auto":
            template_storage = _resolve_storage_pool(
                "auto", node_ip, user, ssh_opts, "vztmpl"
            )
        else:
            template_storage = _resolve_storage_pool(
                template_pool_arg, node_ip, user, ssh_opts, "vztmpl"
            )
    else:
        template_storage = _resolve_template_storage(root_pool, node_ip, user, ssh_opts)

    # Resolve and download template
    template_path = _resolve_template_name(
        config.container_base, template_storage, node_ip, user, ssh_opts
    )

    cidr_prefix = _get_bridge_prefix_length(
        node_ip, user, ssh_opts, bridge, dry_run=dry_run
    )

    # Get next VMID
    vmid = _get_next_vmid(node_ip, user, ssh_opts)

    # Determine privileged/unprivileged
    privileged = config.machine_type == "privileged"

    # Bootstrap SSH access into the new container so the subsequent remote_setup phase
    # can connect as root via the user's SSH key. Without this, pct create leaves root
    # with no usable credentials and the orchestration would hang on password auth.
    pub_path = _resolve_public_key_path(config.ssh_key)
    remote_pubkey_path: Optional[str] = None
    if pub_path:
        print(f"  Uploading public key for container access: {pub_path}")
        remote_pubkey_path = _upload_pubkey_to_host(
            pub_path, node_ip, user, ssh_opts, dry_run=dry_run
        )
    else:
        print(
            "  ⚠ No SSH public key found alongside --key; the new container will have "
            "no root credentials and remote setup will be unable to connect."
        )

    try:
        # Create container
        _create_container(
            vmid=vmid,
            target_ip=target_ip,
            template_path=template_path,
            memory=memory,
            cores=config.container_cores,
            root_pool=root_pool,
            storage_amount=storage_amount,
            cidr_prefix=cidr_prefix,
            bridge=bridge,
            gateway=gateway,
            nameservers=nameservers,
            hostname=hostname,
            node_ip=node_ip,
            user=user,
            ssh_opts=ssh_opts,
            privileged=privileged,
            dry_run=dry_run,
            ssh_pubkey_remote_path=remote_pubkey_path,
        )

        # Wait for sshd in the container to come up before handing off to remote_setup.
        if remote_pubkey_path:
            _wait_for_container_ssh(
                target_ip, node_ip, user, ssh_opts, dry_run=dry_run
            )
    finally:
        if remote_pubkey_path and not dry_run:
            _ssh_run(
                node_ip, user, ssh_opts,
                f"rm -f {shlex.quote(remote_pubkey_path)}",
                dry_run=False,
            )
