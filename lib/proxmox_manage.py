#!/usr/bin/env python3
"""LXC container management against a Proxmox host over SSH.

Provides helpers for:
- Listing containers (``pct list``).
- Querying status, config, and uptime for a single container.
- Starting and stopping containers.
- Destroying containers (caller is expected to handle confirmation).
- Health-checking a container (status + ping + optional SSH probe).
- Configuring native Proxmox notification webhooks.

All commands run via ``ssh root@<node>`` using the existing
:mod:`lib.proxmox_node` SSH helpers so behaviour stays consistent with the
provisioning path.
"""

from __future__ import annotations

import base64
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from typing import Optional
import urllib.parse

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


@dataclass
class ProxmoxWebhookNotificationConfig:
    """Configuration for native Proxmox webhook notifications."""

    endpoint_name: str
    matcher_name: str
    url: str
    severities: list[str] = field(default_factory=list)


DEFAULT_NOTIFICATION_ENDPOINT = "infra-tools-webhook"
DEFAULT_NOTIFICATION_MATCHER = "infra-tools-system"
DEFAULT_NOTIFICATION_SEVERITIES = ["info", "notice", "warning", "error", "unknown"]
_NOTIFICATION_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,62}$")


def _run_on_host(
    host: ProxmoxHost,
    cmd: str,
    *,
    dry_run: bool = False,
    log_cmd: Optional[str] = None,
) -> subprocess.CompletedProcess[str]:
    """Execute ``cmd`` on ``host`` over SSH, returning the completed process."""
    opts = _ssh_opts(host.ssh_key)
    return _ssh_run(host.address, host.user, opts, cmd, dry_run=dry_run, log_cmd=log_cmd)


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


def install_webhook_notifications(
    host: ProxmoxHost,
    url: str,
    *,
    endpoint_name: str = DEFAULT_NOTIFICATION_ENDPOINT,
    matcher_name: str = DEFAULT_NOTIFICATION_MATCHER,
    severities: Optional[list[str]] = None,
    send_test: bool = False,
    dry_run: bool = False,
) -> ProxmoxWebhookNotificationConfig:
    """Configure Proxmox's native webhook notifier for system notifications.

    This uses Proxmox VE's notification API through ``pvesh``. It creates or
    updates a webhook endpoint with a JSON body compatible with infra_tools'
    notification payload shape, then creates or updates a matcher that routes
    matching severities to that endpoint. No local hook script is installed.
    """
    config = _validate_webhook_config(
        url=url,
        endpoint_name=endpoint_name,
        matcher_name=matcher_name,
        severities=severities,
    )
    commands = _build_webhook_notification_commands(config)
    redacted = _build_webhook_notification_commands(
        ProxmoxWebhookNotificationConfig(
            endpoint_name=config.endpoint_name,
            matcher_name=config.matcher_name,
            url=_redact_url(config.url),
            severities=config.severities,
        )
    )
    for command, display in zip(commands, redacted):
        result = _run_on_host(host, command, dry_run=dry_run, log_cmd=display)
        if result.returncode != 0:
            raise ProxmoxManageError(
                f"Proxmox notification command failed on {host.address}: "
                f"{(result.stderr or result.stdout or '').strip() or 'unknown error'}"
            )
    if send_test:
        send_webhook_test_notification(
            host,
            config.endpoint_name,
            dry_run=dry_run,
        )
    return config


def send_webhook_test_notification(
    host: ProxmoxHost,
    endpoint_name: str = DEFAULT_NOTIFICATION_ENDPOINT,
    *,
    dry_run: bool = False,
) -> None:
    """Ask Proxmox to send a native test notification to a webhook endpoint."""
    _validate_notification_id(endpoint_name, "endpoint name")
    cmd = shlex.join([
        "pvesh", "create", f"/cluster/notifications/targets/{endpoint_name}/test",
    ])
    result = _run_on_host(host, cmd, dry_run=dry_run)
    if result.returncode != 0:
        raise ProxmoxManageError(
            f"Proxmox test notification failed on {host.address}: "
            f"{(result.stderr or result.stdout or '').strip() or 'unknown error'}"
        )


def _validate_webhook_config(
    *,
    url: str,
    endpoint_name: str,
    matcher_name: str,
    severities: Optional[list[str]],
) -> ProxmoxWebhookNotificationConfig:
    _validate_notification_id(endpoint_name, "endpoint name")
    _validate_notification_id(matcher_name, "matcher name")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"Invalid webhook URL: {url}")

    selected = severities or list(DEFAULT_NOTIFICATION_SEVERITIES)
    allowed = set(DEFAULT_NOTIFICATION_SEVERITIES)
    bad = [sev for sev in selected if sev not in allowed]
    if bad:
        raise ValueError(f"Invalid Proxmox notification severities: {', '.join(bad)}")

    return ProxmoxWebhookNotificationConfig(
        endpoint_name=endpoint_name,
        matcher_name=matcher_name,
        url=url,
        severities=selected,
    )


def _validate_notification_id(value: str, label: str) -> None:
    if not _NOTIFICATION_ID_RE.match(value):
        raise ValueError(
            f"Invalid Proxmox notification {label}: {value!r}. "
            "Use a letter followed by letters, numbers, '_' or '-' (max 63 chars)."
        )


def _build_webhook_notification_commands(
    config: ProxmoxWebhookNotificationConfig,
) -> list[str]:
    endpoint_path = f"/cluster/notifications/endpoints/webhook/{config.endpoint_name}"
    matcher_path = f"/cluster/notifications/matchers/{config.matcher_name}"

    endpoint_create = shlex.join([
        "pvesh", "create", "/cluster/notifications/endpoints/webhook",
        "--name", config.endpoint_name,
        "--url", config.url,
        "--method", "post",
        "--header", _pve_property("Content-Type", "application/json"),
        "--body", _base64(_webhook_body_template()),
        "--comment", "infra_tools Proxmox system notifications",
    ])
    endpoint_set = shlex.join([
        "pvesh", "set", endpoint_path,
        "--url", config.url,
        "--method", "post",
        "--header", _pve_property("Content-Type", "application/json"),
        "--body", _base64(_webhook_body_template()),
        "--comment", "infra_tools Proxmox system notifications",
    ])

    matcher_args = [
        "--target", config.endpoint_name,
        "--comment", "Route Proxmox system notifications to infra_tools",
    ]
    for severity in config.severities:
        matcher_args.extend(["--match-severity", severity])
    matcher_create = shlex.join([
        "pvesh", "create", "/cluster/notifications/matchers",
        "--name", config.matcher_name,
        *matcher_args,
    ])
    matcher_set = shlex.join([
        "pvesh", "set", matcher_path,
        *matcher_args,
    ])

    return [
        _upsert_pvesh_command(endpoint_path, endpoint_set, endpoint_create),
        _upsert_pvesh_command(matcher_path, matcher_set, matcher_create),
    ]


def _upsert_pvesh_command(path: str, set_cmd: str, create_cmd: str) -> str:
    return (
        f"if pvesh get {shlex.quote(path)} >/dev/null 2>&1; "
        f"then {set_cmd}; else {create_cmd}; fi"
    )


def _webhook_body_template() -> str:
    """Return Proxmox Handlebars JSON body for infra_tools-style webhooks."""
    return """{
  "subject": "Proxmox: {{ escape title }}",
  "job": "proxmox",
  "status": "{{ severity }}",
  "message": "{{ escape message }}",
  "details": "severity={{ severity }}\\ntype={{ fields.type }}\\nfields={{ json fields }}",
  "hostname": "{{ fields.hostname }}"
}"""


def _pve_property(name: str, value: str) -> str:
    return f"name={name},value={_base64(value)}"


def _base64(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _redact_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if not parsed.netloc:
        return "<redacted-url>"
    return urllib.parse.urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        "",
        "<redacted-query>" if parsed.query else "",
        "",
    ))


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
