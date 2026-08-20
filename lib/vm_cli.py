"""Provider-neutral virtual-machine command surface."""

from __future__ import annotations

import argparse
import json
from typing import Optional

from lib.proxmox_backup import BackupInfo, ProxmoxBackupError, list_backups
from lib.proxmox_hosts import ProxmoxHost, find_proxmox_host
from lib.proxmox_manage import (
    HealthReport,
    ProxmoxManageError,
    SnapshotInfo,
    get_container_config,
    get_container_status,
    health_check,
    list_containers,
    list_snapshots,
)
from lib.vm_models import VMHealth, VMRecord, envelope


def add_vm_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Register the provider-neutral ``vm`` command tree."""

    parser = subparsers.add_parser(
        "vm",
        help="Inspect and manage virtual machines through a provider-neutral API",
        description=(
            "Provider-neutral guest operations. The first provider is Proxmox; "
            "provider-specific host administration remains under 'proxmox'."
        ),
    )
    parser.add_argument(
        "--workspace",
        help="Workspace root for saved setups, credentials, known_hosts, and history",
    )
    commands = parser.add_subparsers(dest="vm_command", help="VM subcommand")

    list_parser = commands.add_parser("list", aliases=["ls"], help="List guests")
    list_parser.add_argument("host", help="Registered provider host")
    list_parser.add_argument("--json", action="store_true", help="Output JSON")
    list_parser.set_defaults(_handler=_cmd_list)

    show_parser = commands.add_parser("show", help="Show one guest and its configuration")
    show_parser.add_argument("host", help="Registered provider host")
    show_parser.add_argument("vmid", type=_positive_id, metavar="ID")
    show_parser.add_argument("--json", action="store_true", help="Output JSON")
    show_parser.set_defaults(_handler=_cmd_show)

    health_parser = commands.add_parser("health", help="Check one guest")
    health_parser.add_argument("host", help="Registered provider host")
    health_parser.add_argument("vmid", type=_positive_id, metavar="ID")
    health_parser.add_argument(
        "--no-ssh",
        action="store_true",
        help="Skip the guest SSH port probe",
    )
    health_parser.add_argument("--json", action="store_true", help="Output JSON")
    health_parser.set_defaults(_handler=_cmd_health)

    snapshot_parser = commands.add_parser("snapshot", help="Inspect guest snapshots")
    snapshot_commands = snapshot_parser.add_subparsers(
        dest="vm_snapshot_command", help="Snapshot subcommand"
    )
    snapshot_list = snapshot_commands.add_parser("list", help="List snapshots")
    snapshot_list.add_argument("host", help="Registered provider host")
    snapshot_list.add_argument("vmid", type=_positive_id, metavar="ID")
    snapshot_list.add_argument("--json", action="store_true", help="Output JSON")
    snapshot_list.set_defaults(_handler=_cmd_snapshot_list)

    backup_parser = commands.add_parser("backup", help="Inspect guest backups")
    backup_commands = backup_parser.add_subparsers(
        dest="vm_backup_command", help="Backup subcommand"
    )
    backup_list = backup_commands.add_parser("list", help="List backups")
    backup_list.add_argument("host", help="Registered provider host")
    backup_list.add_argument("vmid", type=_positive_id, metavar="ID")
    backup_list.add_argument("--json", action="store_true", help="Output JSON")
    backup_list.set_defaults(_handler=_cmd_backup_list)

    return parser


def _positive_id(value: str) -> int:
    try:
        vmid = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("ID must be a positive integer") from exc
    if vmid < 1:
        raise argparse.ArgumentTypeError("ID must be a positive integer")
    return vmid


def _resolve_host(target: str, workspace: Optional[str]) -> ProxmoxHost:
    host = find_proxmox_host(target, workspace)
    if host is None:
        raise ValueError(
            f"No registered provider host matching '{target}'. "
            "Use 'infra-tools proxmox add' first."
        )
    return host


def _print_result(payload: dict, *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))


def _find_guest(host: ProxmoxHost, vmid: int):
    for guest in list_containers(host):
        if guest.vmid == vmid:
            return guest
    raise ValueError(f"No guest with ID {vmid} found on {host.name}")


def _cmd_list(args: argparse.Namespace, workspace: Optional[str]) -> int:
    host = _resolve_host(args.host, workspace)
    records = [
        VMRecord(
            id=str(guest.vmid),
            kind=guest.guest_type,
            name=guest.name,
            state=guest.status,
            lock=guest.lock,
        ).to_dict()
        for guest in list_containers(host)
    ]
    payload = envelope(
        provider=host.provider,
        host=host.name,
        operation="list",
        resources=records,
    )
    _print_result(payload, json_output=args.json)
    if not args.json:
        print(f"Provider: {host.provider}  Host: {host.name}")
        if records:
            for record in records:
                print(
                    f"{record['id']:>6}  {record['kind']:<3}  "
                    f"{record['state']:<10}  {record['name']}"
                )
        else:
            print("No guests found.")
    return 0


def _cmd_show(args: argparse.Namespace, workspace: Optional[str]) -> int:
    host = _resolve_host(args.host, workspace)
    guest = _find_guest(host, args.vmid)
    config = get_container_config(host, args.vmid)
    resource = VMRecord(
        id=str(guest.vmid),
        kind=guest.guest_type,
        name=guest.name,
        state=get_container_status(host, args.vmid),
        lock=guest.lock,
    ).to_dict()
    resource["config"] = config
    payload = envelope(
        provider=host.provider,
        host=host.name,
        operation="show",
        resources=[resource],
    )
    _print_result(payload, json_output=args.json)
    if not args.json:
        print(f"Provider: {host.provider}  Host: {host.name}")
        print(f"ID: {resource['id']}")
        print(f"Kind: {resource['kind']}")
        print(f"Name: {resource['name']}")
        print(f"State: {resource['state']}")
        for key, value in config.items():
            print(f"{key}: {value}")
    return 0


def _health_model(report: HealthReport) -> VMHealth:
    return VMHealth(
        id=str(report.vmid),
        kind=report.guest_type,
        state=report.status,
        healthy=report.healthy,
        address=report.ip,
        pingable=report.pingable,
        ssh_open=report.ssh_open,
        notes=list(report.notes),
    )


def _cmd_health(args: argparse.Namespace, workspace: Optional[str]) -> int:
    host = _resolve_host(args.host, workspace)
    report = health_check(host, args.vmid, probe_ssh=not args.no_ssh)
    health = _health_model(report)
    payload = envelope(
        provider=host.provider,
        host=host.name,
        operation="health",
        resources=[health.to_dict()],
    )
    _print_result(payload, json_output=args.json)
    if not args.json:
        print(f"{host.name}/{args.vmid}: {'healthy' if health.healthy else 'unhealthy'}")
        for note in health.notes:
            print(f"  - {note}")
    return 0 if health.healthy else 1


def _snapshot_dict(snapshot: SnapshotInfo) -> dict:
    return {
        "name": snapshot.name,
        "description": snapshot.description,
        "current": snapshot.is_current,
    }


def _cmd_snapshot_list(args: argparse.Namespace, workspace: Optional[str]) -> int:
    host = _resolve_host(args.host, workspace)
    snapshots = [_snapshot_dict(item) for item in list_snapshots(host, args.vmid)]
    payload = envelope(
        provider=host.provider,
        host=host.name,
        operation="snapshot.list",
        resources=snapshots,
    )
    _print_result(payload, json_output=args.json)
    if not args.json:
        for snapshot in snapshots:
            marker = "*" if snapshot["current"] else " "
            print(f"{marker} {snapshot['name']}  {snapshot['description']}")
    return 0


def _backup_dict(backup: BackupInfo) -> dict:
    return {
        "volume": backup.volid,
        "storage": backup.storage,
        "filename": backup.filename,
        "vmid": backup.vmid,
        "size": backup.size,
        "created": backup.ctime,
        "format": backup.format,
        "notes": backup.notes,
    }


def _cmd_backup_list(args: argparse.Namespace, workspace: Optional[str]) -> int:
    host = _resolve_host(args.host, workspace)
    backups = [_backup_dict(item) for item in list_backups(host, args.vmid)]
    payload = envelope(
        provider=host.provider,
        host=host.name,
        operation="backup.list",
        resources=backups,
    )
    _print_result(payload, json_output=args.json)
    if not args.json:
        for backup in backups:
            print(f"{backup['storage']}: {backup['filename']} ({backup['size']} bytes)")
    return 0


def run_vm_command(args: argparse.Namespace) -> int:
    """Dispatch a parsed ``vm`` command."""

    handler = getattr(args, "_handler", None)
    if handler is None:
        print("Use 'infra-tools vm --help' for available commands.")
        return 0
    workspace = getattr(args, "workspace", None)
    try:
        return handler(args, workspace)
    except (ProxmoxBackupError, ProxmoxManageError, ValueError) as exc:
        print(f"Error: {exc}")
        return 1


__all__ = ["add_vm_subparser", "run_vm_command"]
