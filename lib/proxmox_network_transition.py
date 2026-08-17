"""Reconcile Proxmox guest metadata during a verified network handoff."""

from __future__ import annotations

import ipaddress
import re
import shlex
import socket
from dataclasses import dataclass
from typing import Optional

from lib.config import SetupConfig
from lib.proxmox_guest import _ssh_opts, _ssh_run
from lib.types import StrList


@dataclass(frozen=True)
class ProxmoxNetworkPlan:
    """A reversible Proxmox guest network metadata update."""

    node: str
    user: str
    ssh_opts: StrList
    guest_kind: str
    vmid: int
    option: str
    previous_value: str
    requested_value: str


def _literal_ip(value: str) -> Optional[str]:
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def _resolved_host_ips(value: str) -> set[str]:
    literal = _literal_ip(value)
    if literal:
        return {literal}
    try:
        return {
            str(ipaddress.ip_address(sockaddr[0]))
            for _family, _type, _proto, _canonname, sockaddr in socket.getaddrinfo(
                value,
                None,
                type=socket.SOCK_STREAM,
            )
        }
    except (OSError, ValueError):
        return set()


def _config_value(output: str, key: str) -> Optional[str]:
    prefix = f"{key}:"
    for line in output.splitlines():
        if line.startswith(prefix):
            return line.split(":", 1)[1].strip()
    return None


def _assignment_ip(value: str, key: str) -> Optional[str]:
    match = re.search(rf"(?:^|,){re.escape(key)}=([^,\s]+)", value)
    if not match or match.group(1) in {"dhcp", "auto"}:
        return None
    return _literal_ip(match.group(1).split("/", 1)[0])


def _assignments_equal(left: str, right: str) -> bool:
    def fields(value: str) -> Optional[dict[str, str]]:
        parsed: dict[str, str] = {}
        for field in value.split(","):
            key, separator, field_value = field.partition("=")
            if not separator or not key or key in parsed:
                return None
            parsed[key] = field_value
        return parsed

    left_fields = fields(left)
    right_fields = fields(right)
    return (
        left == right
        if left_fields is None or right_fields is None
        else left_fields == right_fields
    )


def _replace_assignment_fields(
    current: str,
    replacements: list[tuple[str, Optional[str]]],
) -> str:
    pending = dict(replacements)
    fields: list[str] = []
    for field in current.split(","):
        key = field.split("=", 1)[0]
        if key not in pending:
            fields.append(field)
            continue
        value = pending.pop(key)
        if value is not None:
            fields.append(f"{key}={value}")
    for key, value in replacements:
        if key in pending and value is not None:
            fields.append(f"{key}={value}")
    return ",".join(fields)


def _requested_assignment(current: str, config: SetupConfig) -> str:
    replacements: list[tuple[str, Optional[str]]] = []
    if config.static_ipv4:
        replacements.extend(
            [
                ("ip", str(ipaddress.ip_interface(config.static_ipv4))),
                ("gw", config.network_gateway4),
            ]
        )
    if config.static_ipv6:
        replacements.extend(
            [
                ("ip6", str(ipaddress.ip_interface(config.static_ipv6))),
                ("gw6", config.network_gateway6),
            ]
        )
    return _replace_assignment_fields(current, replacements)


def _guest_kind(config: SetupConfig) -> tuple[str, str, str, str]:
    if config.machine_type == "vm":
        return "VM", "qm", "ipconfig0", "name"
    return "LXC", "pct", "net0", "hostname"


def prepare_proxmox_network_plan(
    config: SetupConfig,
    previous_host: str,
) -> Optional[ProxmoxNetworkPlan]:
    """Read and validate the exact Proxmox guest update without changing it."""

    if not config.hosted_node:
        return None

    guest_kind, command, option, name_key = _guest_kind(config)
    node = str(config.hosted_node)
    user = config.hosted_user
    ssh_opts = _ssh_opts(config.hosted_key)
    list_result = _ssh_run(node, user, ssh_opts, f"{command} list", dry_run=False)
    if list_result.returncode != 0:
        raise RuntimeError(
            f"Could not list {guest_kind} guests on Proxmox node {node}: "
            f"{(list_result.stderr or list_result.stdout or '').strip() or 'command failed'}"
        )

    previous_ips = _resolved_host_ips(previous_host)
    requested_ips = {
        str(ipaddress.ip_interface(value).ip)
        for value in (config.static_ipv4, config.static_ipv6)
        if value
    }
    expected_names = {
        value
        for value in (config.system_hostname, config.friendly_name)
        if value
    }
    matches: list[tuple[int, str]] = []
    for line in (list_result.stdout or "").splitlines()[1:]:
        fields = line.split()
        if not fields:
            continue
        try:
            vmid = int(fields[0])
        except ValueError:
            continue
        config_result = _ssh_run(
            node,
            user,
            ssh_opts,
            f"{command} config {vmid}",
            dry_run=False,
        )
        if config_result.returncode != 0:
            detail = (
                config_result.stderr
                or config_result.stdout
                or "command failed"
            ).strip()
            raise RuntimeError(
                f"Could not inspect Proxmox {guest_kind} {vmid} while checking "
                f"network conflicts: {detail}"
            )
        assignment = _config_value(config_result.stdout or "", option)
        if assignment is None:
            continue
        assignment_ips = {
            value
            for value in (
                _assignment_ip(assignment, "ip"),
                _assignment_ip(assignment, "ip6"),
            )
            if value
        }
        guest_name = _config_value(config_result.stdout or "", name_key)
        identity_match = bool(
            assignment_ips.intersection(previous_ips)
            or assignment_ips.intersection(requested_ips)
            or (guest_name and guest_name in expected_names)
        )
        if identity_match:
            matches.append((vmid, assignment))

    if not matches:
        raise RuntimeError(
            f"Could not identify the existing Proxmox {guest_kind} for {previous_host}; "
            "no guest network metadata was changed"
        )
    if len(matches) > 1:
        vmids = ", ".join(str(vmid) for vmid, _value in matches)
        raise RuntimeError(
            f"Multiple Proxmox {guest_kind} guests match the network transition "
            f"({vmids}); no guest network metadata was changed"
        )

    vmid, previous_value = matches[0]
    return ProxmoxNetworkPlan(
        node=node,
        user=user,
        ssh_opts=ssh_opts,
        guest_kind=guest_kind,
        vmid=vmid,
        option=option,
        previous_value=previous_value,
        requested_value=_requested_assignment(previous_value, config),
    )


def _read_plan_value(plan: ProxmoxNetworkPlan) -> str:
    command = "qm" if plan.guest_kind == "VM" else "pct"
    result = _ssh_run(
        plan.node,
        plan.user,
        plan.ssh_opts,
        f"{command} config {plan.vmid}",
        dry_run=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Could not verify Proxmox {plan.guest_kind} {plan.vmid} network metadata: "
            f"{(result.stderr or result.stdout or '').strip() or 'command failed'}"
        )
    value = _config_value(result.stdout or "", plan.option)
    if value is None:
        raise RuntimeError(
            f"Proxmox {plan.guest_kind} {plan.vmid} no longer has {plan.option}"
        )
    return value


def _apply_plan_value(
    plan: ProxmoxNetworkPlan,
    value: str,
    *,
    expected_current: Optional[str] = None,
) -> None:
    command = "qm" if plan.guest_kind == "VM" else "pct"
    if expected_current is not None:
        current = _read_plan_value(plan)
        if not _assignments_equal(current, expected_current):
            raise RuntimeError(
                f"Proxmox {plan.guest_kind} {plan.vmid} network metadata changed "
                "after preflight; refusing to overwrite it"
            )
    result = _ssh_run(
        plan.node,
        plan.user,
        plan.ssh_opts,
        f"{command} set {plan.vmid} --{plan.option} {shlex.quote(value)}",
        dry_run=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Could not update Proxmox {plan.guest_kind} {plan.vmid} network metadata: "
            f"{(result.stderr or result.stdout or '').strip() or 'command failed'}"
        )
    stored = _read_plan_value(plan)
    if not _assignments_equal(stored, value):
        raise RuntimeError(
            f"Proxmox {plan.guest_kind} {plan.vmid} did not retain the requested "
            f"{plan.option} value"
        )


def apply_proxmox_network_plan(plan: Optional[ProxmoxNetworkPlan]) -> None:
    """Apply a preflighted guest metadata update, if one is needed."""

    if plan is None or plan.requested_value == plan.previous_value:
        return
    _apply_plan_value(
        plan,
        plan.requested_value,
        expected_current=plan.previous_value,
    )
    print(
        f"  ✓ Proxmox {plan.guest_kind} {plan.vmid} network metadata updated on {plan.node}"
    )


def rollback_proxmox_network_plan(plan: Optional[ProxmoxNetworkPlan]) -> None:
    """Best-effort restoration after a post-update accessibility failure."""

    if plan is None or plan.requested_value == plan.previous_value:
        return
    try:
        current = _read_plan_value(plan)
        if _assignments_equal(current, plan.previous_value):
            return
        if not _assignments_equal(current, plan.requested_value):
            print(
                f"  ⚠ Refusing to roll back Proxmox {plan.guest_kind} {plan.vmid}; "
                "its network metadata changed concurrently"
            )
            return
        _apply_plan_value(
            plan,
            plan.previous_value,
            expected_current=plan.requested_value,
        )
        print(f"  ✓ Restored Proxmox {plan.guest_kind} {plan.vmid} network metadata")
    except RuntimeError as exc:
        print(f"  ⚠ Proxmox network metadata rollback failed: {exc}")
