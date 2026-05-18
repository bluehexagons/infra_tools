"""CLI subparser registration and dispatch for sysadmin convenience commands."""

from __future__ import annotations

import argparse
from typing import Optional


# ---------------------------------------------------------------------------
# mount / umount
# ---------------------------------------------------------------------------

def _add_mount_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "mount",
        help="Mount a remote directory via sshfs",
        description=(
            "Mount a remote directory using sshfs. If the host has a saved "
            "infra_tools config, username/key are inherited automatically."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Example:\n  infra_tools.py mount myserver:/var/log /mnt/myserver-logs",
    )
    p.add_argument("remote", metavar="host:path", help="Remote host and path (e.g. myhost:/srv/data)")
    p.add_argument("local_path", metavar="local_path", help="Local mountpoint (created if absent)")
    p.add_argument("--username", "-u", help="SSH username (overrides saved config)")
    p.add_argument("--key", "-i", dest="ssh_key", help="SSH identity file (overrides saved config)")
    p.add_argument("--port", "-p", type=int, help="SSH port")
    p.add_argument("--ro", action="store_true", help="Mount read-only")
    p.set_defaults(_sysadmin_cmd="mount")


def _add_umount_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "umount",
        help="Unmount an sshfs mount",
        description="Unmount an sshfs mount by local path or by host name.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n  infra_tools.py umount /mnt/myserver-logs\n  infra_tools.py umount myhost",
    )
    p.add_argument(
        "target",
        help="Local mountpoint path or host name to unmount",
    )
    p.set_defaults(_sysadmin_cmd="umount")


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------

def _add_health_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "health",
        help="Show a health summary for a remote host",
        description=(
            "SSH into a host and print uptime, memory, disk usage, failed systemd "
            "units, recent journal errors, pending apt upgrades, and reboot status."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Example:\n  infra_tools.py health myserver",
    )
    p.add_argument("host", help="Remote host (IP or hostname)")
    p.add_argument("--username", "-u", help="SSH username (overrides saved config)")
    p.add_argument("--key", "-i", dest="ssh_key", help="SSH identity file (overrides saved config)")
    p.set_defaults(_sysadmin_cmd="health")


# ---------------------------------------------------------------------------
# ssh
# ---------------------------------------------------------------------------

def _add_ssh_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "ssh",
        help="Open an SSH session using saved config",
        description=(
            "Open an interactive SSH session (or run a remote command) using the "
            "username, key, and port from the saved infra_tools config for the host."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  infra_tools.py ssh myserver\n"
            "  infra_tools.py ssh myserver -- journalctl -f"
        ),
    )
    p.add_argument("host", help="Remote host (IP or hostname)")
    p.add_argument("--username", "-u", help="SSH username (overrides saved config)")
    p.add_argument("--key", "-i", dest="ssh_key", help="SSH identity file (overrides saved config)")
    p.add_argument("--port", "-p", type=int, help="SSH port")
    p.add_argument("remote_command", nargs=argparse.REMAINDER, help="Optional remote command")
    p.set_defaults(_sysadmin_cmd="ssh")


# ---------------------------------------------------------------------------
# push / pull
# ---------------------------------------------------------------------------

def _add_push_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "push",
        help="Push a local path to a remote host via rsync",
        description=(
            "Sync a local file or directory to a remote host using rsync over SSH. "
            "Username and key are inherited from the saved config when available."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  infra_tools.py push ./dist myserver:/var/www/app\n"
            "  infra_tools.py push ./data myserver:/backup/data --delete --dry-run"
        ),
    )
    p.add_argument("local_path", help="Local source path")
    p.add_argument("remote", metavar="host:path", help="Remote destination (e.g. myhost:/srv/app)")
    p.add_argument("--username", "-u", help="SSH username")
    p.add_argument("--key", "-i", dest="ssh_key", help="SSH identity file")
    p.add_argument("--port", "-p", type=int, help="SSH port")
    p.add_argument("--delete", action="store_true", help="Delete extraneous files from dest")
    p.add_argument("--dry-run", "-n", action="store_true", help="Show what would be transferred")
    p.set_defaults(_sysadmin_cmd="push")


def _add_pull_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "pull",
        help="Pull a remote path to local via rsync",
        description=(
            "Sync a remote file or directory to a local path using rsync over SSH."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  infra_tools.py pull myserver:/var/log ./logs\n"
            "  infra_tools.py pull myserver:/srv/data"
        ),
    )
    p.add_argument("remote", metavar="host:path", help="Remote source (e.g. myhost:/var/log)")
    p.add_argument("local_path", nargs="?", help="Local destination (defaults to ./<basename>)")
    p.add_argument("--username", "-u", help="SSH username")
    p.add_argument("--key", "-i", dest="ssh_key", help="SSH identity file")
    p.add_argument("--port", "-p", type=int, help="SSH port")
    p.add_argument("--dry-run", "-n", action="store_true", help="Show what would be transferred")
    p.set_defaults(_sysadmin_cmd="pull")


# ---------------------------------------------------------------------------
# key
# ---------------------------------------------------------------------------

def _add_key_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "key",
        help="Manage SSH keys on remote hosts",
        description="Install or rotate SSH public keys on remote hosts.",
    )
    key_sub = p.add_subparsers(dest="key_command", help="Key command")

    push_p = key_sub.add_parser(
        "push",
        help="Install local public key on a remote host",
        description=(
            "Append the local public key to ~/.ssh/authorized_keys on the remote "
            "host, creating the file with correct permissions if needed. Idempotent."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Example:\n  infra_tools.py key push myserver",
    )
    push_p.add_argument("host", help="Remote host (IP or hostname)")
    push_p.add_argument("--username", "-u", help="SSH username (overrides saved config)")
    push_p.add_argument("--key", "-i", dest="ssh_key", help="SSH key to authenticate with")
    push_p.add_argument(
        "--pubkey",
        default="~/.ssh/id_ed25519.pub",
        help="Public key to install (default: ~/.ssh/id_ed25519.pub)",
    )
    push_p.set_defaults(_sysadmin_cmd="key_push")

    p.set_defaults(_sysadmin_cmd="key")


# ---------------------------------------------------------------------------
# Public registration
# ---------------------------------------------------------------------------

def add_sysadmin_subparsers(subparsers: argparse._SubParsersAction) -> None:
    """Register all sysadmin convenience subcommands."""
    _add_mount_parser(subparsers)
    _add_umount_parser(subparsers)
    _add_health_parser(subparsers)
    _add_ssh_parser(subparsers)
    _add_push_parser(subparsers)
    _add_pull_parser(subparsers)
    _add_key_parser(subparsers)


def run_sysadmin_command(args: argparse.Namespace) -> int:
    """Dispatch a sysadmin subcommand."""
    cmd = getattr(args, "_sysadmin_cmd", None)

    if cmd == "mount":
        from lib.sysadmin_mount import run_mount
        return run_mount(
            args.remote,
            args.local_path,
            username=getattr(args, "username", None),
            ssh_key=getattr(args, "ssh_key", None),
            port=getattr(args, "port", None),
            read_only=args.ro,
        )

    if cmd == "umount":
        from lib.sysadmin_mount import run_umount
        return run_umount(args.target)

    if cmd == "health":
        from lib.sysadmin_health import run_health
        return run_health(
            args.host,
            username=getattr(args, "username", None),
            ssh_key=getattr(args, "ssh_key", None),
        )

    if cmd == "ssh":
        from lib.sysadmin_ssh import run_ssh
        remote_command = getattr(args, "remote_command", [])
        # strip leading '--' from REMAINDER
        if remote_command and remote_command[0] == "--":
            remote_command = remote_command[1:]
        return run_ssh(
            args.host,
            username=getattr(args, "username", None),
            ssh_key=getattr(args, "ssh_key", None),
            port=getattr(args, "port", None),
            remote_command=remote_command or None,
        )

    if cmd == "push":
        from lib.sysadmin_transfer import run_push
        return run_push(
            args.local_path,
            args.remote,
            username=getattr(args, "username", None),
            ssh_key=getattr(args, "ssh_key", None),
            port=getattr(args, "port", None),
            delete=args.delete,
            dry_run=args.dry_run,
        )

    if cmd == "pull":
        from lib.sysadmin_transfer import run_pull
        return run_pull(
            args.remote,
            getattr(args, "local_path", None),
            username=getattr(args, "username", None),
            ssh_key=getattr(args, "ssh_key", None),
            port=getattr(args, "port", None),
            dry_run=args.dry_run,
        )

    if cmd == "key_push":
        from lib.sysadmin_keys import run_key_push
        return run_key_push(
            args.host,
            username=getattr(args, "username", None),
            ssh_key=getattr(args, "ssh_key", None),
            pubkey_path=args.pubkey,
        )

    if cmd == "key":
        import sys
        print("Error: key subcommand required (push)", file=sys.stderr)
        return 1

    import sys
    print(f"Error: unknown sysadmin command {cmd!r}", file=sys.stderr)
    return 1
