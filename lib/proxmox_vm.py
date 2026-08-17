#!/usr/bin/env python3
"""Proxmox VM provisioning via SSH using ``qm`` + cloud-init.

Mirrors :mod:`lib.proxmox_node`'s LXC provisioning so that the rest of the
setup pipeline can hand off to ``remote_setup`` regardless of whether the
target is an LXC container or a VM.

The flow is:

1. Resolve the cloud image (curated catalog, explicit URL, or pre-uploaded
   ``storage:iso/...`` reference).
2. Download the qcow2 onto the Proxmox node, verify SHA-512 when known.
3. Allocate the next VMID, detect the bridge / gateway / nameservers (reused
   helpers from :mod:`lib.proxmox_node`).
4. ``qm create`` with a recovery console + virtio-scsi. Desktop/RDP guests
   receive VirtIO-GPU for noVNC; server guests retain the serial console.
5. ``qm disk import`` (or ``--import-from``) the qcow2 into the root storage,
   attach as ``scsi0``, set boot order, attach a cloud-init drive.
6. Cloud-init: user/SSH key/IP from infra_tools, then resize to the requested
   size and ``qm start``.
7. Wait for SSH on the target IP.
"""

from __future__ import annotations

import ipaddress
import shlex
import subprocess
import time
from dataclasses import dataclass
from typing import Optional, cast

from lib.cloud_images import (
    CloudImage,
    is_local_image_ref,
    parse_image_argument,
    resolve_cloud_image,
)
from lib.config import SetupConfig
from lib.proxmox_guest import (
    ProvisionError,
    _build_guest_hostname,
    _get_bridge_prefix_length,
    _get_guest_gateway,
    _get_host_nameservers,
    _get_next_vmid,
    _resolve_public_key_path,
    _resolve_storage_pool,
    _ssh_opts,
    _ssh_run,
    _wait_for_guest_ssh,
    auto_detect_bridge,
)
from lib.types import NestedStrList, StrList


class VMAlreadyExists(Exception):
    """Raised when a VM with the target IP already exists on the Proxmox node."""


@dataclass
class _ResolvedImage:
    """Either a remote URL with optional sha512, or an existing storage ref."""
    url: Optional[str]
    sha512: Optional[str]
    filename: Optional[str]
    storage_ref: Optional[str]


_UNIT_TO_KIB = {"K": 1, "M": 1024, "G": 1024 * 1024, "T": 1024 * 1024 * 1024}


def _parse_size_kib(value: str, *, label: str) -> int:
    s = (value or "").strip()
    if not s:
        raise ProvisionError(f"{label} must be a non-empty string like '2G'")
    unit = s[-1].upper()
    if unit in _UNIT_TO_KIB:
        digits, multiplier = s[:-1], _UNIT_TO_KIB[unit]
    else:
        digits, multiplier = s, _UNIT_TO_KIB["M"]  # bare number = MiB
    try:
        n = int(digits)
    except ValueError as exc:
        raise ProvisionError(f"Invalid {label}: {value!r}") from exc
    if n <= 0:
        raise ProvisionError(f"{label} must be positive (got {value!r})")
    return n * multiplier


def _parse_memory_mb(value: str) -> int:
    """Convert a memory string like ``2G`` / ``512M`` to mebibytes."""
    return max(1, _parse_size_kib(value, label="VM memory") // 1024)


def _parse_disk_size_gib(value: str) -> int:
    """Convert a storage amount like ``32G`` / ``2T`` / ``8192M`` to GiB."""
    gib = _parse_size_kib(value, label="VM disk size") // (1024 * 1024)
    if gib < 1:
        raise ProvisionError(f"VM disk must be at least 1G (got {value!r})")
    return gib


def _needs_graphical_console(config: SetupConfig) -> bool:
    """Return whether a hosted VM needs a Proxmox graphical console."""
    return config.include_desktop or config.enable_rdp


def check_vm_exists(
    node_ip: str,
    target_ip: str,
    user: str,
    ssh_opts: StrList,
    *,
    dry_run: bool = False,
) -> bool:
    """Return True if any VM on ``node_ip`` is configured with ``target_ip``."""
    if dry_run:
        return False
    result = _ssh_run(node_ip, user, ssh_opts, "qm list", dry_run=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() or "unknown error"
        raise ProvisionError(f"Failed to query VMs on {node_ip}: {detail}")
    vmids: StrList = []
    for line in (result.stdout or "").splitlines()[1:]:
        parts = line.split()
        if not parts:
            continue
        try:
            vmids.append(str(int(parts[0])))
        except ValueError:
            continue
    for vmid in vmids:
        cfg = _ssh_run(node_ip, user, ssh_opts, f"qm config {vmid}", dry_run=False)
        if cfg.returncode != 0:
            detail = (cfg.stderr or cfg.stdout or "").strip() or "unknown error"
            raise ProvisionError(f"Failed to inspect VM {vmid} on {node_ip}: {detail}")
        if f"ip={target_ip}/" in (cfg.stdout or "") or f"ip={target_ip}," in (cfg.stdout or ""):
            status = _ssh_run(node_ip, user, ssh_opts, f"qm status {vmid}", dry_run=False)
            probe = _ssh_run(
                node_ip,
                user,
                ssh_opts,
                f"timeout 3 bash -c '</dev/tcp/{shlex.quote(target_ip)}/22' && echo READY",
                dry_run=False,
            )
            if status.returncode == 0 and "status: running" in (status.stdout or "") and "READY" in (probe.stdout or ""):
                print(f"  ✓ VM {vmid} already exists and is reachable at IP {target_ip}")
                return True
            raise ProvisionError(
                f"VM {vmid} is configured with IP {target_ip} but is not reachable on SSH; "
                "remove or repair it before retrying provisioning"
            )
    return False


def _resolve_image(
    config: SetupConfig,
    explicit: Optional[str],
) -> tuple[_ResolvedImage, CloudImage | None]:
    """Resolve the image source from ``--image`` or the catalog.

    Returns the resolved image reference plus the catalog entry that backed it
    (if any) for logging purposes.
    """
    if explicit:
        url, storage_ref = parse_image_argument(explicit)
        if storage_ref:
            return (
                _ResolvedImage(url=None, sha512=None, filename=None, storage_ref=storage_ref),
                None,
            )
        if url:
            filename = url.rsplit("/", 1)[-1]
            return (
                _ResolvedImage(url=url, sha512=None, filename=filename, storage_ref=None),
                None,
            )
    image = resolve_cloud_image(config.container_base or "debian")
    return (
        _ResolvedImage(
            url=image["url"],
            sha512=image["sha512"] or None,
            filename=image["filename"],
            storage_ref=None,
        ),
        image,
    )


def _download_image_to_host(
    image: _ResolvedImage,
    storage_pool: str,
    node_ip: str,
    user: str,
    ssh_opts: StrList,
    *,
    dry_run: bool,
) -> str:
    """Fetch ``image`` onto the Proxmox node; return the absolute remote path."""
    if not image.url or not image.filename:
        raise ProvisionError("Internal error: download requested without URL")
    image_ref = f"{storage_pool}:iso/{image.filename}"
    if dry_run:
        remote_path = f"/var/lib/vz/template/iso/{image.filename}"
    else:
        path_result = _ssh_run(
            node_ip,
            user,
            ssh_opts,
            f"pvesm path {shlex.quote(image_ref)}",
            dry_run=False,
        )
        remote_path = (path_result.stdout or "").strip()
        if path_result.returncode != 0 or not remote_path or not remote_path.startswith("/"):
            raise ProvisionError(
                f"Could not resolve image storage path for {image_ref}: "
                f"{(path_result.stderr or path_result.stdout or '').strip() or 'pvesm path failed'}"
            )
    remote_dir = remote_path.rsplit("/", 1)[0]

    if dry_run:
        print(f"  [DRY-RUN] Would download {image.url} → {remote_path}")
        return remote_path

    mkdir_result = _ssh_run(
        node_ip, user, ssh_opts, f"mkdir -p {shlex.quote(remote_dir)}"
    )
    if mkdir_result.returncode != 0:
        raise ProvisionError(
            f"Failed to prepare image storage path on {node_ip}: "
            f"{(mkdir_result.stderr or mkdir_result.stdout or '').strip() or 'mkdir failed'}"
        )
    fetch = (
        f"if [ ! -f {shlex.quote(remote_path)} ]; then "
        f"wget -q --show-progress -O {shlex.quote(remote_path)}.part "
        f"{shlex.quote(image.url)} && "
        f"mv {shlex.quote(remote_path)}.part {shlex.quote(remote_path)}; "
        f"fi"
    )
    print(f"  Downloading cloud image: {image.url}")
    result = _ssh_run(node_ip, user, ssh_opts, fetch)
    if result.returncode != 0:
        raise ProvisionError(
            f"Failed to download cloud image on {node_ip}: "
            f"{(result.stderr or result.stdout or '').strip() or 'unknown error'}"
        )
    if image.sha512:
        check = (
            f"echo {shlex.quote(image.sha512 + '  ' + remote_path)} "
            f"| sha512sum -c -"
        )
        verify = _ssh_run(node_ip, user, ssh_opts, check)
        if verify.returncode != 0:
            raise ProvisionError(
                f"SHA-512 verification failed for {image.filename} on {node_ip}: "
                f"{(verify.stderr or verify.stdout or '').strip()}"
            )
        print(f"  ✓ SHA-512 verified")
    else:
        print(f"  ⚠ No SHA-512 pinned for {image.filename}; skipping verification")

    return remote_path


def _render_user_data(
    *,
    username: str,
    pubkey_contents: Optional[str],
) -> str:
    """Build a minimal cloud-init user-data document.

    Creates ``username`` (with sudo NOPASSWD) and installs the SSH key. The
    rest of infra_tools' setup runs over SSH afterward, so we keep this short.
    """
    normalized_pubkey = pubkey_contents.strip() if pubkey_contents else None
    if normalized_pubkey and any(
        ord(char) < 32 or ord(char) == 127 for char in normalized_pubkey
    ):
        raise ProvisionError(
            "SSH public key must be a single line without control characters"
        )
    pubkey_yaml = (
        "'" + normalized_pubkey.replace("'", "''") + "'"
        if normalized_pubkey
        else None
    )
    lines = [
        "#cloud-config",
        f"hostname: __HOSTNAME__",
        "manage_etc_hosts: true",
        "package_update: true",
        "packages:",
        "  - qemu-guest-agent",
        "write_files:",
        "  - path: /etc/modules-load.d/infra-tools-virtio-balloon.conf",
        "    permissions: '0644'",
        "    content: |",
        "      virtio_balloon",
        "users:",
        "  - name: root",
        "    lock_passwd: false",
    ]
    if pubkey_yaml:
        lines.append("    ssh_authorized_keys:")
        lines.append(f"      - {pubkey_yaml}")
    if username and username != "root":
        lines.extend([
            f"  - name: {username}",
            "    groups: sudo",
            "    sudo: 'ALL=(ALL) NOPASSWD:ALL'",
            "    shell: /bin/bash",
            "    lock_passwd: false",
        ])
        if pubkey_yaml:
            lines.append("    ssh_authorized_keys:")
            lines.append(f"      - {pubkey_yaml}")
    lines.append("ssh_pwauth: false")
    lines.extend([
        "runcmd:",
        "  - modprobe virtio_balloon",
        "  - systemctl enable --now qemu-guest-agent",
    ])
    lines.append("")
    return "\n".join(lines)


def _upload_user_data(
    user_data: str,
    hostname: str,
    storage_pool: str,
    node_ip: str,
    user: str,
    ssh_opts: StrList,
    *,
    dry_run: bool,
) -> Optional[str]:
    """Write the rendered user-data to a snippet on the node and return its path."""
    filename = f"infra_tools-{hostname}.yaml"
    snippet_ref = f"{storage_pool}:snippets/{filename}"
    if dry_run:
        return "/var/lib/vz/snippets/infra_tools-userdata.dryrun.yaml"

    rendered = user_data.replace("__HOSTNAME__", hostname)
    path_result = _ssh_run(
        node_ip,
        user,
        ssh_opts,
        f"pvesm path {shlex.quote(snippet_ref)}",
        dry_run=False,
    )
    remote_path = (path_result.stdout or "").strip()
    if path_result.returncode != 0 or not remote_path or not remote_path.startswith("/"):
        raise ProvisionError(
            f"Could not resolve snippet storage path for {snippet_ref}: "
            f"{(path_result.stderr or path_result.stdout or '').strip() or 'pvesm path failed'}"
        )
    snippets_dir = remote_path.rsplit("/", 1)[0]
    mkdir_result = _ssh_run(
        node_ip, user, ssh_opts, f"mkdir -p {shlex.quote(snippets_dir)}"
    )
    if mkdir_result.returncode != 0:
        raise ProvisionError(
            f"Failed to prepare snippet storage path on {node_ip}: "
            f"{(mkdir_result.stderr or mkdir_result.stdout or '').strip() or 'mkdir failed'}"
        )
    write_cmd = ["ssh"] + ssh_opts + [
        f"{user}@{node_ip}",
        f"cat > {shlex.quote(remote_path)}",
    ]
    proc = subprocess.run(
        write_cmd, input=rendered, text=True, capture_output=True, timeout=60
    )
    if proc.returncode != 0:
        raise ProvisionError(
            f"Failed to upload cloud-init user-data to {node_ip}: "
            f"{proc.stderr.strip() or 'unknown error'}"
        )
    return remote_path


def _destroy_vm_best_effort(
    vmid: int,
    node_ip: str,
    user: str,
    ssh_opts: StrList,
) -> None:
    """Remove a VM created by this run after a failed provisioning attempt."""
    print(f"  ⚠ Cleaning up partially provisioned VM {vmid}")
    _ssh_run(node_ip, user, ssh_opts, f"qm stop {vmid} --skiplock 1", dry_run=False)
    _ssh_run(
        node_ip,
        user,
        ssh_opts,
        f"qm destroy {vmid} --purge 1 --skiplock 1",
        dry_run=False,
    )


def _create_vm(
    *,
    vmid: int,
    target_ip: str,
    image_remote_path: Optional[str],
    storage_ref: Optional[str],
    memory_mb: int,
    balloon_min_mb: int,
    cores: int,
    root_pool: str,
    disk_size_gib: int,
    cidr_prefix: str,
    bridge: str,
    gateway: str,
    nameservers: StrList,
    hostname: str,
    user_data_path: Optional[str],
    user_data_ref: Optional[str],
    graphical_console: bool,
    node_ip: str,
    user: str,
    ssh_opts: StrList,
    dry_run: bool = False,
    ipv6_cidr: Optional[str] = None,
    gateway6: Optional[str] = None,
) -> bool:
    """Build, populate, and start the VM on ``node_ip``."""
    ipconfig_parts = [
        f"ip={target_ip}/{cidr_prefix}",
        f"gw={gateway}",
    ]
    if ipv6_cidr:
        ipconfig_parts.append(f"ip6={ipv6_cidr}")
        if gateway6:
            ipconfig_parts.append(f"gw6={gateway6}")

    create_parts = [
        f"qm create {vmid}",
        f"--name {shlex.quote(hostname)}",
        f"--memory {memory_mb}",
        f"--balloon {balloon_min_mb}",
        f"--cores {cores}",
        "--cpu host",
        "--ostype l26",
        "--scsihw virtio-scsi-single",
        "--serial0 socket",
        "--vga virtio" if graphical_console else "--vga serial0",
        "--agent enabled=1,freeze-fs=1",
        "--rng0 source=/dev/urandom",
        (
            f"--net0 virtio,bridge={shlex.quote(bridge)}"
        ),
        f"--ipconfig0 {shlex.quote(','.join(ipconfig_parts))}",
        f"--nameserver {shlex.quote(' '.join(nameservers))}",
        "--onboot 1",
    ]
    if user_data_ref:
        create_parts.append(f"--cicustom user={shlex.quote(user_data_ref)}")

    create_cmd = " ".join(create_parts)
    result = _ssh_run(node_ip, user, ssh_opts, create_cmd, dry_run=dry_run)
    if result.returncode != 0:
        raise ProvisionError(
            f"qm create {vmid} failed: "
            f"{(result.stderr or result.stdout or '').strip() or 'unknown error'}"
        )
    created = True

    # Attach the disk: prefer importing the qcow2; otherwise reference the
    # pre-uploaded storage volume directly.
    if image_remote_path:
        # Let Proxmox choose the target's native image format. Block-backed
        # pools such as LVM-thin only support raw volumes, while directory
        # pools commonly use qcow2.
        import_cmd = (
            f"qm disk import {vmid} {shlex.quote(image_remote_path)} "
            f"{shlex.quote(root_pool)}"
        )
        imported = _ssh_run(node_ip, user, ssh_opts, import_cmd, dry_run=dry_run)
        if imported.returncode != 0:
            if not dry_run and created:
                _destroy_vm_best_effort(vmid, node_ip, user, ssh_opts)
            raise ProvisionError(
                f"qm disk import for VM {vmid} failed: "
                f"{(imported.stderr or imported.stdout or '').strip() or 'unknown error'}"
            )
        # Proxmox names the imported volume {pool}:vm-{vmid}-disk-0.
        disk_volume = f"{root_pool}:vm-{vmid}-disk-0"
    elif storage_ref:
        # Caller has uploaded a qcow2 to e.g. local:iso/foo.qcow2; let qm
        # import-from copy it into the root pool during set.
        disk_volume = f"{root_pool}:0,import-from={storage_ref}"
    else:
        if not dry_run and created:
            _destroy_vm_best_effort(vmid, node_ip, user, ssh_opts)
        raise ProvisionError("No image source available to attach to VM disk")

    set_cmd = (
        f"qm set {vmid} "
        f"--scsi0 {shlex.quote(disk_volume)},iothread=1 "
        f"--ide2 {shlex.quote(root_pool)}:cloudinit "
        f"--boot order=scsi0"
    )
    set_result = _ssh_run(node_ip, user, ssh_opts, set_cmd, dry_run=dry_run)
    if set_result.returncode != 0:
        if not dry_run and created:
            _destroy_vm_best_effort(vmid, node_ip, user, ssh_opts)
        raise ProvisionError(
            f"qm set for VM {vmid} failed: "
            f"{(set_result.stderr or set_result.stdout or '').strip() or 'unknown error'}"
        )

    resize_cmd = f"qm resize {vmid} scsi0 {disk_size_gib}G"
    resize_result = _ssh_run(node_ip, user, ssh_opts, resize_cmd, dry_run=dry_run)
    if resize_result.returncode != 0:
        if not dry_run and created:
            _destroy_vm_best_effort(vmid, node_ip, user, ssh_opts)
        raise ProvisionError(
            f"qm resize for VM {vmid} failed: "
            f"{(resize_result.stderr or resize_result.stdout or '').strip() or 'the requested disk may be smaller than the image'}"
        )

    start_result = _ssh_run(
        node_ip, user, ssh_opts, f"qm start {vmid}", dry_run=dry_run
    )
    if start_result.returncode != 0:
        if not dry_run and created:
            _destroy_vm_best_effort(vmid, node_ip, user, ssh_opts)
        raise ProvisionError(
            f"qm start {vmid} failed: "
            f"{(start_result.stderr or start_result.stdout or '').strip() or 'unknown error'}"
        )

    print(f"  ✓ VM {vmid} created and started ({hostname}, {target_ip})")
    return True


def _wait_for_guest_agent(
    vmid: int,
    node_ip: str,
    user: str,
    ssh_opts: StrList,
    *,
    timeout: int = 180,
    poll_interval: int = 5,
    dry_run: bool = False,
) -> None:
    """Wait briefly for qemu-guest-agent to become reachable."""
    if dry_run:
        print(f"  [DRY-RUN] Would wait for qemu-guest-agent in VM {vmid}")
        return

    print("  Waiting for qemu-guest-agent...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = _ssh_run(
            node_ip,
            user,
            ssh_opts,
            f"qm agent {vmid} ping",
            dry_run=False,
        )
        if result.returncode == 0:
            print("  ✓ qemu-guest-agent is responding")
            return
        time.sleep(poll_interval)

    print("  ⚠ qemu-guest-agent did not come up before SSH handoff; continuing")


def provision_vm(config: SetupConfig, *, image: Optional[str] = None) -> None:
    """Orchestrate Proxmox VM provisioning.

    Args:
        config: SetupConfig with hosted_node, container_memory, container_storage, etc.
        image: Optional override; either an http(s) URL or a Proxmox storage
            reference like ``local:iso/foo.qcow2``.

    Raises:
        VMAlreadyExists: if a VM with the target IP already exists on the node.
        ProvisionError: on any provisioning failure.
    """
    node_ip = cast(str, config.hosted_node)
    memory_str = cast(str, config.container_memory)
    storage_specs = cast(NestedStrList, config.container_storage)
    user: str = config.hosted_user
    static_ipv4 = ipaddress.ip_interface(config.static_ipv4) if config.static_ipv4 else None
    if static_ipv4 is not None and not isinstance(static_ipv4, ipaddress.IPv4Interface):
        raise ProvisionError("VM provisioning requires an IPv4 setup target")
    target_ip = str(static_ipv4.ip) if static_ipv4 else config.host
    ssh_opts = _ssh_opts(config.hosted_key)
    dry_run = config.dry_run

    root_spec: Optional[StrList] = None
    for spec in storage_specs or []:
        if spec and spec[0] == "root":
            root_spec = list(spec)
            break
    if not root_spec or len(root_spec) < 3:
        raise ProvisionError("Missing root storage specification (--storage root POOL AMOUNT)")
    root_pool_arg, disk_amount = root_spec[1], root_spec[2]

    memory_mb = _parse_memory_mb(memory_str)
    balloon_min_mb = (
        _parse_memory_mb(config.vm_balloon_min)
        if config.vm_balloon_min
        else memory_mb
    )
    disk_size_gib = _parse_disk_size_gib(disk_amount)

    hostname = config.system_hostname or _build_guest_hostname(
        target_ip,
        config.friendly_name,
        default_prefix="vm",
    )

    resolved, catalog_entry = _resolve_image(config, image)

    pub_path = _resolve_public_key_path(config.ssh_key) if not dry_run else None
    pubkey_contents: Optional[str] = None
    if not dry_run:
        if not pub_path:
            raise ProvisionError(
                "VM provisioning requires a readable SSH private key with a matching .pub file"
            )
        try:
            with open(pub_path, "r", encoding="utf-8") as fh:
                pubkey_contents = fh.read().strip()
        except OSError as exc:
            raise ProvisionError(f"Failed to read public key {pub_path}: {exc}")
        print(f"  Using public key for VM access: {pub_path}")

    if dry_run:
        print("[DRY RUN] Would provision Proxmox VM:")
        print(f"  Proxmox node: {node_ip}")
        print(f"  Target IP: {target_ip}")
        if config.static_ipv6:
            print(f"  Static IPv6: {config.static_ipv6}")
        if config.network_gateway4:
            print(f"  IPv4 gateway: {config.network_gateway4}")
        else:
            print("  IPv4 gateway: auto-detect from selected Proxmox bridge")
        if config.network_gateway6:
            print(f"  IPv6 gateway: {config.network_gateway6}")
        if config.network_dns:
            print(f"  DNS servers: {', '.join(config.network_dns)}")
        else:
            print("  DNS servers: auto-detect from Proxmox node")
        print(f"  Hostname: {hostname}")
        print(f"  Memory: {memory_mb} MiB")
        if balloon_min_mb < memory_mb:
            print(f"  Balloon minimum: {balloon_min_mb} MiB (dynamic)")
        else:
            print(f"  Balloon minimum: {balloon_min_mb} MiB (fixed allocation)")
        print(f"  Cores: {config.container_cores}")
        print(
            "  Console: "
            + ("VirtIO-GPU + serial" if _needs_graphical_console(config) else "serial")
        )
        print(f"  Root storage: {root_pool_arg} ({disk_size_gib}G)")
        if catalog_entry:
            print(f"  Image (catalog): {catalog_entry['codename']} {catalog_entry['snapshot']} → {catalog_entry['filename']}")
        elif resolved.storage_ref:
            print(f"  Image (storage ref): {resolved.storage_ref}")
        else:
            print(f"  Image (URL): {resolved.url}")
        return

    print(f"  Hostname: {hostname}")

    bridge = auto_detect_bridge(
        node_ip,
        user,
        config.hosted_key,
        preferred_bridge=getattr(config, "hosted_bridge", None),
    )
    if static_ipv4 is None:
        raise ProvisionError("VM provisioning requires an IPv4 setup target")
    gateway = config.network_gateway4 or _get_guest_gateway(
        node_ip,
        user,
        ssh_opts,
        bridge,
        static_ipv4,
    )
    nameservers = list(config.network_dns or _get_host_nameservers(
        node_ip,
        user,
        ssh_opts,
        bridge=bridge,
        fallback_gateway=gateway,
    ))
    config.hosted_bridge = bridge
    config.network_gateway4 = gateway
    config.network_dns = nameservers
    cidr_prefix = (
        str(static_ipv4.network.prefixlen)
        if static_ipv4
        else _get_bridge_prefix_length(node_ip, user, ssh_opts, bridge)
    )

    if check_vm_exists(node_ip, target_ip, user, ssh_opts):
        raise VMAlreadyExists(
            f"VM with IP {target_ip} already exists on {node_ip}"
        )

    root_pool = _resolve_storage_pool(
        root_pool_arg, node_ip, user, ssh_opts, "images"
    )
    snippet_pool = _resolve_storage_pool(
        "auto", node_ip, user, ssh_opts, "snippets"
    )

    if resolved.url:
        image_pool = _resolve_storage_pool(
            "auto", node_ip, user, ssh_opts, "iso"
        )
        image_remote_path = _download_image_to_host(
            resolved, image_pool, node_ip, user, ssh_opts, dry_run=dry_run
        )
        storage_ref: Optional[str] = None
    else:
        image_remote_path = None
        storage_ref = resolved.storage_ref
        if storage_ref:
            if not is_local_image_ref(storage_ref) or ":iso/" not in storage_ref:
                raise ProvisionError(
                    f"Invalid --image storage ref: {storage_ref}; expected STORAGE:iso/FILE"
                )

    user_data = _render_user_data(
        username=config.username, pubkey_contents=pubkey_contents,
    )
    user_data_path = _upload_user_data(
        user_data, hostname, snippet_pool, node_ip, user, ssh_opts, dry_run=dry_run
    )
    user_data_ref = f"{snippet_pool}:snippets/infra_tools-{hostname}.yaml"
    vm_started = False
    provision_complete = False

    try:
        vmid = _get_next_vmid(node_ip, user, ssh_opts)
        create_kwargs = {
            "vmid": vmid,
            "target_ip": target_ip,
            "image_remote_path": image_remote_path,
            "storage_ref": storage_ref,
            "memory_mb": memory_mb,
            "balloon_min_mb": balloon_min_mb,
            "cores": config.container_cores,
            "root_pool": root_pool,
            "disk_size_gib": disk_size_gib,
            "cidr_prefix": cidr_prefix,
            "bridge": bridge,
            "gateway": gateway,
            "nameservers": nameservers,
            "hostname": hostname,
            "user_data_path": user_data_path,
            "user_data_ref": user_data_ref,
            "graphical_console": _needs_graphical_console(config),
            "node_ip": node_ip,
            "user": user,
            "ssh_opts": ssh_opts,
            "dry_run": dry_run,
            "ipv6_cidr": config.static_ipv6,
            "gateway6": config.network_gateway6,
        }
        try:
            _create_vm(**create_kwargs)
        except ProvisionError as exc:
            if "already exists" not in str(exc).lower():
                raise
            print(f"  ⚠ VMID {vmid} was allocated concurrently; retrying with a new VMID")
            vmid = _get_next_vmid(node_ip, user, ssh_opts)
            create_kwargs["vmid"] = vmid
            _create_vm(**create_kwargs)
        vm_started = True
        _wait_for_guest_agent(
            vmid,
            node_ip,
            user,
            ssh_opts,
            dry_run=dry_run,
        )
        # Cloud-init takes longer than LXC startup; bump the timeout.
        _wait_for_guest_ssh(
            target_ip, node_ip, user, ssh_opts, timeout=300, dry_run=dry_run
        )
        provision_complete = True
    except Exception:
        if vm_started and not dry_run:
            _destroy_vm_best_effort(vmid, node_ip, user, ssh_opts)
        raise
    finally:
        # Detach custom cloud-init before deleting its snippet. Leaving a
        # cicustom reference to a removed file breaks later cloud-init updates,
        # migration, and some clone workflows.
        if user_data_path and not dry_run:
            if provision_complete:
                detach_result = _ssh_run(
                    node_ip,
                    user,
                    ssh_opts,
                    f"qm set {vmid} --delete cicustom",
                    dry_run=False,
                )
                if detach_result.returncode != 0:
                    print(
                        "  ⚠ Could not detach the cloud-init snippet reference; "
                        f"preserving {user_data_path}"
                    )
                else:
                    _ssh_run(
                        node_ip, user, ssh_opts,
                        f"rm -f {shlex.quote(user_data_path)}",
                        dry_run=False,
                    )
            else:
                # Failed provisioning destroys the partial VM, so the snippet
                # is no longer referenced.
                _ssh_run(
                    node_ip, user, ssh_opts,
                    f"rm -f {shlex.quote(user_data_path)}",
                    dry_run=False,
                )
            # Tiny grace period so qemu-guest-agent / cloud-init finish flushing
            # before subsequent setup steps log in.
            time.sleep(2)
