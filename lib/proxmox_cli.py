#!/usr/bin/env python3
"""CLI surface for ``infra_tools.py proxmox`` subcommands.

Splits parser construction and command dispatch out of ``infra_tools.py`` so
the management surface can grow independently of the setup/patch flow.
"""

from __future__ import annotations

import argparse
from typing import Optional

from lib.proxmox_hosts import (
    ProxmoxHost,
    add_proxmox_host,
    find_proxmox_host,
    load_proxmox_hosts,
    remove_proxmox_host,
)
from lib.proxmox_manage import (
    DEFAULT_NOTIFICATION_ENDPOINT,
    DEFAULT_NOTIFICATION_MATCHER,
    DEFAULT_NOTIFICATION_SEVERITIES,
    ProxmoxManageError,
    destroy_container,
    get_container_status,
    health_check,
    install_webhook_notifications,
    list_containers,
    send_webhook_test_notification,
    start_container,
    stop_container,
)
from lib.proxmox_shell import ProxmoxShell, run_proxmox_shell


def add_proxmox_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Register the ``proxmox`` command tree on the main argparse subparsers."""
    parser = subparsers.add_parser(
        "proxmox",
        help="Manage Proxmox hosts and the containers running on them",
        description=(
            "Manage Proxmox host registrations and the LXC containers "
            "running on them. Run with no subcommand to enter the "
            "interactive shell."
        ),
    )
    parser.add_argument(
        "--workspace",
        help="Workspace root for saved setups, credentials, known_hosts, and history",
    )

    sub = parser.add_subparsers(dest="proxmox_command", help="Proxmox subcommand")

    shell = sub.add_parser("shell", help="Start the interactive Proxmox shell")
    shell.set_defaults(_handler=_cmd_shell)

    hosts = sub.add_parser("hosts", help="List registered Proxmox hosts")
    hosts.set_defaults(_handler=_cmd_hosts_list)

    add = sub.add_parser("add", help="Register a Proxmox host")
    add.add_argument("name", help="Short name for the host")
    add.add_argument("address", help="IP or hostname for the Proxmox node")
    add.add_argument("-u", "--user", default="root", help="SSH user (default: root)")
    add.add_argument("-k", "--key", dest="ssh_key", help="SSH private key path")
    add.add_argument("--description", help="Optional human-readable description")
    add.add_argument(
        "--default-storage",
        help="Optional default storage pool to suggest when creating containers",
    )
    add.add_argument(
        "--default-bridge",
        help="Optional default network bridge to suggest when creating containers",
    )
    add.add_argument(
        "--replace",
        action="store_true",
        help="Replace an existing host with the same name",
    )
    add.set_defaults(_handler=_cmd_hosts_add)

    rm = sub.add_parser("remove", aliases=["rm"], help="Remove a registered Proxmox host")
    rm.add_argument("target", help="Host name or address to remove")
    rm.set_defaults(_handler=_cmd_hosts_remove)

    ls = sub.add_parser("ls", aliases=["list"], help="List containers on a host")
    ls.add_argument("host", help="Registered host name or address")
    ls.set_defaults(_handler=_cmd_containers_ls)

    status = sub.add_parser("status", help="Show container status")
    status.add_argument("host", help="Registered host name or address")
    status.add_argument("vmid", type=int, help="Container VMID")
    status.set_defaults(_handler=_cmd_status)

    start = sub.add_parser("start", help="Start a container")
    start.add_argument("host", help="Registered host name or address")
    start.add_argument("vmid", type=int, help="Container VMID")
    start.set_defaults(_handler=_cmd_start)

    stop = sub.add_parser("stop", help="Shutdown (or force-stop) a container")
    stop.add_argument("host", help="Registered host name or address")
    stop.add_argument("vmid", type=int, help="Container VMID")
    stop.add_argument(
        "--force", action="store_true", help="Use 'pct stop' instead of graceful shutdown"
    )
    stop.set_defaults(_handler=_cmd_stop)

    destroy = sub.add_parser("destroy", help="Destroy a container (asks for confirmation)")
    destroy.add_argument("host", help="Registered host name or address")
    destroy.add_argument("vmid", type=int, help="Container VMID")
    destroy.add_argument(
        "-y", "--yes", action="store_true", help="Skip the confirmation prompt"
    )
    destroy.add_argument(
        "--force", action="store_true", help="Use 'pct stop' before destroy if running"
    )
    destroy.set_defaults(_handler=_cmd_destroy)

    health = sub.add_parser("health", help="Run a health check against a container")
    health.add_argument("host", help="Registered host name or address")
    health.add_argument("vmid", type=int, help="Container VMID")
    health.add_argument(
        "--no-ssh", action="store_true", help="Skip the SSH:22 reachability probe"
    )
    health.set_defaults(_handler=_cmd_health)

    notifications = sub.add_parser(
        "notifications",
        help="Configure native Proxmox notification targets",
        description=(
            "Configure Proxmox's native notification system to send system "
            "notifications to an infra_tools-compatible webhook endpoint."
        ),
    )
    notification_sub = notifications.add_subparsers(
        dest="notification_command",
        help="Notification subcommand",
    )
    notifications.set_defaults(_handler=_cmd_notifications_missing)

    install = notification_sub.add_parser(
        "install-webhook",
        help="Create/update a native Proxmox webhook endpoint and matcher",
    )
    install.add_argument("host", help="Registered host name or address")
    install.add_argument("url", help="Webhook URL to receive Proxmox notifications")
    install.add_argument(
        "--endpoint-name",
        default=DEFAULT_NOTIFICATION_ENDPOINT,
        help=f"Proxmox webhook endpoint name (default: {DEFAULT_NOTIFICATION_ENDPOINT})",
    )
    install.add_argument(
        "--matcher-name",
        default=DEFAULT_NOTIFICATION_MATCHER,
        help=f"Proxmox matcher name (default: {DEFAULT_NOTIFICATION_MATCHER})",
    )
    install.add_argument(
        "--severity",
        action="append",
        choices=DEFAULT_NOTIFICATION_SEVERITIES,
        help=(
            "Severity to route to the webhook. Repeatable. "
            f"Default: {', '.join(DEFAULT_NOTIFICATION_SEVERITIES)}"
        ),
    )
    install.add_argument(
        "--send-test",
        action="store_true",
        help="Ask Proxmox to send a test notification after configuring the endpoint",
    )
    install.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the remote pvesh commands without executing them",
    )
    install.set_defaults(_handler=_cmd_notifications_install_webhook)

    test = notification_sub.add_parser(
        "test-webhook",
        help="Ask Proxmox to send a native test notification to an endpoint",
    )
    test.add_argument("host", help="Registered host name or address")
    test.add_argument(
        "--endpoint-name",
        default=DEFAULT_NOTIFICATION_ENDPOINT,
        help=f"Proxmox webhook endpoint name (default: {DEFAULT_NOTIFICATION_ENDPOINT})",
    )
    test.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the remote pvesh command without executing it",
    )
    test.set_defaults(_handler=_cmd_notifications_test_webhook)

    return parser


def run_proxmox_command(args: argparse.Namespace) -> int:
    """Dispatch a parsed ``proxmox`` argparse namespace."""
    workspace = getattr(args, "workspace", None)
    handler = getattr(args, "_handler", None)
    if handler is None:
        return run_proxmox_shell(workspace)
    try:
        return handler(args, workspace)
    except (ProxmoxManageError, ValueError) as exc:
        print(f"Error: {exc}")
        return 1


# ---------------------------------------------------------------------------
# Handlers


def _resolve_host(target: str, workspace: Optional[str]) -> ProxmoxHost:
    host = find_proxmox_host(target, workspace)
    if not host:
        raise ValueError(
            f"No registered Proxmox host matching '{target}'. "
            f"Use 'infra_tools.py proxmox add' first."
        )
    return host


def _cmd_shell(args: argparse.Namespace, workspace: Optional[str]) -> int:
    return run_proxmox_shell(workspace)


def _cmd_hosts_list(args: argparse.Namespace, workspace: Optional[str]) -> int:
    hosts = load_proxmox_hosts(workspace)
    if not hosts:
        print("No Proxmox hosts registered.")
        return 0
    print(f"{'NAME':<20} {'ADDRESS':<25} {'USER':<12} DESCRIPTION")
    print("-" * 70)
    for host in hosts:
        print(
            f"{host.name:<20} {host.address:<25} {host.user:<12} "
            f"{host.description or ''}"
        )
    return 0


def _cmd_hosts_add(args: argparse.Namespace, workspace: Optional[str]) -> int:
    host = ProxmoxHost(
        name=args.name,
        address=args.address,
        user=args.user,
        ssh_key=args.ssh_key,
        description=args.description,
        default_storage=args.default_storage,
        default_bridge=args.default_bridge,
    )
    add_proxmox_host(host, workspace, replace=args.replace)
    print(f"Registered Proxmox host '{host.name}' ({host.address}).")
    return 0


def _cmd_hosts_remove(args: argparse.Namespace, workspace: Optional[str]) -> int:
    if remove_proxmox_host(args.target, workspace):
        print(f"Removed Proxmox host '{args.target}'.")
        return 0
    print(f"No Proxmox host matching '{args.target}'.")
    return 1


def _cmd_containers_ls(args: argparse.Namespace, workspace: Optional[str]) -> int:
    host = _resolve_host(args.host, workspace)
    rows = list_containers(host)
    if not rows:
        print(f"No containers on {host.name} ({host.address}).")
        return 0
    print(f"Containers on {host.name} ({host.address}):")
    print(f"  {'VMID':>6} {'STATUS':<10} {'LOCK':<10} NAME")
    for row in rows:
        print(
            f"  {row.vmid:>6} {row.status:<10} {(row.lock or '-'):<10} "
            f"{row.name or '-'}"
        )
    return 0


def _cmd_status(args: argparse.Namespace, workspace: Optional[str]) -> int:
    host = _resolve_host(args.host, workspace)
    print(get_container_status(host, args.vmid))
    return 0


def _cmd_start(args: argparse.Namespace, workspace: Optional[str]) -> int:
    host = _resolve_host(args.host, workspace)
    start_container(host, args.vmid)
    print(f"Started container {args.vmid} on {host.name}.")
    return 0


def _cmd_stop(args: argparse.Namespace, workspace: Optional[str]) -> int:
    host = _resolve_host(args.host, workspace)
    stop_container(host, args.vmid, force=args.force)
    verb = "Stopped" if args.force else "Shut down"
    print(f"{verb} container {args.vmid} on {host.name}.")
    return 0


def _cmd_destroy(args: argparse.Namespace, workspace: Optional[str]) -> int:
    host = _resolve_host(args.host, workspace)
    if not args.yes:
        prompt = (
            f"Destroy container {args.vmid} on {host.name} ({host.address})? "
            f"Type 'yes' to confirm: "
        )
        try:
            response = input(prompt)
        except (EOFError, KeyboardInterrupt):
            print()
            print("Aborted.")
            return 1
        if response.strip().lower() != "yes":
            print("Aborted.")
            return 1
    destroy_container(host, args.vmid, force=args.force)
    print(f"Destroyed container {args.vmid} on {host.name}.")
    return 0


def _cmd_health(args: argparse.Namespace, workspace: Optional[str]) -> int:
    host = _resolve_host(args.host, workspace)
    report = health_check(host, args.vmid, probe_ssh=not args.no_ssh)
    print(f"VMID {report.vmid} on {host.name} ({host.address}):")
    print(f"  status:  {report.status}")
    print(f"  ip:      {report.ip or 'n/a'}")
    print(f"  ping:    {_tristate(report.pingable)}")
    print(f"  ssh:22:  {_tristate(report.ssh_open)}")
    print(f"  result:  {'HEALTHY' if report.healthy else 'UNHEALTHY'}")
    for note in report.notes:
        print(f"  note:    {note}")
    return 0 if report.healthy else 1


def _cmd_notifications_install_webhook(
    args: argparse.Namespace,
    workspace: Optional[str],
) -> int:
    host = _resolve_host(args.host, workspace)
    config = install_webhook_notifications(
        host,
        args.url,
        endpoint_name=args.endpoint_name,
        matcher_name=args.matcher_name,
        severities=args.severity,
        send_test=args.send_test,
        dry_run=args.dry_run,
    )
    prefix = "Would configure" if args.dry_run else "Configured"
    print(
        f"{prefix} Proxmox webhook notifications on {host.name} "
        f"using endpoint '{config.endpoint_name}' and matcher '{config.matcher_name}'."
    )
    return 0


def _cmd_notifications_missing(args: argparse.Namespace, workspace: Optional[str]) -> int:
    raise ValueError("Choose a notifications subcommand: install-webhook or test-webhook")


def _cmd_notifications_test_webhook(
    args: argparse.Namespace,
    workspace: Optional[str],
) -> int:
    host = _resolve_host(args.host, workspace)
    send_webhook_test_notification(
        host,
        args.endpoint_name,
        dry_run=args.dry_run,
    )
    prefix = "Would send" if args.dry_run else "Sent"
    print(f"{prefix} Proxmox test notification via endpoint '{args.endpoint_name}'.")
    return 0


def _tristate(value: Optional[bool]) -> str:
    if value is None:
        return "skipped"
    return "ok" if value else "fail"


__all__ = [
    "ProxmoxShell",
    "add_proxmox_subparser",
    "run_proxmox_command",
]
