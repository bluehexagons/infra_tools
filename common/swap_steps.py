"""Rerun-safe, ownership-aware Linux swap configuration."""

from __future__ import annotations

import json
import os
import re
import shlex
import stat
from pathlib import Path
from typing import Any

from common.storage_steps import (
    _device_path,
    _find_declared_disk,
    _find_device_by_path,
    _has_mountpoint,
    _wipefs_signatures,
)
from lib.atomic_io import remove_file_durable, write_json_atomic, write_text_atomic
from lib.config import SetupConfig
from lib.machine_state import can_manage_swap
from lib.remote_utils import is_dry_run, run
from lib.swap_config import (
    SwapDevice,
    SwapFile,
    SwapZram,
    has_explicit_swap_areas,
    swap_devices,
    swap_files,
    swap_zram,
)
from lib.vm_storage import data_disks


SWAP_STATE_FILE = "/opt/infra_tools/state/swap.json"
FSTAB_PATH = "/etc/fstab"
SYSCTL_PATH = "/etc/sysctl.d/90-infra-tools-swap.conf"
ZRAM_PATH = "/etc/systemd/zram-generator.conf.d/90-infra-tools.conf"
ZSWAP_SERVICE_PATH = "/etc/systemd/system/infra-tools-zswap.service"
RESUME_PATH = "/etc/initramfs-tools/conf.d/99-infra-tools-resume"
SWAP_SCHEMA_VERSION = 1
FSTAB_BEGIN = "# BEGIN infra-tools managed swap"
FSTAB_END = "# END infra-tools managed swap"


def _capture(command: str, *, check: bool = True):
    return run(command, check=check, capture_output=True)


def get_total_ram_mb() -> int:
    result = _capture("free --mebi --output=total | tail -n 1", check=False)
    try:
        return int(result.stdout.strip())
    except (ValueError, AttributeError):
        return 0


def get_free_disk_mb() -> int:
    result = _capture("df --output=avail -BM / | tail -n 1", check=False)
    match = re.search(r"([0-9]+)", result.stdout or "")
    return int(match.group(1)) if match else 0


def _load_state() -> dict[str, Any]:
    try:
        with open(SWAP_STATE_FILE, encoding="utf-8") as state_file:
            state = json.load(state_file)
    except FileNotFoundError:
        return {"schema": SWAP_SCHEMA_VERSION, "areas": []}
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Could not read the managed swap state") from exc
    if state.get("schema") != SWAP_SCHEMA_VERSION or not isinstance(
        state.get("areas"), list
    ):
        raise RuntimeError("Managed swap state has an unsupported schema")
    return state


def _active_swap() -> set[str]:
    result = _capture("swapon --show=NAME --noheadings --raw", check=False)
    if result.returncode not in {0, 1}:
        raise RuntimeError("Could not inspect active swap areas")
    return {line.strip() for line in (result.stdout or "").splitlines() if line.strip()}


def _replace_fstab(entries: list[str]) -> None:
    try:
        current = Path(FSTAB_PATH).read_text(encoding="utf-8")
    except FileNotFoundError:
        current = ""
    start = current.find(FSTAB_BEGIN)
    end = current.find(FSTAB_END)
    if (start == -1) != (end == -1) or (start != -1 and end < start):
        raise RuntimeError("/etc/fstab contains an incomplete infra-tools swap block")
    if start != -1:
        end += len(FSTAB_END)
        while end < len(current) and current[end] == "\n":
            end += 1
        current = current[:start].rstrip("\n") + current[end:]
    block = ""
    if entries:
        block = "\n".join((FSTAB_BEGIN, *entries, FSTAB_END)) + "\n"
    content = current.rstrip("\n")
    if content and block:
        content += "\n\n"
    elif content:
        content += "\n"
    content += block
    write_text_atomic(FSTAB_PATH, content, mode=0o644)


def _swap_uuid(source: str) -> str:
    result = _capture(
        f"blkid --match-tag UUID --output value {shlex.quote(source)}",
        check=False,
    )
    value = (result.stdout or "").strip()
    if result.returncode != 0 or not re.fullmatch(r"[A-Za-z0-9-]{8,64}", value):
        raise RuntimeError(f"Could not read the swap UUID from {source}")
    return value


def _swap_type(source: str) -> str | None:
    result = _capture(
        f"blkid --probe --match-tag TYPE --output value {shlex.quote(source)}",
        check=False,
    )
    value = (result.stdout or "").strip()
    return value if result.returncode == 0 and value else None


def _swapon(source: str, priority: int, discard: str = "off") -> None:
    options = ["swapon", "--priority", str(priority)]
    if discard != "off":
        options.append("--discard" if discard == "both" else f"--discard={discard}")
    options.append(source)
    run(shlex.join(options))


def _warn_swap_file_filesystem(path: str) -> None:
    target = path if os.path.exists(path) else os.path.dirname(path)
    result = _capture(
        f"findmnt --noheadings --output FSTYPE --target {shlex.quote(target)}",
        check=False,
    )
    filesystem = (result.stdout or "").strip().lower()
    if filesystem == "zfs":
        print(
            f"  ⚠ Swap file {path} is on ZFS; infra-tools has not qualified "
            "ZFS swap-file behavior. Prefer a dedicated block device."
        )
    elif filesystem == "btrfs":
        raise RuntimeError(
            f"Swap file {path} is on Btrfs, which requires filesystem-specific "
            "creation rules not managed by infra-tools"
        )


def _size_mib(value: str) -> int:
    units = {"K": 1 / 1024, "M": 1, "G": 1024, "T": 1024 * 1024}
    return int(int(value[:-1]) * units[value[-1].upper()])


def _swap_label(name: str) -> str:
    return f"it-{name}"[:16]


def _assert_safe_swap_parent(path: str) -> None:
    """Reject swap files below directories writable by non-root users."""

    candidate = Path(path)
    while not candidate.exists():
        candidate = candidate.parent
    info = candidate.stat()
    if info.st_uid != 0 or info.st_mode & 0o022:
        raise RuntimeError(
            f"Swap-file parent {candidate} must be root-owned and not writable "
            "by group or other users"
        )


def _ensure_swap_file(area: SwapFile, prior: dict[str, Any] | None) -> dict[str, Any]:
    path = area.path
    parent = os.path.dirname(path)
    if os.path.lexists(path) and os.path.islink(path):
        raise RuntimeError(f"Refusing to manage symlink swap file: {path}")
    probe = Path(parent)
    while probe != probe.parent:
        if probe.is_symlink():
            raise RuntimeError(f"Refusing swap path below symlink: {probe}")
        probe = probe.parent
    _assert_safe_swap_parent(parent)
    os.makedirs(parent, mode=0o755, exist_ok=True)
    _warn_swap_file_filesystem(path)
    size_mib = _size_mib(area.size)
    restart = bool(prior and prior.get("priority") != area.priority)
    if os.path.exists(path):
        file_info = os.stat(path, follow_symlinks=False)
        if (
            not stat.S_ISREG(file_info.st_mode)
            or file_info.st_nlink != 1
            or file_info.st_uid != 0
        ):
            raise RuntimeError(f"Managed swap path is not a single regular file: {path}")
        if not prior or prior.get("type") != "file" or prior.get("source") != path:
            raise RuntimeError(
                f"Refusing to adopt existing unmanaged swap file {path}; choose "
                "another path or remove it explicitly"
            )
        if _swap_type(path) != "swap":
            raise RuntimeError(
                f"Managed swap file {path} no longer has a swap signature; "
                "refusing to overwrite or remove it"
            )
        if os.path.getsize(path) != size_mib * 1024 * 1024:
            if path in _active_swap():
                run(f"swapoff {shlex.quote(path)}")
            run(f"fallocate --length {size_mib}M {shlex.quote(path)}")
            run(f"chmod 600 {shlex.quote(path)}")
            run(
                f"mkswap --force --label {shlex.quote(_swap_label(area.name))} "
                f"{shlex.quote(path)}"
            )
            restart = False
    else:
        run(f"fallocate --length {size_mib}M {shlex.quote(path)}")
        run(f"chmod 600 {shlex.quote(path)}")
        run(
            f"mkswap --label {shlex.quote(_swap_label(area.name))} "
            f"{shlex.quote(path)}"
        )
    if _swap_type(path) != "swap":
        raise RuntimeError(f"Managed swap file did not acquire a swap signature: {path}")
    active = _active_swap()
    if restart and path in active:
        run(f"swapoff {shlex.quote(path)}")
        active.remove(path)
    if path not in active:
        _swapon(path, area.priority)
    return {
        "name": area.name,
        "type": "file",
        "source": path,
        "priority": area.priority,
        "size": area.size,
    }


def _resolve_direct_device(source: str) -> str:
    if source.startswith("UUID="):
        result = _capture(f"findfs {shlex.quote(source)}", check=False)
        path = (result.stdout or "").strip()
        if result.returncode != 0 or not path.startswith("/dev/"):
            raise RuntimeError(f"Could not resolve swap device {source}")
        return path
    resolved = os.path.realpath(source)
    if not resolved.startswith("/dev/") or resolved == source:
        raise RuntimeError(f"Could not resolve stable swap device path {source}")
    return resolved


def _ensure_swap_device(
    config: SetupConfig,
    area: SwapDevice,
    prior: dict[str, Any] | None,
) -> dict[str, Any]:
    disks = {disk.name: disk for disk in data_disks(config)}
    provider_owned = area.source in disks
    if provider_owned:
        declared = disks[area.source]
        record = _find_declared_disk(declared.serial, declared.size)
        path = _device_path(record)
    else:
        path = _resolve_direct_device(area.source)
        record = _find_device_by_path(path)
        if record is None:
            raise RuntimeError(f"Swap device is not visible to lsblk: {path}")

    if path.startswith(("/dev/zvol/", "/dev/zd")):
        print(
            f"  ⚠ Swap device {path} appears to be ZFS-backed. Direct ZFS swap "
            "has not been qualified by infra-tools; monitor pool memory pressure."
        )
    if record.get("children") or _has_mountpoint(record):
        raise RuntimeError(f"Refusing to use partitioned or mounted swap device {path}")
    signatures = _wipefs_signatures(path)
    current_type = record.get("fstype") or _swap_type(path)
    if current_type and current_type != "swap":
        raise RuntimeError(f"Refusing to overwrite {current_type} on swap device {path}")
    non_swap_signatures = [signature for signature in signatures if signature != "swap"]
    if non_swap_signatures:
        raise RuntimeError(
            f"Refusing to overwrite signatures on swap device {path}: "
            + ", ".join(non_swap_signatures)
        )
    if current_type != "swap":
        if not provider_owned and area.name not in (config.swap_initialize or []):
            raise RuntimeError(
                f"Blank direct device {area.source} requires "
                f"--swap-initialize {area.name}"
            )
        run(
            f"mkswap --label {shlex.quote(_swap_label(area.name))} "
            f"{shlex.quote(path)}"
        )
        run("udevadm settle")
    uuid = _swap_uuid(path)
    active = _active_swap()
    prior_policy_changed = bool(
        prior
        and (
            prior.get("priority") != area.priority
            or prior.get("discard", "off") != area.discard
        )
    )
    if prior_policy_changed and (
        path in active or f"/dev/disk/by-uuid/{uuid}" in active
    ):
        run(f"swapoff {shlex.quote(path)}")
        active.discard(path)
        active.discard(f"/dev/disk/by-uuid/{uuid}")
    if path not in active and f"/dev/disk/by-uuid/{uuid}" not in active:
        _swapon(path, area.priority, area.discard)
    return {
        "name": area.name,
        "type": "device",
        "source": area.source,
        "path": path,
        "uuid": uuid,
        "priority": area.priority,
        "discard": area.discard,
        "provider_owned": provider_owned,
    }


def _zram_configuration(areas: list[SwapZram]) -> str:
    sections: list[str] = []
    for index, area in enumerate(areas):
        lines = [
            f"[zram{index}]",
            f"zram-size = {_size_mib(area.size)}",
            f"swap-priority = {area.priority}",
        ]
        if area.algorithm != "auto":
            lines.append(f"compression-algorithm = {area.algorithm}")
        sections.append("\n".join(lines))
    return "\n\n".join(sections) + ("\n" if sections else "")


def _reconcile_zram(
    areas: list[SwapZram], old_areas: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    records = [
        {
            "name": area.name,
            "type": "zram",
            "source": f"/dev/zram{index}",
            "priority": area.priority,
            "size": area.size,
            "algorithm": area.algorithm,
        }
        for index, area in enumerate(areas)
    ]
    if records == old_areas and (not records or os.path.exists(ZRAM_PATH)):
        return records
    if not areas and not old_areas:
        return []
    if areas:
        run("apt-get install -y systemd-zram-generator")
        write_text_atomic(ZRAM_PATH, _zram_configuration(areas), mode=0o644)
    else:
        remove_file_durable(ZRAM_PATH)
    for index in range(max(len(old_areas), len(areas))):
        run(f"systemctl stop systemd-zram-setup@zram{index}.service", check=False)
    run("systemctl daemon-reload")
    for index in range(len(areas)):
        run(f"systemctl start systemd-zram-setup@zram{index}.service")
    return records


def _configure_swappiness(value: int | None, *, remove: bool = False) -> None:
    if remove:
        if remove_file_durable(SYSCTL_PATH):
            run("sysctl --system")
        return
    if value is None:
        return
    content = f"vm.swappiness = {value}\n"
    try:
        current = Path(SYSCTL_PATH).read_text(encoding="utf-8")
    except FileNotFoundError:
        current = ""
    if current != content:
        write_text_atomic(SYSCTL_PATH, content, mode=0o644)
    run(f"sysctl --write vm.swappiness={value}")


def _configure_zswap(enabled: bool | None, pool_percent: int | None) -> None:
    if enabled is None:
        return
    if not os.path.exists("/sys/module/zswap/parameters/enabled"):
        if enabled:
            raise RuntimeError("This kernel does not expose zswap controls")
        if os.path.exists(ZSWAP_SERVICE_PATH):
            run("systemctl disable --now infra-tools-zswap.service", check=False)
            remove_file_durable(ZSWAP_SERVICE_PATH)
            run("systemctl daemon-reload")
        return
    state = "Y" if enabled else "N"
    commands = [
        "[Unit]",
        "Description=Apply infra-tools zswap policy",
        "After=systemd-modules-load.service",
        "",
        "[Service]",
        "Type=oneshot",
        "RemainAfterExit=yes",
        f"ExecStart=/bin/sh -c 'printf {state} > /sys/module/zswap/parameters/enabled'",
    ]
    if pool_percent is not None:
        commands.append(
            "ExecStart=/bin/sh -c 'printf "
            f"{pool_percent} > /sys/module/zswap/parameters/max_pool_percent'"
        )
    commands.extend(("", "[Install]", "WantedBy=multi-user.target", ""))
    content = "\n".join(commands)
    try:
        current = Path(ZSWAP_SERVICE_PATH).read_text(encoding="utf-8")
    except FileNotFoundError:
        current = ""
    changed = current != content
    if changed:
        write_text_atomic(ZSWAP_SERVICE_PATH, content, mode=0o644)
        run("systemctl daemon-reload")
    run("systemctl enable infra-tools-zswap.service")
    live_state = Path("/sys/module/zswap/parameters/enabled").read_text(
        encoding="utf-8"
    ).strip().upper()
    live_pool = (
        Path("/sys/module/zswap/parameters/max_pool_percent")
        .read_text(encoding="utf-8")
        .strip()
        if pool_percent is not None
        else None
    )
    if changed or live_state != state or (
        pool_percent is not None and live_pool != str(pool_percent)
    ):
        run("systemctl restart infra-tools-zswap.service")
    else:
        run("systemctl start infra-tools-zswap.service")


def _remove_managed_zswap() -> None:
    if not os.path.exists(ZSWAP_SERVICE_PATH):
        return
    if os.path.exists("/sys/module/zswap/parameters/enabled"):
        run("sh -c 'printf N > /sys/module/zswap/parameters/enabled'")
    run("systemctl disable --now infra-tools-zswap.service", check=False)
    remove_file_durable(ZSWAP_SERVICE_PATH)
    run("systemctl daemon-reload")


def _remove_area(area: dict[str, Any], active: set[str]) -> None:
    source = str(area.get("path") or area.get("source") or "")
    candidates = {source}
    if area.get("uuid"):
        candidates.add(f"/dev/disk/by-uuid/{area['uuid']}")
    if candidates & active:
        run(f"swapoff {shlex.quote(source)}")
    if area.get("type") == "file" and source:
        if not os.path.exists(source):
            return
        if _swap_type(source) != "swap":
            raise RuntimeError(
                f"Managed swap file {source} no longer has a swap signature; "
                "refusing to remove it"
            )
        remove_file_durable(source)


def _fstab_field(value: str) -> str:
    return value.replace("\\", "\\134").replace(" ", "\\040").replace("\t", "\\011")


def _fstab_entry(area: dict[str, Any]) -> str | None:
    if area["type"] == "file":
        return (
            f"{_fstab_field(str(area['source']))} none swap "
            f"sw,pri={area['priority']} 0 0"
        )
    if area["type"] == "device":
        options = ["sw", f"pri={area['priority']}"]
        discard = area.get("discard", "off")
        if discard != "off":
            options.append(
                "discard" if discard == "both" else f"discard={discard}"
            )
        return f"UUID={area['uuid']} none swap {','.join(options)} 0 0"
    return None


def _configure_resume(name: str | None, areas: list[dict[str, Any]]) -> None:
    previous = os.path.exists(RESUME_PATH)
    if name is None:
        if previous:
            remove_file_durable(RESUME_PATH)
            run("update-initramfs -u")
        return
    area = next((item for item in areas if item["name"] == name), None)
    if area is None or area["type"] != "device":
        raise RuntimeError("The configured resume swap device was not reconciled")
    content = f"RESUME=UUID={area['uuid']}\n"
    try:
        current = Path(RESUME_PATH).read_text(encoding="utf-8")
    except FileNotFoundError:
        current = ""
    if current != content:
        write_text_atomic(RESUME_PATH, content, mode=0o644)
        run("update-initramfs -u")


def _automatic_swap_file() -> SwapFile | None:
    ram_mb = get_total_ram_mb()
    if ram_mb == 0:
        print("  ⚠ Could not detect RAM size; leaving swap unchanged")
        return None
    size_mb = ram_mb * 2 if ram_mb < 2048 else ram_mb if ram_mb < 8192 else 4096
    free_mb = get_free_disk_mb()
    if free_mb < size_mb + 1024:
        if free_mb <= 2048:
            print(f"  ⚠ Not enough free root storage for swap ({free_mb} MiB free)")
            return None
        size_mb = 1024
        print("  ⚠ Reducing automatic swap to 1024 MiB due to free space")
    return SwapFile("auto-root", "/swapfile", f"{size_mb}M", 100)


def configure_swap(config: SetupConfig) -> None:
    """Reconcile only swap areas explicitly owned by infra-tools."""

    explicit = has_explicit_swap_areas(config)
    if is_dry_run() or config.dry_run:
        count = len(swap_files(config)) + len(swap_devices(config)) + len(swap_zram(config))
        print(f"  [dry-run] swap mode={config.swap_mode}, declared areas={count}")
        return
    if (
        config.system_type == "server_proxmox"
        and not explicit
        and config.swap_mode in {"auto", "preserve"}
    ):
        _configure_swappiness(config.swappiness)
        _configure_zswap(config.zswap, config.zswap_max_pool_percent)
        print("  ✓ Preserving Proxmox host swap layout")
        return
    if not can_manage_swap():
        print("  ✓ Skipping swap configuration (managed by container host)")
        return

    state = _load_state()
    old_areas = [item for item in state["areas"] if isinstance(item, dict)]
    old_by_name = {str(item.get("name")): item for item in old_areas}
    active = _active_swap()

    if config.swap_mode == "preserve":
        _configure_swappiness(config.swappiness)
        _configure_zswap(config.zswap, config.zswap_max_pool_percent)
        print("  ✓ Preserving existing swap areas")
        return
    if config.swap_mode == "none":
        for area in old_areas:
            if area.get("type") != "zram":
                _remove_area(area, active)
        _reconcile_zram(
            [], [area for area in old_areas if area.get("type") == "zram"]
        )
        _replace_fstab([])
        _configure_resume(None, [])
        _configure_swappiness(None, remove=True)
        _remove_managed_zswap()
        remove_file_durable(SWAP_STATE_FILE)
        print("  ✓ Removed infra-tools-managed swap areas")
        return

    desired_files = swap_files(config)
    desired_devices = swap_devices(config)
    desired_zram = swap_zram(config)
    if not explicit:
        if old_areas:
            desired_files = [
                SwapFile(
                    str(area["name"]),
                    str(area["source"]),
                    str(area["size"]),
                    int(area["priority"]),
                )
                for area in old_areas
                if area.get("type") == "file"
            ]
            desired_devices = [
                SwapDevice(
                    str(area["name"]),
                    str(area["source"]),
                    int(area["priority"]),
                    str(area.get("discard", "off")),
                )
                for area in old_areas
                if area.get("type") == "device"
            ]
            desired_zram = [
                SwapZram(
                    str(area["name"]),
                    str(area["size"]),
                    int(area["priority"]),
                    str(area.get("algorithm", "auto")),
                )
                for area in old_areas
                if area.get("type") == "zram"
            ]
        if not old_areas and active:
            print("  ✓ Existing swap is already configured; leaving it unmanaged")
            _configure_swappiness(config.swappiness)
            _configure_zswap(config.zswap, config.zswap_max_pool_percent)
            return
        if not old_areas and os.path.exists("/swapfile"):
            print("  ✓ Existing /swapfile is not owned by infra-tools; leaving it unchanged")
            return
        if not old_areas:
            automatic = _automatic_swap_file()
            if automatic is None:
                return
            desired_files = [automatic]

    desired_names = {
        area.name for area in [*desired_files, *desired_devices, *desired_zram]
    }
    new_areas: list[dict[str, Any]] = []
    for area in desired_files:
        new_areas.append(_ensure_swap_file(area, old_by_name.get(area.name)))
    for area in desired_devices:
        new_areas.append(_ensure_swap_device(config, area, old_by_name.get(area.name)))
    for area in old_areas:
        if area.get("name") not in desired_names and area.get("type") != "zram":
            _remove_area(area, active)
    old_zram_areas = [area for area in old_areas if area.get("type") == "zram"]
    new_areas.extend(_reconcile_zram(desired_zram, old_zram_areas))
    _replace_fstab(
        [entry for area in new_areas if (entry := _fstab_entry(area)) is not None]
    )
    _configure_swappiness(config.swappiness if config.swappiness is not None else 10)
    _configure_zswap(config.zswap, config.zswap_max_pool_percent)
    _configure_resume(config.swap_resume, new_areas)
    write_json_atomic(
        SWAP_STATE_FILE,
        {"schema": SWAP_SCHEMA_VERSION, "areas": new_areas},
        mode=0o600,
        sort_keys=True,
    )
    print(f"  ✓ Reconciled {len(new_areas)} managed swap area(s)")
