#!/usr/bin/env python3
"""CLI surface for ``infra_tools.py proxmox`` subcommands.

Splits parser construction and command dispatch out of ``infra_tools.py`` so
the management surface can grow independently of the setup/patch flow.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from typing import Optional

from lib.proxmox_guest import probe_proxmox_host
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
    get_container_config,
    get_container_pending,
    get_container_status,
    health_check,
    install_webhook_notifications,
    list_containers,
    modify_container,
    reconfigure_container,
    resize_container_disk,
    send_webhook_test_notification,
    start_container,
    stop_container,
)
from lib.proxmox_shell import ProxmoxShell, run_proxmox_shell


def add_proxmox_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Register the ``proxmox`` command tree on the main argparse subparsers."""
    parser = subparsers.add_parser(
        "proxmox",
        help="Manage Proxmox hosts and the guests running on them",
        description=(
            "Manage Proxmox host registrations and the Proxmox guests "
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
        help="Optional default storage pool to suggest when creating guests",
    )
    add.add_argument(
        "--default-template-storage",
        help="Optional default LXC template storage pool to suggest when creating guests",
    )
    add.add_argument(
        "--default-bridge",
        help="Optional default network bridge to suggest when creating guests",
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

    probe = sub.add_parser(
        "probe",
        help="Probe a registered host for storage pools, bridges, and setup defaults",
    )
    probe.add_argument("host", help="Registered host name or address")
    probe.set_defaults(_handler=_cmd_probe)

    ls = sub.add_parser("ls", aliases=["list"], help="List guests on a host")
    ls.add_argument("host", help="Registered host name or address")
    ls.set_defaults(_handler=_cmd_containers_ls)

    status = sub.add_parser("status", help="Show guest status")
    status.add_argument("host", help="Registered host name or address")
    status.add_argument("vmid", type=int, help="Guest VMID")
    status.set_defaults(_handler=_cmd_status)

    start = sub.add_parser("start", help="Start a guest")
    start.add_argument("host", help="Registered host name or address")
    start.add_argument("vmid", type=int, help="Guest VMID")
    start.set_defaults(_handler=_cmd_start)

    stop = sub.add_parser("stop", help="Shutdown (or force-stop) a guest")
    stop.add_argument("host", help="Registered host name or address")
    stop.add_argument("vmid", type=int, help="Guest VMID")
    stop.add_argument(
        "--force", action="store_true", help="Use an immediate stop instead of graceful shutdown"
    )
    stop.set_defaults(_handler=_cmd_stop)

    destroy = sub.add_parser("destroy", help="Destroy a guest (asks for confirmation)")
    destroy.add_argument("host", help="Registered host name or address")
    destroy.add_argument("vmid", type=int, help="Guest VMID")
    destroy.add_argument(
        "-y", "--yes", action="store_true", help="Skip the confirmation prompt"
    )
    destroy.add_argument(
        "--force", action="store_true", help="Force-stop the guest before destroy if it is running"
    )
    destroy.set_defaults(_handler=_cmd_destroy)

    health = sub.add_parser("health", help="Run a health check against a guest")
    health.add_argument("host", help="Registered host name or address")
    health.add_argument("vmid", type=int, help="Guest VMID")
    health.add_argument(
        "--no-ssh", action="store_true", help="Skip the SSH:22 reachability probe"
    )
    health.set_defaults(_handler=_cmd_health)

    config_cmd = sub.add_parser("config", help="Show guest configuration")
    config_cmd.add_argument("host", help="Registered host name or address")
    config_cmd.add_argument("vmid", type=int, help="Guest VMID")
    config_cmd.add_argument(
        "--pending",
        action="store_true",
        help="Show pending (unapplied) configuration changes instead",
    )
    config_cmd.set_defaults(_handler=_cmd_config)

    reconfig = sub.add_parser(
        "reconfigure",
        help="Set arbitrary guest configuration options",
        description=(
            "Apply one or more pct/qm set options to a guest. "
            "Changes that affect a running guest may require a restart."
        ),
    )
    reconfig.add_argument("host", help="Registered host name or address")
    reconfig.add_argument("vmid", type=int, help="Guest VMID")
    reconfig.add_argument(
        "--set",
        action="append",
        dest="options",
        metavar="KEY=VALUE",
        help=(
            "Option to set, as key=value (e.g. --set hostname=mybox). "
            "Repeatable."
        ),
    )
    reconfig.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the remote pct/qm set command without executing it",
    )
    reconfig.set_defaults(_handler=_cmd_reconfigure)

    modify = sub.add_parser(
        "modify",
        help="Change CPU cores or memory allocation for a guest",
    )
    modify.add_argument("host", help="Registered host name or address")
    modify.add_argument("vmid", type=int, help="Guest VMID")
    modify.add_argument(
        "--cores",
        type=int,
        help="Number of vCPU cores",
    )
    modify.add_argument(
        "--memory",
        dest="memory",
        help=(
            "RAM allocation in MiB, or with a unit suffix: "
            "512M / 4G (e.g. --memory 4G)"
        ),
    )
    modify.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the remote pct/qm set command without executing it",
    )
    modify.set_defaults(_handler=_cmd_modify)

    resize = sub.add_parser(
        "resize-disk",
        help="Increase a guest disk volume size",
    )
    resize.add_argument("host", help="Registered host name or address")
    resize.add_argument("vmid", type=int, help="Guest VMID")
    resize.add_argument("volume", help="Volume name (e.g. rootfs)")
    resize.add_argument("size", help="New absolute size with unit (e.g. 20G)")
    resize.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the remote pct/qm resize command without executing it",
    )
    resize.set_defaults(_handler=_cmd_resize_disk)

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
    print(
        f"{'NAME':<20} {'ADDRESS':<25} {'USER':<12} "
        f"{'ROOT':<12} {'TEMPLATE':<12} {'BRIDGE':<10} DESCRIPTION"
    )
    print("-" * 110)
    for host in hosts:
        print(
            f"{host.name:<20} {host.address:<25} {host.user:<12} "
            f"{(host.default_storage or '-').ljust(12)}"
            f"{(host.default_template_storage or '-').ljust(12)}"
            f"{(host.default_bridge or '-').ljust(10)}"
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
        default_template_storage=args.default_template_storage,
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


def _cmd_probe(args: argparse.Namespace, workspace: Optional[str]) -> int:
    host = _resolve_host(args.host, workspace)
    facts = probe_proxmox_host(host.address, user=host.user, hosted_key=host.ssh_key)
    updated_host = replace(
        host,
        default_storage=host.default_storage or facts.default_root_storage,
        default_template_storage=(
            host.default_template_storage or facts.default_template_storage
        ),
        default_bridge=host.default_bridge or facts.default_bridge,
        facts=facts,
    )
    add_proxmox_host(updated_host, workspace, replace=True)

    print(f"Probed Proxmox host '{updated_host.name}' ({updated_host.address}).")
    print(f"  node:      {facts.node_name or '-'}")
    print(f"  root:      {updated_host.default_storage or '-'}")
    print(f"  template:  {updated_host.default_template_storage or '-'}")
    print(f"  bridge:    {updated_host.default_bridge or '-'}")
    print(f"  gateway:   {facts.gateway or '-'}")
    print(
        "  dns:       "
        + (", ".join(facts.nameservers) if facts.nameservers else "-")
    )
    print(
        "  bridges:   "
        + (", ".join(facts.bridges) if facts.bridges else "-")
    )
    if facts.storage_pools:
        print("  storage:")
        for pool in facts.storage_pools:
            content = ",".join(pool.content) if pool.content else "-"
            print(
                f"    {pool.name}: {pool.type or '-'} / "
                f"{pool.status or '-'} / {content}"
            )
    return 0


def _cmd_containers_ls(args: argparse.Namespace, workspace: Optional[str]) -> int:
    host = _resolve_host(args.host, workspace)
    rows = list_containers(host)
    if not rows:
        print(f"No guests on {host.name} ({host.address}).")
        return 0
    print(f"Guests on {host.name} ({host.address}):")
    print(f"  {'VMID':>6} {'TYPE':<6} {'STATUS':<10} {'LOCK':<10} NAME")
    for row in rows:
        print(
            f"  {row.vmid:>6} {row.guest_type:<6} {row.status:<10} {(row.lock or '-'):<10} "
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
    print(f"Started guest {args.vmid} on {host.name}.")
    return 0


def _cmd_stop(args: argparse.Namespace, workspace: Optional[str]) -> int:
    host = _resolve_host(args.host, workspace)
    stop_container(host, args.vmid, force=args.force)
    verb = "Stopped" if args.force else "Shut down"
    print(f"{verb} guest {args.vmid} on {host.name}.")
    return 0


def _cmd_destroy(args: argparse.Namespace, workspace: Optional[str]) -> int:
    host = _resolve_host(args.host, workspace)
    if not args.yes:
        prompt = (
            f"Destroy guest {args.vmid} on {host.name} ({host.address})? "
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
    print(f"Destroyed guest {args.vmid} on {host.name}.")
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


def _cmd_config(args: argparse.Namespace, workspace: Optional[str]) -> int:
    host = _resolve_host(args.host, workspace)
    if args.pending:
        data = get_container_pending(host, args.vmid)
        label = "Pending configuration"
    else:
        data = get_container_config(host, args.vmid)
        label = "Configuration"
    if not data:
        print(f"{label} for VMID {args.vmid} on {host.name}: (empty)")
        return 0
    print(f"{label} for VMID {args.vmid} on {host.name}:")
    for key, value in sorted(data.items()):
        print(f"  {key}: {value}")
    return 0


def _cmd_reconfigure(args: argparse.Namespace, workspace: Optional[str]) -> int:
    if not args.options:
        print("Error: At least one --set KEY=VALUE option is required.")
        return 1
    options: dict[str, str] = {}
    for item in args.options:
        if "=" not in item:
            print(f"Error: --set value must be KEY=VALUE, got: {item!r}")
            return 1
        key, _, value = item.partition("=")
        options[key] = value
    host = _resolve_host(args.host, workspace)
    reconfigure_container(host, args.vmid, options, dry_run=args.dry_run)
    prefix = "Would set" if args.dry_run else "Set"
    print(
        f"{prefix} {len(options)} option(s) on VMID {args.vmid} "
        f"on {host.name}."
    )
    return 0


def _parse_memory_mb(value: str) -> int:
    """Parse a memory string to MiB. Accepts plain integers or N[M|G] suffixes."""
    value = value.strip()
    if value.endswith(("G", "g")):
        try:
            return int(value[:-1]) * 1024
        except ValueError:
            pass
    if value.endswith(("M", "m")):
        try:
            return int(value[:-1])
        except ValueError:
            pass
    try:
        return int(value)
    except ValueError:
        raise ValueError(
            f"Invalid memory value: {value!r}. "
            "Use a plain integer (MiB), or add a suffix: 512M or 4G."
        )


def _cmd_modify(args: argparse.Namespace, workspace: Optional[str]) -> int:
    if args.cores is None and args.memory is None:
        print("Error: At least one of --cores or --memory is required.")
        return 1
    memory_mb: Optional[int] = None
    if args.memory is not None:
        try:
            memory_mb = _parse_memory_mb(args.memory)
        except ValueError as exc:
            print(f"Error: {exc}")
            return 1
    host = _resolve_host(args.host, workspace)
    modify_container(
        host,
        args.vmid,
        cores=args.cores,
        memory_mb=memory_mb,
        dry_run=args.dry_run,
    )
    parts = []
    if args.cores is not None:
        parts.append(f"cores={args.cores}")
    if memory_mb is not None:
        parts.append(f"memory={memory_mb}M")
    prefix = "Would modify" if args.dry_run else "Modified"
    print(
        f"{prefix} VMID {args.vmid} on {host.name}: {', '.join(parts)}."
    )
    return 0


def _cmd_resize_disk(args: argparse.Namespace, workspace: Optional[str]) -> int:
    host = _resolve_host(args.host, workspace)
    resize_container_disk(
        host, args.vmid, args.volume, args.size, dry_run=args.dry_run
    )
    prefix = "Would resize" if args.dry_run else "Resized"
    print(
        f"{prefix} {args.volume} on VMID {args.vmid} on {host.name} "
        f"to {args.size}."
    )
    return 0


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
