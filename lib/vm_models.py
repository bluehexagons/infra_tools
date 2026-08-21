"""Provider-neutral models for virtual-machine management output."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from lib.types import JSONDict, JSONList


VM_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class VMRecord:
    """A provider-neutral virtual-machine or container inventory row."""

    id: str
    kind: str
    name: str
    state: str
    lock: Optional[str] = None
    address: Optional[str] = None

    def to_dict(self) -> JSONDict:
        result: JSONDict = {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "state": self.state,
        }
        if self.lock is not None:
            result["lock"] = self.lock
        if self.address is not None:
            result["address"] = self.address
        return result


@dataclass(frozen=True)
class VMHealth:
    """A provider-neutral health observation for one guest."""

    id: str
    kind: Optional[str]
    state: str
    healthy: bool
    address: Optional[str]
    pingable: Optional[bool]
    ssh_open: Optional[bool]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> JSONDict:
        return {
            "id": self.id,
            "kind": self.kind,
            "state": self.state,
            "healthy": self.healthy,
            "address": self.address,
            "pingable": self.pingable,
            "ssh_open": self.ssh_open,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class VMStats:
    """Provider-neutral live resource counters for one guest."""

    id: str
    kind: str
    name: str
    state: str
    cpu_usage: float
    cpu_count: int
    memory_used: int
    memory_total: int
    swap_used: int
    swap_total: int
    disk_used: int
    disk_total: int
    disk_read: int
    disk_written: int
    network_in: int
    network_out: int
    uptime_seconds: int
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> JSONDict:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "state": self.state,
            "cpu_usage": self.cpu_usage,
            "cpu_count": self.cpu_count,
            "memory_used": self.memory_used,
            "memory_total": self.memory_total,
            "swap_used": self.swap_used,
            "swap_total": self.swap_total,
            "disk_used": self.disk_used,
            "disk_total": self.disk_total,
            "disk_read": self.disk_read,
            "disk_written": self.disk_written,
            "network_in": self.network_in,
            "network_out": self.network_out,
            "uptime_seconds": self.uptime_seconds,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class VMAutostart:
    """Provider-neutral guest start-at-boot settings."""

    id: str
    kind: str
    name: str
    enabled: bool
    order: Optional[int]
    start_delay: Optional[int]
    shutdown_timeout: Optional[int]

    def to_dict(self) -> JSONDict:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "enabled": self.enabled,
            "order": self.order,
            "start_delay": self.start_delay,
            "shutdown_timeout": self.shutdown_timeout,
        }


def envelope(
    *,
    provider: str,
    host: str,
    operation: str,
    resources: JSONList,
) -> JSONDict:
    """Build the stable outer shape used by all ``vm`` JSON commands."""

    return {
        "schema_version": VM_SCHEMA_VERSION,
        "provider": provider,
        "host": host,
        "operation": operation,
        "resources": resources,
    }


__all__ = [
    "VMAutostart",
    "VMHealth",
    "VMRecord",
    "VMStats",
    "VM_SCHEMA_VERSION",
    "envelope",
]
