"""Host-level Proxmox setup steps."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from lib.proxmox_memory import (
    DEFAULT_BALLOON_TARGET_PERCENT,
    calculate_balloon_target,
    format_gib,
)
from lib.remote_utils import is_dry_run, run

if TYPE_CHECKING:
    from lib.config import SetupConfig


def _host_total_memory_mib(meminfo_path: str = "/proc/meminfo") -> int:
    """Read physical host RAM from Linux meminfo."""
    try:
        with open(meminfo_path, "r", encoding="utf-8") as meminfo:
            for line in meminfo:
                if line.startswith("MemTotal:"):
                    fields = line.split()
                    return int(fields[1]) // 1024
    except (OSError, ValueError, IndexError) as exc:
        raise RuntimeError(f"Unable to determine Proxmox host memory: {exc}") from exc
    raise RuntimeError("Unable to determine Proxmox host memory: MemTotal is missing")


def _configured_balloon_target(output: str) -> int | None:
    """Extract an explicitly stored node target, if present."""
    if not output.strip():
        return None
    try:
        config: Any = json.loads(output)
        value = config.get("ballooning-target")
        if value is None:
            return None
        return int(value)
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "Unable to read the existing Proxmox balloon target"
        ) from exc


def configure_proxmox_balloon_target(config: SetupConfig) -> None:
    """Apply an idempotent, host-size-aware Proxmox balloon target."""
    total_mib = _host_total_memory_mib()
    policy = calculate_balloon_target(
        total_mib,
        getattr(config, "proxmox_balloon_target", None),
    )
    source = "automatic" if policy.automatic else "override"
    print(
        "  Proxmox memory policy: "
        f"{format_gib(policy.total_mib)} host RAM, "
        f"{policy.target_percent}% balloon target ({source}), "
        f"{format_gib(policy.reserve_mib)} host headroom"
    )
    if policy.automatic and total_mib < 4096:
        print(
            "  ⚠ Host RAM is below 4 GiB; the 50% safety floor cannot preserve "
            "a full 2 GiB of headroom"
        )

    set_command = (
        "pvenode config set "
        f"--ballooning-target {policy.target_percent}"
    )
    if is_dry_run():
        run(set_command)
        return

    current = run(
        "pvenode config get --output-format json",
        capture_output=True,
    )
    current_target = _configured_balloon_target(current)
    if current_target == policy.target_percent:
        print(f"  ✓ Balloon target already set to {current_target}%")
        return

    run(set_command)
    verified = run(
        "pvenode config get --output-format json",
        capture_output=True,
    )
    verified_target = _configured_balloon_target(verified)
    if verified_target != policy.target_percent:
        raise RuntimeError(
            "Proxmox balloon target verification failed: "
            f"expected {policy.target_percent}%, found {verified_target}%"
        )
    previous = (
        f"{current_target}%"
        if current_target is not None
        else f"implicit default ({DEFAULT_BALLOON_TARGET_PERCENT}%)"
    )
    print(f"  ✓ Changed balloon target from {previous} to {verified_target}%")
