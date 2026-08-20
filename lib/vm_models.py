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


__all__ = ["VMHealth", "VMRecord", "VM_SCHEMA_VERSION", "envelope"]
