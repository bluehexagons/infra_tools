"""Proxmox node resource summary: CPU, memory, storage, and guest counts."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from lib.proxmox_guest import _ssh_opts, _ssh_run
from lib.proxmox_hosts import ProxmoxHost


class ProxmoxSummaryError(Exception):
    """Raised when the node summary cannot be fetched or parsed."""


@dataclass
class NodeSummary:
    """Resource snapshot for a single Proxmox node."""

    node_name: str
    cpu_usage: float        # 0.0 – 1.0
    cpu_count: int
    memory_used: int        # bytes
    memory_total: int       # bytes
    swap_used: int          # bytes
    swap_total: int         # bytes
    disk_used: int          # bytes (root filesystem)
    disk_total: int         # bytes
    uptime_seconds: int
    guests_running: int = 0
    guests_stopped: int = 0
    load_avg: list[float] = field(default_factory=list)


def _run(host: ProxmoxHost, cmd: str) -> subprocess.CompletedProcess[str]:
    return _ssh_run(host.address, host.user, _ssh_opts(host.ssh_key), cmd)


def get_node_summary(host: ProxmoxHost) -> NodeSummary:
    """Fetch CPU, memory, storage, and guest counts for a Proxmox node."""
    result = _run(
        host,
        "pvesh get /nodes/$(hostname -s)/summary --output-format json 2>/dev/null",
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise ProxmoxSummaryError(
            f"Could not fetch node summary from {host.address}: "
            f"{(result.stderr or '').strip() or 'no output from pvesh'}"
        )
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProxmoxSummaryError(
            f"Could not parse node summary from {host.address}: {exc}"
        ) from exc

    memory = data.get("memory") or {}
    swap = data.get("swap") or {}
    rootfs = data.get("rootfs") or {}
    cpuinfo = data.get("cpuinfo") or {}
    loadavg_raw = data.get("loadavg") or []

    # Count running and stopped guests using the typed parsers from proxmox_manage.
    from lib.proxmox_manage import _parse_pct_list, _parse_qm_list
    guests_running = 0
    guests_stopped = 0
    pct_r = _run(host, "pct list")
    if pct_r.returncode == 0:
        for guest in _parse_pct_list(pct_r.stdout):
            if guest.status.lower() == "running":
                guests_running += 1
            else:
                guests_stopped += 1
    qm_r = _run(host, "qm list")
    if qm_r.returncode == 0:
        for guest in _parse_qm_list(qm_r.stdout):
            if guest.status.lower() == "running":
                guests_running += 1
            else:
                guests_stopped += 1

    node_name = str(data.get("name") or host.name or host.address)

    return NodeSummary(
        node_name=node_name,
        cpu_usage=float(data.get("cpu") or 0.0),
        cpu_count=int(cpuinfo.get("cpus") or 0),
        memory_used=int(memory.get("used") or 0),
        memory_total=int(memory.get("total") or 1),
        swap_used=int(swap.get("used") or 0),
        swap_total=int(swap.get("total") or 0),
        disk_used=int(rootfs.get("used") or 0),
        disk_total=int(rootfs.get("total") or 1),
        uptime_seconds=int(data.get("uptime") or 0),
        guests_running=guests_running,
        guests_stopped=guests_stopped,
        load_avg=[float(v) for v in loadavg_raw if v is not None],
    )


def format_node_summary(summary: NodeSummary) -> str:
    """Return a human-readable multi-line string for a :class:`NodeSummary`."""
    lines = [
        f"  Node:    {summary.node_name}",
        f"  CPU:     {_bar(summary.cpu_usage)}  "
        f"{summary.cpu_usage * 100:.1f}%  ({summary.cpu_count} cores)",
        f"  Memory:  {_bar(summary.memory_used / max(1, summary.memory_total))}  "
        f"{_fmt_bytes(summary.memory_used)} / {_fmt_bytes(summary.memory_total)}",
    ]
    if summary.swap_total > 0:
        lines.append(
            f"  Swap:    {_bar(summary.swap_used / max(1, summary.swap_total))}  "
            f"{_fmt_bytes(summary.swap_used)} / {_fmt_bytes(summary.swap_total)}"
        )
    lines.append(
        f"  Root FS: {_bar(summary.disk_used / max(1, summary.disk_total))}  "
        f"{_fmt_bytes(summary.disk_used)} / {_fmt_bytes(summary.disk_total)}"
    )
    if summary.load_avg:
        load_str = "  ".join(f"{v:.2f}" for v in summary.load_avg[:3])
        lines.append(f"  Load:    {load_str}")
    hours, rem = divmod(summary.uptime_seconds, 3600)
    lines.append(f"  Uptime:  {hours}h {rem // 60}m")
    lines.append(
        f"  Guests:  {summary.guests_running} running, "
        f"{summary.guests_stopped} stopped"
    )
    return "\n".join(lines)


def _bar(fraction: float, width: int = 20) -> str:
    filled = round(max(0.0, min(1.0, fraction)) * width)
    return f"[{'#' * filled}{'.' * (width - filled)}]"


def _fmt_bytes(b: int) -> str:
    if b >= 1024 ** 3:
        return f"{b / 1024 ** 3:.1f} GiB"
    if b >= 1024 ** 2:
        return f"{b / 1024 ** 2:.0f} MiB"
    return f"{b / 1024:.0f} KiB"


__all__ = [
    "NodeSummary",
    "ProxmoxSummaryError",
    "format_node_summary",
    "get_node_summary",
]
