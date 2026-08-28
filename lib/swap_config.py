"""Normalized declarations for managed Linux swap areas."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lib.config import SetupConfig


@dataclass(frozen=True)
class SwapFile:
    name: str
    path: str
    size: str
    priority: int = 100


@dataclass(frozen=True)
class SwapDevice:
    name: str
    source: str
    priority: int = 100
    discard: str = "off"


@dataclass(frozen=True)
class SwapZram:
    name: str
    size: str
    priority: int = 300
    algorithm: str = "auto"


def _options(spec: list[str]) -> dict[str, str]:
    return dict(part.split("=", 1) for part in spec if "=" in part)


def swap_files(config: SetupConfig) -> list[SwapFile]:
    result: list[SwapFile] = []
    for spec in config.swap_files or []:
        if len(spec) < 3:
            continue
        options = _options(spec[3:])
        result.append(
            SwapFile(spec[0], spec[1], spec[2], int(options.get("priority", "100")))
        )
    return result


def swap_devices(config: SetupConfig) -> list[SwapDevice]:
    result: list[SwapDevice] = []
    for spec in config.swap_devices or []:
        if len(spec) < 2:
            continue
        options = _options(spec[2:])
        result.append(
            SwapDevice(
                spec[0],
                spec[1],
                int(options.get("priority", "100")),
                options.get("discard", "off"),
            )
        )
    return result


def swap_zram(config: SetupConfig) -> list[SwapZram]:
    result: list[SwapZram] = []
    for spec in config.swap_zram or []:
        if len(spec) < 2:
            continue
        options = _options(spec[2:])
        result.append(
            SwapZram(
                spec[0],
                spec[1],
                int(options.get("priority", "300")),
                options.get("algorithm", "auto"),
            )
        )
    return result


def swap_device_disk_names(config: SetupConfig) -> set[str]:
    """Return device sources that name provider-declared VM data disks."""

    declared = {
        spec[0]
        for spec in config.container_storage or []
        if len(spec) == 3 and spec[0] not in {"root", "template"}
    }
    return {area.source for area in swap_devices(config) if area.source in declared}


def has_explicit_swap_areas(config: SetupConfig) -> bool:
    return bool(config.swap_files or config.swap_devices or config.swap_zram)
