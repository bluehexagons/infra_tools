"""Read-only Proxmox node maintenance and reboot preflight checks."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass, field
from typing import Optional

from lib.proxmox_hosts import ProxmoxHost
from lib.proxmox_manage import ContainerInfo, _parse_pct_list, _parse_qm_list
from lib.ssh_utils import build_ssh_command, get_ssh_control_path


MIN_ROOT_FREE_BYTES = 4 * 1024 ** 3
CORE_SERVICES = (
    "pve-cluster",
    "pvedaemon",
    "pveproxy",
    "pvestatd",
    "pvescheduler",
)


@dataclass
class ProxmoxMaintenanceReport:
    """Observed node state used by audits and rolling-update safety gates."""

    host_name: str
    address: str
    node_name: str = ""
    clustered: Optional[bool] = None
    quorate: Optional[bool] = None
    service_states: dict[str, str] = field(default_factory=dict)
    active_tasks: list[str] = field(default_factory=list)
    running_guests: list[ContainerInfo] = field(default_factory=list)
    locked_guests: list[ContainerInfo] = field(default_factory=list)
    storage_states: dict[str, str] = field(default_factory=dict)
    root_free_bytes: Optional[int] = None
    reboot_required: Optional[bool] = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        """Return whether all required maintenance checks passed."""
        return not self.errors

    @property
    def reboot_safe(self) -> bool:
        """Return whether the node is healthy and has no active guests."""
        return self.healthy and not self.running_guests and not self.locked_guests

    def reboot_blockers(self) -> list[str]:
        """Return concise reasons an automatic node reboot must not proceed."""
        blockers = list(self.errors)
        if self.running_guests:
            guest_ids = ", ".join(str(guest.vmid) for guest in self.running_guests)
            blockers.append(f"running guests: {guest_ids}")
        if self.locked_guests:
            locked_ids = ", ".join(str(guest.vmid) for guest in self.locked_guests)
            blockers.append(f"locked guests: {locked_ids}")
        return blockers

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable maintenance report."""
        return {
            "host_name": self.host_name,
            "address": self.address,
            "node_name": self.node_name,
            "healthy": self.healthy,
            "reboot_safe": self.reboot_safe,
            "clustered": self.clustered,
            "quorate": self.quorate,
            "service_states": dict(self.service_states),
            "active_tasks": list(self.active_tasks),
            "running_guests": [asdict(guest) for guest in self.running_guests],
            "locked_guests": [asdict(guest) for guest in self.locked_guests],
            "storage_states": dict(self.storage_states),
            "root_free_bytes": self.root_free_bytes,
            "reboot_required": self.reboot_required,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


def _run(host: ProxmoxHost, command: str) -> subprocess.CompletedProcess[str]:
    """Run a read-only command on a registered Proxmox host."""
    return subprocess.run(
        build_ssh_command(
            host.address,
            host.user,
            host.ssh_key,
            remote_command=command,
            batch_mode=False,
            connect_timeout=10,
            server_alive_interval=10,
            control_path=get_ssh_control_path(
                host.address, host.user, host.ssh_key
            ),
        ),
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def _failure_detail(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout or "").strip() or f"exit {result.returncode}"


def _format_task(task: object) -> str:
    if not isinstance(task, dict):
        return str(task)
    task_type = str(task.get("type") or "task")
    task_id = str(task.get("id") or "").strip()
    user = str(task.get("user") or "").strip()
    label = f"{task_type}:{task_id}" if task_id else task_type
    return f"{label} ({user})" if user else label


def _parse_storage_states(stdout: str) -> dict[str, str]:
    states: dict[str, str] = {}
    for line in stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 3:
            states[parts[0]] = parts[2].lower()
    return states


def collect_maintenance_report(host: ProxmoxHost) -> ProxmoxMaintenanceReport:
    """Collect a read-only maintenance preflight report for ``host``."""
    report = ProxmoxMaintenanceReport(host_name=host.name, address=host.address)

    try:
        identity = _run(host, "hostname -s")
    except (OSError, subprocess.TimeoutExpired) as exc:
        report.errors.append(f"SSH probe failed: {exc}")
        return report
    if identity.returncode != 0 or not identity.stdout.strip():
        report.errors.append(f"SSH probe failed: {_failure_detail(identity)}")
        return report
    report.node_name = identity.stdout.strip().splitlines()[0]

    try:
        services = _run(host, "systemctl is-active " + " ".join(CORE_SERVICES))
        service_lines = [line.strip().lower() for line in services.stdout.splitlines()]
        if len(service_lines) != len(CORE_SERVICES):
            report.errors.append("Could not determine every core Proxmox service state")
        for index, service_name in enumerate(CORE_SERVICES):
            state = service_lines[index] if index < len(service_lines) else "unknown"
            report.service_states[service_name] = state
            if state != "active":
                report.errors.append(f"Core service {service_name} is {state}")

        cluster_config = _run(host, "test -s /etc/pve/corosync.conf")
        if cluster_config.returncode == 0:
            report.clustered = True
            cluster_status = _run(host, "pvecm status")
            if cluster_status.returncode != 0:
                report.quorate = False
                report.errors.append(
                    f"Could not read cluster status: {_failure_detail(cluster_status)}"
                )
            else:
                match = re.search(
                    r"^Quorate:\s*(Yes|No)\s*$",
                    cluster_status.stdout,
                    re.IGNORECASE | re.MULTILINE,
                )
                report.quorate = bool(match and match.group(1).lower() == "yes")
                if not report.quorate:
                    report.errors.append("Cluster is not quorate")
        elif cluster_config.returncode == 1:
            report.clustered = False
        else:
            report.errors.append(
                f"Could not determine cluster membership: {_failure_detail(cluster_config)}"
            )

        tasks = _run(
            host,
            "pvenode task list --source active --output-format json",
        )
        if tasks.returncode != 0:
            report.errors.append(f"Could not list active tasks: {_failure_detail(tasks)}")
        else:
            try:
                task_data = json.loads(tasks.stdout or "[]")
            except json.JSONDecodeError as exc:
                report.errors.append(f"Could not parse active task list: {exc}")
            else:
                if not isinstance(task_data, list):
                    report.errors.append("Active task response was not a JSON list")
                else:
                    report.active_tasks = [_format_task(task) for task in task_data]
                    if report.active_tasks:
                        report.errors.append(
                            f"{len(report.active_tasks)} active Proxmox task(s)"
                        )

        pct_result = _run(host, "pct list")
        qm_result = _run(host, "qm list")
        if pct_result.returncode != 0:
            report.errors.append(f"Could not list LXC guests: {_failure_detail(pct_result)}")
        if qm_result.returncode != 0:
            report.errors.append(f"Could not list VM guests: {_failure_detail(qm_result)}")
        guests: list[ContainerInfo] = []
        if pct_result.returncode == 0:
            guests.extend(_parse_pct_list(pct_result.stdout))
        if qm_result.returncode == 0:
            guests.extend(_parse_qm_list(qm_result.stdout))
        guests.sort(key=lambda guest: guest.vmid)
        report.running_guests = [
            guest for guest in guests if guest.status.lower() == "running"
        ]
        report.locked_guests = [guest for guest in guests if guest.lock]
        if report.running_guests:
            report.warnings.append(f"{len(report.running_guests)} running guest(s)")
        if report.locked_guests:
            report.errors.append(f"{len(report.locked_guests)} locked guest(s)")

        storage = _run(host, "pvesm status")
        if storage.returncode != 0:
            report.errors.append(f"Could not read storage status: {_failure_detail(storage)}")
        else:
            report.storage_states = _parse_storage_states(storage.stdout)
            if not report.storage_states:
                report.errors.append("No Proxmox storage pools were reported")
            for storage_name, state in report.storage_states.items():
                if state != "active":
                    report.errors.append(f"Storage {storage_name} is {state}")

        root_free = _run(host, "df -Pk / | awk 'NR==2 {print $4}'")
        if root_free.returncode != 0:
            report.errors.append(f"Could not read root free space: {_failure_detail(root_free)}")
        else:
            try:
                report.root_free_bytes = int(root_free.stdout.strip()) * 1024
            except ValueError:
                report.errors.append("Could not parse root free space")
            else:
                if report.root_free_bytes < MIN_ROOT_FREE_BYTES:
                    report.errors.append("Root filesystem has less than 4 GiB free")

        reboot_required = _run(host, "test -f /var/run/reboot-required")
        if reboot_required.returncode in (0, 1):
            report.reboot_required = reboot_required.returncode == 0
            if report.reboot_required:
                report.warnings.append("Node already requires a reboot")
        else:
            report.errors.append(
                f"Could not check reboot-required state: {_failure_detail(reboot_required)}"
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        report.errors.append(f"Maintenance probe failed: {exc}")

    return report


def _format_bytes(value: Optional[int]) -> str:
    if value is None:
        return "unknown"
    return f"{value / 1024 ** 3:.1f} GiB"


def format_maintenance_report(report: ProxmoxMaintenanceReport) -> str:
    """Return a compact operator-facing maintenance report."""
    cluster = "unknown"
    if report.clustered is False:
        cluster = "standalone"
    elif report.clustered:
        cluster = "quorate" if report.quorate else "not quorate"

    service_text = ", ".join(
        f"{name}={state}" for name, state in report.service_states.items()
    ) or "unknown"
    storage_text = ", ".join(
        f"{name}={state}" for name, state in report.storage_states.items()
    ) or "unknown"
    lines = [
        f"Proxmox maintenance audit: {report.host_name} ({report.address})",
        f"  node:           {report.node_name or 'unknown'}",
        f"  result:         {'HEALTHY' if report.healthy else 'UNHEALTHY'}",
        f"  reboot safety:  {'READY' if report.reboot_safe else 'BLOCKED'}",
        f"  cluster:        {cluster}",
        f"  services:       {service_text}",
        f"  active tasks:   {len(report.active_tasks)}",
        f"  running guests: {len(report.running_guests)}",
        f"  locked guests:  {len(report.locked_guests)}",
        f"  storage:        {storage_text}",
        f"  root free:      {_format_bytes(report.root_free_bytes)}",
        "  reboot needed:  "
        + ("unknown" if report.reboot_required is None else str(report.reboot_required).lower()),
    ]
    if report.active_tasks:
        lines.append("  tasks:          " + ", ".join(report.active_tasks))
    if report.running_guests:
        guests = ", ".join(
            f"{guest.vmid} ({guest.guest_type}, {guest.name or '-'})"
            for guest in report.running_guests
        )
        lines.append(f"  guests:         {guests}")
    for error in report.errors:
        lines.append(f"  ERROR: {error}")
    for warning in report.warnings:
        lines.append(f"  WARNING: {warning}")
    return "\n".join(lines)


__all__ = [
    "CORE_SERVICES",
    "MIN_ROOT_FREE_BYTES",
    "ProxmoxMaintenanceReport",
    "collect_maintenance_report",
    "format_maintenance_report",
]
