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
4. ``qm create`` with serial console + virtio-scsi.
5. ``qm importdisk`` (or ``--import-from``) the qcow2 into the root storage,
   attach as ``scsi0``, set boot order, attach a cloud-init drive.
6. Cloud-init: user/SSH key/IP from infra_tools, then resize to the requested
   size and ``qm start``.
7. Wait for SSH on the target IP.
"""

from __future__ import annotations

import shlex
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
from lib.proxmox_node import (
    ProvisionError,
    _build_container_hostname,
    _get_bridge_prefix_length,
    _get_host_gateway,
    _get_host_nameservers,
    _get_next_vmid,
    _resolve_public_key_path,
    _resolve_storage_pool,
    _ssh_opts,
    _ssh_run,
    _wait_for_container_ssh,
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
        return False
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
            continue
        if f"ip={target_ip}/" in (cfg.stdout or "") or f"ip={target_ip}," in (cfg.stdout or ""):
            print(f"  ✓ VM {vmid} already exists with IP {target_ip}")
            return True
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
    node_ip: str,
    user: str,
    ssh_opts: StrList,
    *,
    dry_run: bool,
) -> str:
    """Fetch ``image`` onto the Proxmox node; return the absolute remote path."""
    if not image.url or not image.filename:
        raise ProvisionError("Internal error: download requested without URL")
    remote_dir = "/var/lib/vz/template/iso"
    remote_path = f"{remote_dir}/{image.filename}"

    if dry_run:
        print(f"  [DRY-RUN] Would download {image.url} → {remote_path}")
        return remote_path

    _ssh_run(node_ip, user, ssh_opts, f"mkdir -p {shlex.quote(remote_dir)}")
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
    lines = [
        "#cloud-config",
        f"hostname: __HOSTNAME__",
        "manage_etc_hosts: true",
        "users:",
        "  - name: root",
        "    lock_passwd: false",
    ]
    if pubkey_contents:
        lines.append("    ssh_authorized_keys:")
        lines.append(f"      - {pubkey_contents.strip()}")
    if username and username != "root":
        lines.extend([
            f"  - name: {username}",
            "    groups: sudo",
            "    sudo: 'ALL=(ALL) NOPASSWD:ALL'",
            "    shell: /bin/bash",
            "    lock_passwd: false",
        ])
        if pubkey_contents:
            lines.append("    ssh_authorized_keys:")
            lines.append(f"      - {pubkey_contents.strip()}")
    lines.append("ssh_pwauth: false")
    lines.append("")
    return "\n".join(lines)


def _upload_user_data(
    user_data: str,
    hostname: str,
    node_ip: str,
    user: str,
    ssh_opts: StrList,
    *,
    dry_run: bool,
) -> Optional[str]:
    """Write the rendered user-data to a snippet on the node and return its path."""
    if dry_run:
        return "/var/lib/vz/snippets/infra_tools-userdata.dryrun.yaml"

    rendered = user_data.replace("__HOSTNAME__", hostname)
    snippets_dir = "/var/lib/vz/snippets"
    _ssh_run(node_ip, user, ssh_opts, f"mkdir -p {shlex.quote(snippets_dir)}")
    remote_path = f"{snippets_dir}/infra_tools-{hostname}.yaml"
    write_cmd = ["ssh"] + ssh_opts + [
        f"{user}@{node_ip}",
        f"cat > {shlex.quote(remote_path)}",
    ]
    import subprocess
    proc = subprocess.run(
        write_cmd, input=rendered, text=True, capture_output=True, timeout=60
    )
    if proc.returncode != 0:
        raise ProvisionError(
            f"Failed to upload cloud-init user-data to {node_ip}: "
            f"{proc.stderr.strip() or 'unknown error'}"
        )
    return remote_path


def _create_vm(
    *,
    vmid: int,
    target_ip: str,
    image_remote_path: Optional[str],
    storage_ref: Optional[str],
    memory_mb: int,
    cores: int,
    root_pool: str,
    disk_size_gib: int,
    cidr_prefix: str,
    bridge: str,
    gateway: str,
    nameservers: StrList,
    hostname: str,
    user_data_path: Optional[str],
    node_ip: str,
    user: str,
    ssh_opts: StrList,
    dry_run: bool = False,
) -> None:
    """Build, populate, and start the VM on ``node_ip``."""
    create_parts = [
        f"qm create {vmid}",
        f"--name {shlex.quote(hostname)}",
        f"--memory {memory_mb}",
        f"--cores {cores}",
        "--cpu host",
        "--ostype l26",
        "--scsihw virtio-scsi-single",
        "--serial0 socket",
        "--vga serial0",
        "--agent enabled=1",
        (
            f"--net0 virtio,bridge={shlex.quote(bridge)}"
        ),
        f"--ipconfig0 ip={shlex.quote(target_ip)}/{shlex.quote(cidr_prefix)},gw={shlex.quote(gateway)}",
        f"--nameserver {shlex.quote(' '.join(nameservers))}",
        "--onboot 1",
    ]
    if user_data_path:
        # Snippets always live on `local` storage on a single-node default; the
        # path-based form keeps us out of guessing the snippet storage name.
        snippet_volume = f"local:snippets/{user_data_path.rsplit('/', 1)[-1]}"
        create_parts.append(f"--cicustom user={shlex.quote(snippet_volume)}")

    create_cmd = " ".join(create_parts)
    result = _ssh_run(node_ip, user, ssh_opts, create_cmd, dry_run=dry_run)
    if result.returncode != 0:
        raise ProvisionError(
            f"qm create {vmid} failed: "
            f"{(result.stderr or result.stdout or '').strip() or 'unknown error'}"
        )

    # Attach the disk: prefer importing the qcow2; otherwise reference the
    # pre-uploaded storage volume directly.
    if image_remote_path:
        import_cmd = (
            f"qm importdisk {vmid} {shlex.quote(image_remote_path)} "
            f"{shlex.quote(root_pool)} --format qcow2"
        )
        imported = _ssh_run(node_ip, user, ssh_opts, import_cmd, dry_run=dry_run)
        if imported.returncode != 0:
            raise ProvisionError(
                f"qm importdisk for VM {vmid} failed: "
                f"{(imported.stderr or imported.stdout or '').strip() or 'unknown error'}"
            )
        # Proxmox names the imported volume {pool}:vm-{vmid}-disk-0.
        disk_volume = f"{root_pool}:vm-{vmid}-disk-0"
    elif storage_ref:
        # Caller has uploaded a qcow2 to e.g. local:iso/foo.qcow2; let qm
        # import-from copy it into the root pool during set.
        disk_volume = f"{root_pool}:0,import-from={storage_ref}"
    else:
        raise ProvisionError("No image source available to attach to VM disk")

    set_cmd = (
        f"qm set {vmid} "
        f"--scsi0 {shlex.quote(disk_volume)} "
        f"--ide2 {shlex.quote(root_pool)}:cloudinit "
        f"--boot order=scsi0"
    )
    set_result = _ssh_run(node_ip, user, ssh_opts, set_cmd, dry_run=dry_run)
    if set_result.returncode != 0:
        raise ProvisionError(
            f"qm set for VM {vmid} failed: "
            f"{(set_result.stderr or set_result.stdout or '').strip() or 'unknown error'}"
        )

    resize_cmd = f"qm resize {vmid} scsi0 {disk_size_gib}G"
    resize_result = _ssh_run(node_ip, user, ssh_opts, resize_cmd, dry_run=dry_run)
    if resize_result.returncode != 0 and "shrink" not in (resize_result.stderr or "").lower():
        # `qm resize` errors out if the new size is smaller than the imported
        # image; surface as a friendlier message.
        raise ProvisionError(
            f"qm resize for VM {vmid} failed: "
            f"{(resize_result.stderr or resize_result.stdout or '').strip() or 'unknown error'}"
        )

    start_result = _ssh_run(
        node_ip, user, ssh_opts, f"qm start {vmid}", dry_run=dry_run
    )
    if start_result.returncode != 0:
        raise ProvisionError(
            f"qm start {vmid} failed: "
            f"{(start_result.stderr or start_result.stdout or '').strip() or 'unknown error'}"
        )

    print(f"  ✓ VM {vmid} created and started ({hostname}, {target_ip})")


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
    target_ip: str = config.host
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
    disk_size_gib = _parse_disk_size_gib(disk_amount)

    hostname = _build_container_hostname(target_ip, config.friendly_name)
    if hostname.startswith("lxc-"):
        hostname = "vm-" + hostname[len("lxc-"):]

    resolved, catalog_entry = _resolve_image(config, image)

    if dry_run:
        print("[DRY RUN] Would provision Proxmox VM:")
        print(f"  Proxmox node: {node_ip}")
        print(f"  Target IP: {target_ip}")
        print(f"  Hostname: {hostname}")
        print(f"  Memory: {memory_mb} MiB")
        print(f"  Cores: {config.container_cores}")
        print(f"  Root storage: {root_pool_arg} ({disk_size_gib}G)")
        if catalog_entry:
            print(f"  Image (catalog): {catalog_entry['codename']} {catalog_entry['snapshot']} → {catalog_entry['filename']}")
        elif resolved.storage_ref:
            print(f"  Image (storage ref): {resolved.storage_ref}")
        else:
            print(f"  Image (URL): {resolved.url}")
        return

    if check_vm_exists(node_ip, target_ip, user, ssh_opts):
        raise VMAlreadyExists(
            f"VM with IP {target_ip} already exists on {node_ip}"
        )

    print(f"  Hostname: {hostname}")

    bridge = auto_detect_bridge(node_ip, user, config.hosted_key)
    gateway = _get_host_gateway(node_ip, user, ssh_opts)
    nameservers = _get_host_nameservers(node_ip, user, ssh_opts)
    cidr_prefix = _get_bridge_prefix_length(node_ip, user, ssh_opts, bridge)

    root_pool = _resolve_storage_pool(
        root_pool_arg, node_ip, user, ssh_opts, "images"
    )

    if resolved.url:
        image_remote_path = _download_image_to_host(
            resolved, node_ip, user, ssh_opts, dry_run=dry_run
        )
        storage_ref: Optional[str] = None
    else:
        image_remote_path = None
        storage_ref = resolved.storage_ref
        if storage_ref and not is_local_image_ref(storage_ref):
            raise ProvisionError(f"Invalid --image storage ref: {storage_ref}")

    pub_path = _resolve_public_key_path(config.ssh_key)
    pubkey_contents: Optional[str] = None
    if pub_path:
        try:
            with open(pub_path, "r", encoding="utf-8") as fh:
                pubkey_contents = fh.read().strip()
        except OSError as exc:
            raise ProvisionError(f"Failed to read public key {pub_path}: {exc}")
        print(f"  Using public key for VM access: {pub_path}")
    else:
        print(
            "  ⚠ No SSH public key found alongside --key; cloud-init will not "
            "install root credentials and remote setup will be unable to connect."
        )

    user_data = _render_user_data(
        username=config.username, pubkey_contents=pubkey_contents,
    )
    user_data_path = _upload_user_data(
        user_data, hostname, node_ip, user, ssh_opts, dry_run=dry_run
    )

    vmid = _get_next_vmid(node_ip, user, ssh_opts)

    try:
        _create_vm(
            vmid=vmid,
            target_ip=target_ip,
            image_remote_path=image_remote_path,
            storage_ref=storage_ref,
            memory_mb=memory_mb,
            cores=config.container_cores,
            root_pool=root_pool,
            disk_size_gib=disk_size_gib,
            cidr_prefix=cidr_prefix,
            bridge=bridge,
            gateway=gateway,
            nameservers=nameservers,
            hostname=hostname,
            user_data_path=user_data_path,
            node_ip=node_ip,
            user=user,
            ssh_opts=ssh_opts,
            dry_run=dry_run,
        )
        # Cloud-init takes longer than LXC startup; bump the timeout.
        _wait_for_container_ssh(
            target_ip, node_ip, user, ssh_opts, timeout=300, dry_run=dry_run
        )
    finally:
        # Best-effort cleanup of the snippet now that cloud-init has consumed it.
        if user_data_path and not dry_run:
            _ssh_run(
                node_ip, user, ssh_opts,
                f"rm -f {shlex.quote(user_data_path)}",
                dry_run=False,
            )
            # Tiny grace period so qemu-guest-agent / cloud-init finish flushing
            # before subsequent setup steps log in.
            time.sleep(2)
