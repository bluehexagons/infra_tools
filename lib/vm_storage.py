"""Shared models and stable identities for provisioned VM data storage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lib.config import SetupConfig


_UNIT_TO_KIB = {
    "K": 1,
    "M": 1024,
    "G": 1024 * 1024,
    "T": 1024 * 1024 * 1024,
}


@dataclass(frozen=True)
class VMDataDisk:
    """A validated, provider-backed non-root VM disk declaration."""

    name: str
    pool: str
    size: str

    @property
    def serial(self) -> str:
        return storage_disk_serial(self.name)


@dataclass(frozen=True)
class VMStorageMount:
    """A validated guest mount declaration for one named VM data disk."""

    name: str
    path: str
    filesystem: str = "ext4"
    policy: str = "empty"


def storage_size_kib(value: str) -> int:
    """Convert a validated binary-size declaration to KiB."""

    return int(value[:-1]) * _UNIT_TO_KIB[value[-1].upper()]


def storage_disk_serial(name: str) -> str:
    """Return the stable serial reported by Proxmox to the guest.

    Proxmox limits drive serials to 20 bytes. Validation limits logical names
    so the ``it-`` prefix plus the complete name always fits without a lossy
    truncation or hash collision.
    """

    return f"it-{name}"


def data_disks(config: SetupConfig) -> list[VMDataDisk]:
    """Return non-root, non-template storage declarations in CLI order."""

    result: list[VMDataDisk] = []
    for spec in config.container_storage or []:
        if len(spec) == 3 and spec[0] not in {"root", "template"}:
            result.append(VMDataDisk(spec[0], spec[1], spec[2]))
    return result


def storage_mounts(config: SetupConfig) -> list[VMStorageMount]:
    """Return normalized mount declarations in CLI order."""

    result: list[VMStorageMount] = []
    for spec in config.storage_mounts or []:
        if len(spec) < 2:
            continue
        result.append(
            VMStorageMount(
                name=spec[0],
                path=spec[1],
                filesystem=spec[2] if len(spec) >= 3 else "ext4",
                policy=spec[3] if len(spec) >= 4 else "empty",
            )
        )
    return result


def has_home_mount(config: SetupConfig) -> bool:
    """Return whether provisioning will mount a dedicated filesystem at /home."""

    return any(mount.path == "/home" for mount in storage_mounts(config))
