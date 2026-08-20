"""Fail-closed guest filesystem setup for newly provisioned VM data disks."""

from __future__ import annotations

import json
import os
import re
import shlex
from typing import Any

from lib.atomic_io import write_json_atomic, write_text_atomic
from lib.config import SetupConfig
from lib.remote_utils import is_dry_run, run
from lib.vm_storage import VMStorageMount, data_disks, storage_mounts, storage_size_kib


STORAGE_STATE_FILE = "/opt/infra_tools/state/vm-storage.json"
STORAGE_MARKER = ".infra-tools-storage.json"
STORAGE_SCHEMA_VERSION = 1


def _run_capture(command: str, *, check: bool = True):
    return run(command, check=check, capture_output=True)


def _lsblk() -> list[dict[str, Any]]:
    result = _run_capture(
        "lsblk --json --bytes --paths "
        "--output NAME,PATH,TYPE,SIZE,SERIAL,FSTYPE,PTTYPE,MOUNTPOINTS,UUID"
    )
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("lsblk returned invalid JSON while inspecting VM storage") from exc
    devices = payload.get("blockdevices")
    if not isinstance(devices, list):
        raise RuntimeError("lsblk did not return a block-device list")
    return [device for device in devices if isinstance(device, dict)]


def _device_path(device: dict[str, Any]) -> str:
    value = device.get("path") or device.get("name")
    if not isinstance(value, str) or not value.startswith("/dev/"):
        raise RuntimeError("lsblk returned an unsafe block-device path")
    return value


def _has_mountpoint(device: dict[str, Any]) -> bool:
    value = device.get("mountpoints")
    if isinstance(value, list):
        return any(isinstance(item, str) and item for item in value)
    return isinstance(value, str) and bool(value)


def _find_declared_disk(serial: str, expected_size: str) -> dict[str, Any]:
    matches = [
        device
        for device in _lsblk()
        if device.get("type") == "disk" and device.get("serial") == serial
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one VM data disk with serial {serial!r}; found {len(matches)}"
        )
    disk = matches[0]
    try:
        actual_bytes = int(disk.get("size"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"VM data disk {serial!r} did not report a valid size") from exc
    expected_bytes = storage_size_kib(expected_size) * 1024
    if actual_bytes < expected_bytes:
        raise RuntimeError(
            f"VM data disk {serial!r} is smaller than declared: "
            f"{actual_bytes} bytes < {expected_bytes} bytes"
        )
    return disk


def _wipefs_signatures(device_path: str) -> list[str]:
    result = _run_capture(
        f"wipefs --no-act --noheadings --output TYPE {shlex.quote(device_path)}",
        check=False,
    )
    if result.returncode not in {0, 1}:
        detail = (result.stderr or result.stdout or "").strip() or "wipefs failed"
        raise RuntimeError(f"Could not inspect {device_path} for signatures: {detail}")
    return [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]


def _partition_for_mount(
    disk: dict[str, Any],
    serial: str,
    expected_size: str,
) -> str:
    disk_path = _device_path(disk)
    children = disk.get("children") or []
    if not isinstance(children, list):
        raise RuntimeError(f"VM data disk {serial!r} returned invalid partition data")

    if not children:
        if any((disk.get("fstype"), disk.get("pttype"), _has_mountpoint(disk))):
            raise RuntimeError(
                f"Refusing to partition nonblank VM data disk {serial!r} ({disk_path})"
            )
        signatures = _wipefs_signatures(disk_path)
        if signatures:
            raise RuntimeError(
                f"Refusing to partition VM data disk {serial!r}; signatures found: "
                + ", ".join(signatures)
            )
        _run_capture(
            f"parted --script {shlex.quote(disk_path)} "
            "mklabel gpt mkpart primary 1MiB 100%"
        )
        _run_capture("udevadm settle")
        disk = _find_declared_disk(serial, expected_size)
        children = disk.get("children") or []

    if disk.get("pttype") != "gpt" or len(children) != 1:
        raise RuntimeError(
            f"VM data disk {serial!r} must contain exactly one GPT partition"
        )
    partition = children[0]
    if not isinstance(partition, dict) or partition.get("type") != "part":
        raise RuntimeError(f"VM data disk {serial!r} has an unexpected child device")
    return _device_path(partition)


def _filesystem_uuid(device_path: str) -> str:
    result = _run_capture(
        f"blkid --match-tag UUID --output value {shlex.quote(device_path)}",
        check=False,
    )
    uuid = (result.stdout or "").strip()
    if result.returncode != 0 or not re.fullmatch(r"[A-Fa-f0-9-]{8,64}", uuid):
        raise RuntimeError(f"Could not read a filesystem UUID from {device_path}")
    return uuid


def _ensure_filesystem(device_path: str, filesystem: str) -> str:
    devices = _lsblk()
    partition: dict[str, Any] | None = None
    for disk in devices:
        for child in disk.get("children") or []:
            if isinstance(child, dict) and _device_path(child) == device_path:
                partition = child
                break
        if partition is not None:
            break
    if partition is None:
        raise RuntimeError(f"Partition disappeared before formatting: {device_path}")

    current_filesystem = partition.get("fstype")
    if current_filesystem:
        if current_filesystem != filesystem:
            raise RuntimeError(
                f"{device_path} contains {current_filesystem}, expected {filesystem}; "
                "refusing to reformat"
            )
        return _filesystem_uuid(device_path)

    signatures = _wipefs_signatures(device_path)
    if signatures:
        raise RuntimeError(
            f"Refusing to format {device_path}; signatures found: "
            + ", ".join(signatures)
        )
    if _has_mountpoint(partition):
        raise RuntimeError(f"Refusing to format mounted partition {device_path}")

    if filesystem == "ext4":
        _run_capture(f"mkfs.ext4 -F -m 0 {shlex.quote(device_path)}")
    elif filesystem == "xfs":
        _run_capture(f"mkfs.xfs -f {shlex.quote(device_path)}")
    else:
        raise RuntimeError(f"Unsupported VM data filesystem: {filesystem}")
    _run_capture("udevadm settle")
    return _filesystem_uuid(device_path)


def _reject_symlinked_mount_path(path: str) -> None:
    current = os.path.sep
    for component in os.path.abspath(path).split(os.path.sep):
        if not component:
            continue
        current = os.path.join(current, component)
        if os.path.lexists(current) and os.path.islink(current):
            raise RuntimeError(f"Refusing symlinked VM storage mount path: {current}")


def _mounted_info(path: str) -> tuple[str, str] | None:
    result = _run_capture(
        f"findmnt --json --target {shlex.quote(path)} --output SOURCE,FSTYPE,TARGET",
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("findmnt returned invalid JSON") from exc
    filesystems = payload.get("filesystems")
    if not isinstance(filesystems, list) or not filesystems:
        return None
    record = filesystems[0]
    if not isinstance(record, dict) or record.get("target") != path:
        return None
    source = record.get("source")
    filesystem = record.get("fstype")
    if not isinstance(source, str) or not isinstance(filesystem, str):
        raise RuntimeError(f"findmnt returned incomplete mount data for {path}")
    return source, filesystem


def _systemd_mount_unit(path: str) -> str:
    result = _run_capture(
        f"systemd-escape --path --suffix=mount {shlex.quote(path)}"
    )
    unit = (result.stdout or "").strip()
    if not unit.endswith(".mount") or "/" in unit or any(
        ord(character) < 32 for character in unit
    ):
        raise RuntimeError(f"systemd returned an invalid mount unit for {path}")
    return unit


def _verify_active_mount(
    mount: VMStorageMount,
    expected_uuid: str,
) -> tuple[str, str]:
    mounted = _mounted_info(mount.path)
    if mounted is None:
        raise RuntimeError(f"Required VM data mount is not active: {mount.path}")
    source, filesystem = mounted
    if filesystem != mount.filesystem:
        raise RuntimeError(
            f"{mount.path} is mounted as {filesystem}, expected {mount.filesystem}"
        )
    actual_uuid = _filesystem_uuid(source)
    if actual_uuid != expected_uuid:
        raise RuntimeError(
            f"{mount.path} is backed by UUID {actual_uuid}, expected {expected_uuid}"
        )
    return source, filesystem


def _prepare_mount(
    mount: VMStorageMount,
    disk_size: str,
    serial: str,
    bus_slot: str,
) -> dict[str, Any]:
    _reject_symlinked_mount_path(mount.path)
    mounted = _mounted_info(mount.path)
    if mounted is None and os.path.lexists(mount.path):
        if not os.path.isdir(mount.path):
            raise RuntimeError(f"VM storage mount path is not a directory: {mount.path}")
        if os.listdir(mount.path):
            raise RuntimeError(
                f"VM storage mount path must be empty before first use: {mount.path}"
            )

    disk = _find_declared_disk(serial, disk_size)
    if mounted is not None and not (disk.get("children") or []):
        raise RuntimeError(
            f"Refusing to prepare blank VM data disk {serial!r} while "
            f"{mount.path} is already mounted"
        )
    partition_path = _partition_for_mount(disk, serial, disk_size)
    filesystem_uuid = _ensure_filesystem(partition_path, mount.filesystem)

    if mounted is None:
        if not os.path.lexists(mount.path):
            os.makedirs(mount.path, mode=0o755)
    else:
        _verify_active_mount(mount, filesystem_uuid)

    unit = _systemd_mount_unit(mount.path)
    unit_path = os.path.join("/etc/systemd/system", unit)
    unit_text = (
        "[Unit]\n"
        f"Description=infra-tools VM data mount {mount.name}\n"
        "Before=local-fs.target\n\n"
        "[Mount]\n"
        f"What=/dev/disk/by-uuid/{filesystem_uuid}\n"
        f"Where={mount.path}\n"
        f"Type={mount.filesystem}\n"
        "Options=defaults\n\n"
        "[Install]\n"
        "WantedBy=local-fs.target\n"
    )
    write_text_atomic(unit_path, unit_text, mode=0o644)
    _run_capture("systemctl daemon-reload")
    _run_capture(f"systemctl enable --now {shlex.quote(unit)}")
    source, _filesystem = _verify_active_mount(mount, filesystem_uuid)

    marker = {
        "schema_version": STORAGE_SCHEMA_VERSION,
        "name": mount.name,
        "serial": serial,
        "bus_slot": bus_slot,
        "uuid": filesystem_uuid,
        "filesystem": mount.filesystem,
        "mount_path": mount.path,
    }
    write_json_atomic(
        os.path.join(mount.path, STORAGE_MARKER),
        marker,
        mode=0o644,
        sort_keys=True,
    )
    return {
        **marker,
        "partition": partition_path,
        "active_source": source,
        "mount_unit": unit,
        "policy": mount.policy,
    }


def setup_vm_storage(config: SetupConfig) -> None:
    """Prepare every declared blank VM data disk before application setup."""

    mounts = storage_mounts(config)
    if not mounts:
        return
    if is_dry_run():
        for mount in mounts:
            print(
                f"  [DRY-RUN] Would prepare VM data disk {mount.name} at "
                f"{mount.path} ({mount.filesystem})"
            )
        return

    disk_by_name = {disk.name: disk for disk in data_disks(config)}
    disk_slots = {
        disk.name: f"scsi{index}"
        for index, disk in enumerate(data_disks(config), 1)
    }
    dependencies = _run_capture(
        "apt-get install -y -qq parted e2fsprogs xfsprogs util-linux"
    )
    if dependencies.returncode != 0:
        raise RuntimeError("VM storage setup dependencies could not be installed")

    records: list[dict[str, Any]] = []
    for mount in mounts:
        disk = disk_by_name.get(mount.name)
        if disk is None:
            raise RuntimeError(f"No VM data disk declaration exists for {mount.name}")
        record = _prepare_mount(
            mount,
            disk.size,
            disk.serial,
            disk_slots[mount.name],
        )
        records.append({**record, "pool": disk.pool, "requested_size": disk.size})
        print(f"  Mounted VM data disk {mount.name} at {mount.path}")

    write_json_atomic(
        STORAGE_STATE_FILE,
        {"schema_version": STORAGE_SCHEMA_VERSION, "mounts": records},
        mode=0o600,
        sort_keys=True,
    )


def assert_declared_storage_mount(config: SetupConfig, path: str) -> None:
    """Verify the declared mount containing ``path`` before an application write."""

    matching = [
        mount
        for mount in storage_mounts(config)
        if path == mount.path or path.startswith(mount.path + os.sep)
    ]
    if not matching:
        return
    mount = max(matching, key=lambda item: len(item.path))
    marker_path = os.path.join(mount.path, STORAGE_MARKER)
    try:
        with open(marker_path, encoding="utf-8") as file_obj:
            marker = json.load(file_obj)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Required VM storage marker is missing or invalid: {marker_path}"
        ) from exc
    if not isinstance(marker, dict) or marker.get("name") != mount.name:
        raise RuntimeError(f"VM storage marker does not match {mount.name}: {marker_path}")
    expected_uuid = marker.get("uuid")
    if not isinstance(expected_uuid, str) or not expected_uuid:
        raise RuntimeError(f"VM storage marker has no UUID: {marker_path}")
    _verify_active_mount(mount, expected_uuid)
