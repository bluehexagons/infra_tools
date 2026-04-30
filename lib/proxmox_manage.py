#!/usr/bin/env python3
"""LXC container management against a Proxmox host over SSH.

Provides helpers for:
- Listing containers (``pct list``).
- Querying status, config, and uptime for a single container.
- Starting and stopping containers.
- Destroying containers (caller is expected to handle confirmation).
- Health-checking a container (status + ping + optional SSH probe).

All commands run via ``ssh root@<node>`` using the existing
:mod:`lib.proxmox_node` SSH helpers so behaviour stays consistent with the
provisioning path.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from lib.proxmox_hosts import ProxmoxHost
from lib.proxmox_node import _ssh_opts, _ssh_run
from lib.types import StrList


class ProxmoxManageError(Exception):
    """Raised when a management operation fails on the Proxmox host."""


@dataclass
class ContainerInfo:
    """One row returned from ``pct list`` plus optional enrichment."""

    vmid: int
    status: str
    name: str
    lock: Optional[str] = None
    ip: Optional[str] = None


@dataclass
class HealthReport:
    """Result of :func:`health_check` for a single container."""

    vmid: int
    status: str
    pingable: Optional[bool] = None
    ssh_open: Optional[bool] = None
    ip: Optional[str] = None
    notes: list[str] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        if self.status != "running":
            return False
        if self.ip is None:
            return False
        # Network probes are best-effort; only fail health if explicitly False.
        if self.pingable is False:
            return False
        if self.ssh_open is False:
            return False
        return True


def _run_on_host(
    host: ProxmoxHost,
    cmd: str,
    *,
    dry_run: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Execute ``cmd`` on ``host`` over SSH, returning the completed process."""
    opts = _ssh_opts(host.ssh_key)
    return _ssh_run(host.address, host.user, opts, cmd, dry_run=dry_run)


def _parse_pct_list(stdout: str) -> list[ContainerInfo]:
    """Parse ``pct list`` output into :class:`ContainerInfo` rows."""
    rows: list[ContainerInfo] = []
    lines = [ln for ln in (stdout or "").splitlines() if ln.strip()]
    if not lines:
        return rows
    header = lines[0].split()
    if not header or header[0].upper() != "VMID":
        # Some pct versions emit no header; assume all lines are data.
        data_lines = lines
    else:
        data_lines = lines[1:]
    for line in data_lines:
        parts = line.split()
        if not parts:
            continue
        try:
            vmid = int(parts[0])
        except ValueError:
            continue
        status = parts[1] if len(parts) >= 2 else "unknown"
        # pct list columns: VMID Status [Lock] Name
        if len(parts) == 2:
            name = ""
            lock: Optional[str] = None
        elif len(parts) == 3:
            name = parts[2]
            lock = None
        else:
            # Heuristic: if the third token is a recognised lock keyword treat
            # it as the Lock column; otherwise treat everything after status as
            # the name (names can contain spaces in rare cases via display).
            third = parts[2]
            if third in {
                "backup", "create", "destroyed", "disk", "fstrim",
                "migrate", "mounted", "rollback", "snapshot",
                "snapshot-delete",
            }:
                lock = third
                name = " ".join(parts[3:])
            else:
                lock = None
                name = " ".join(parts[2:])
        rows.append(ContainerInfo(vmid=vmid, status=status, name=name, lock=lock))
    return rows


def list_containers(
    host: ProxmoxHost, *, dry_run: bool = False
) -> list[ContainerInfo]:
    """Return the LXC containers on ``host`` (sorted by VMID)."""
    if dry_run:
        return []
    result = _run_on_host(host, "pct list")
    if result.returncode != 0:
        raise ProxmoxManageError(
            f"pct list failed on {host.address}: "
            f"{(result.stderr or result.stdout or '').strip() or 'no output'}"
        )
    rows = _parse_pct_list(result.stdout)
    rows.sort(key=lambda r: r.vmid)
    return rows


_NET0_IP_RE = re.compile(r"(?:^|,)ip=([^,\s]+)")


def get_container_ip(
    host: ProxmoxHost, vmid: int, *, dry_run: bool = False
) -> Optional[str]:
    """Return the configured IPv4 address from ``pct config`` (no CIDR)."""
    if dry_run:
        return None
    result = _run_on_host(host, f"pct config {int(vmid)}")
    if result.returncode != 0:
        return None
    for line in (result.stdout or "").splitlines():
        if not line.startswith("net0:"):
            continue
        match = _NET0_IP_RE.search(line)
        if not match:
            continue
        return match.group(1).split("/", 1)[0].strip() or None
    return None


def get_container_status(host: ProxmoxHost, vmid: int) -> str:
    """Return the textual status from ``pct status`` (e.g. ``running``)."""
    result = _run_on_host(host, f"pct status {int(vmid)}")
    if result.returncode != 0:
        raise ProxmoxManageError(
            f"pct status {vmid} failed on {host.address}: "
            f"{(result.stderr or '').strip() or 'unknown error'}"
        )
    # Output format: "status: running"
    out = (result.stdout or "").strip()
    if ":" in out:
        return out.split(":", 1)[1].strip() or "unknown"
    return out or "unknown"


def start_container(host: ProxmoxHost, vmid: int) -> None:
    """Start an LXC container on ``host``; idempotent if already running."""
    current = get_container_status(host, vmid)
    if current == "running":
        return
    result = _run_on_host(host, f"pct start {int(vmid)}")
    if result.returncode != 0:
        raise ProxmoxManageError(
            f"pct start {vmid} failed on {host.address}: "
            f"{(result.stderr or '').strip() or 'unknown error'}"
        )


def stop_container(
    host: ProxmoxHost, vmid: int, *, force: bool = False
) -> None:
    """Stop an LXC container.

    By default uses ``pct shutdown`` (graceful). When ``force`` is True falls
    back to ``pct stop`` (immediate). Idempotent if already stopped.
    """
    current = get_container_status(host, vmid)
    if current == "stopped":
        return
    cmd = f"pct stop {int(vmid)}" if force else f"pct shutdown {int(vmid)}"
    result = _run_on_host(host, cmd)
    if result.returncode != 0:
        raise ProxmoxManageError(
            f"{cmd} failed on {host.address}: "
            f"{(result.stderr or '').strip() or 'unknown error'}"
        )


def destroy_container(
    host: ProxmoxHost,
    vmid: int,
    *,
    purge: bool = True,
    force: bool = False,
) -> None:
    """Destroy an LXC container.

    The container is stopped first if needed. ``purge`` removes the container
    from backup/HA configs as well. Pass ``force`` to skip stop verification
    and use ``pct stop`` instead of shutdown.
    """
    try:
        current = get_container_status(host, vmid)
    except ProxmoxManageError:
        current = "unknown"
    if current == "running":
        stop_container(host, vmid, force=force)
    flags: StrList = []
    if purge:
        flags.append("--purge")
    if force:
        flags.append("--force")
    cmd = f"pct destroy {int(vmid)}"
    if flags:
        cmd += " " + " ".join(flags)
    result = _run_on_host(host, cmd)
    if result.returncode != 0:
        raise ProxmoxManageError(
            f"pct destroy {vmid} failed on {host.address}: "
            f"{(result.stderr or '').strip() or 'unknown error'}"
        )


def health_check(
    host: ProxmoxHost,
    vmid: int,
    *,
    probe_ssh: bool = True,
    timeout: int = 3,
) -> HealthReport:
    """Run a best-effort health check against ``vmid`` on ``host``.

    Combines ``pct status`` with a ping from the host and (optionally) a
    TCP probe on port 22. Network probes are recorded but never raise — the
    Proxmox host occasionally lacks ``ping`` or the container may be on an
    isolated bridge.
    """
    report = HealthReport(vmid=vmid, status="unknown")
    try:
        report.status = get_container_status(host, vmid)
    except ProxmoxManageError as exc:
        report.notes.append(str(exc))
        return report

    ip = get_container_ip(host, vmid)
    report.ip = ip
    if not ip:
        report.notes.append("No IPv4 address configured on net0")
        return report

    if report.status != "running":
        report.notes.append(f"Container is not running (status={report.status})")
        return report

    ping_cmd = (
        f"ping -c 1 -W {int(timeout)} {shlex.quote(ip)} >/dev/null 2>&1 "
        f"&& echo OK || echo FAIL"
    )
    ping_result = _run_on_host(host, ping_cmd)
    if ping_result.returncode == 0:
        report.pingable = "OK" in (ping_result.stdout or "")
    else:
        report.notes.append("ping probe could not be executed")

    if probe_ssh:
        ssh_cmd = (
            f"timeout {int(timeout)} bash -c "
            f"'</dev/tcp/{shlex.quote(ip)}/22' && echo OK || echo FAIL"
        )
        ssh_result = _run_on_host(host, ssh_cmd)
        if ssh_result.returncode == 0:
            report.ssh_open = "OK" in (ssh_result.stdout or "")
        else:
            report.notes.append("SSH probe could not be executed")

    return report
